"""Typed read-only client for Bitget PUBLIC market endpoints (no key, no orders).

Endpoints (paths from Bitget-AI/agent-sdk openapi.yaml and CRIT5; each verified
with one live GET on 2026-10-05 ~19:35 UTC, raw replies saved under
tests/fixtures/market/):

  GET /api/v3/market/instruments  ?category=&symbol=      min order, tick, step
  GET /api/v3/market/tickers      ?category=&symbol=      last, best bid/ask
  GET /api/v3/market/orderbook    ?category=&symbol=&limit=   depth levels
  GET /api/v3/market/candles      ?category=&symbol=&interval=&limit=
  GET /api/v2/spot/public/symbols ?symbol=                spot fee rates (v3 instruments has none for SPOT)
  GET /api/v3/reality/market/states                       US session windows for rTokens

Observed wire facts (not assumptions):
- Envelope {code:"00000", msg, requestTime, data}. Unknown symbol -> code "40034", data null.
- Instruments/tickers/candles send numbers as strings; the v3 orderbook sends
  JSON numbers. Empty strings mean "not set". Both are handled.
- An empty book is {"a":[],"b":[],"ts":...} (e.g. RSOXLUSDT) and is valid, not an error.
- limit=200 on the rNVDA spot book returned only 55-56 levels per side: the
  visible native book is short.
Assumption: book sizes are in BASE units (shares of the rToken / perp base coin).
This matches CRIT5's top-of-book notionals; Bitget's doc page was not re-read here.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import httpx
from pydantic import BaseModel, ConfigDict

from .schema import Provenance

BASE_URL = "https://api.bitget.com"


class Category(str, Enum):
    SPOT = "SPOT"
    USDT_FUTURES = "USDT-FUTURES"


class BitgetAPIError(RuntimeError):
    """Non-"00000" code, HTTP error, or a body that is not the documented envelope."""

    def __init__(self, code: str, msg: str, path: str = ""):
        super().__init__(f"{path}: Bitget code {code}: {msg}")
        self.code, self.msg, self.path = code, msg, path


def num(x: Any) -> float | None:
    """String or number -> float. None / "" -> None (Bitget uses "" for unset)."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    return float(s) if s else None


def _req(x: Any, field: str) -> float:
    v = num(x)
    if v is None:
        raise BitgetAPIError("SCHEMA", f"required numeric field {field!r} missing or empty")
    return v


# --------------------------------------------------------------------------- models


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    category: Category
    base_coin: str
    quote_coin: str
    status: str
    symbol_type: str | None            # "stock" for rTokens and stock perps
    is_reality: bool                    # spot rToken flag ("isReality":"yes")
    min_order_usdt: float               # minOrderAmount (quote); read per symbol, 10 or 20 for rTokens
    min_order_qty: float
    tick: float                         # 10 ** -pricePrecision
    qty_step: float                     # 10 ** -quantityPrecision
    max_market_order_usdt: float | None  # spot maxMarketOrderAmount, None if absent
    maker_fee: float | None             # futures instruments carry it; SPOT v3 does not
    taker_fee: float | None
    # Raw field only. Documented as "ratio of the buy limit price to the market price";
    # the doc never states the band or its reference price, so nothing here enforces it.
    buy_limit_price_ratio_raw: float | None
    sell_limit_price_ratio_raw: float | None


class Ticker(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    category: Category
    ts_ms: int
    last: float | None
    bid1: float | None
    ask1: float | None
    bid1_size: float | None
    ask1_size: float | None
    mark: float | None = None
    index: float | None = None
    funding_rate: float | None = None


class Level(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: float
    size: float          # base units (assumption, see module docstring)

    @property
    def notional(self) -> float:
        return self.price * self.size


class OrderBook(BaseModel):
    """Point-in-time snapshot. bids high->low, asks low->high.

    provenance: REPLAY_NATIVE for a real Bitget book (fetched live or read back
    from a capture file); SIM_PAPER for anything synthetic (hand-built test books,
    demo/paptrading books). Estimates derived from it inherit this label.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    category: Category
    ts_ms: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    provenance: Provenance = Provenance.REPLAY_NATIVE

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2

    @property
    def spread_bps(self) -> float | None:
        m = self.mid
        return None if m is None else (self.asks[0].price - self.bids[0].price) / m * 1e4

    @property
    def is_empty(self) -> bool:
        return not self.bids and not self.asks


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    base_volume: float | None
    quote_volume: float | None


class SpotFees(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    maker_fee: float | None
    taker_fee: float | None    # standard rate from the public symbol list, before VIP/BGB discounts


class SessionWindow(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: str        # pre_market | regular | after_hours | overnight
    start: str        # "HH:MM"
    end: str
    tz_label: str     # as sent ("EST"); CRIT5: the label looks stale, treat as America/New_York


# --------------------------------------------------------------------------- parsers


def _unwrap(body: Any, path: str = "") -> Any:
    if not isinstance(body, dict) or "code" not in body:
        raise BitgetAPIError("SCHEMA", "response is not the {code,msg,data} envelope", path)
    if str(body["code"]) != "00000":
        raise BitgetAPIError(str(body["code"]), str(body.get("msg", "")), path)
    return body.get("data")


def _list(data: Any) -> list:
    if data is None:
        return []
    if isinstance(data, dict) and "list" in data:
        return data["list"] or []
    if isinstance(data, list):
        return data
    raise BitgetAPIError("SCHEMA", f"expected a list, got {type(data).__name__}")


def _step(precision: Any) -> float:
    p = num(precision)
    if p is None:
        raise BitgetAPIError("SCHEMA", "precision field missing")
    return 10.0 ** (-int(p))


def parse_instrument(row: dict) -> Instrument:
    return Instrument(
        symbol=row["symbol"],
        category=Category(row["category"]),
        base_coin=row.get("baseCoin", ""),
        quote_coin=row.get("quoteCoin", ""),
        status=row.get("status", ""),
        symbol_type=row.get("symbolType") or None,
        is_reality=str(row.get("isReality", "")).lower() == "yes",
        min_order_usdt=_req(row.get("minOrderAmount"), "minOrderAmount"),
        min_order_qty=_req(row.get("minOrderQty"), "minOrderQty"),
        tick=_step(row.get("pricePrecision")),
        qty_step=_step(row.get("quantityPrecision")),
        max_market_order_usdt=num(row.get("maxMarketOrderAmount")),
        maker_fee=num(row.get("makerFeeRate")),
        taker_fee=num(row.get("takerFeeRate")),
        buy_limit_price_ratio_raw=num(row.get("buyLimitPriceRatio")),
        sell_limit_price_ratio_raw=num(row.get("sellLimitPriceRatio")),
    )


def parse_ticker(row: dict) -> Ticker:
    return Ticker(
        symbol=row["symbol"], category=Category(row["category"]), ts_ms=int(_req(row.get("ts"), "ts")),
        last=num(row.get("lastPrice")), bid1=num(row.get("bid1Price")), ask1=num(row.get("ask1Price")),
        bid1_size=num(row.get("bid1Size")), ask1_size=num(row.get("ask1Size")),
        mark=num(row.get("markPrice")), index=num(row.get("indexPrice")), funding_rate=num(row.get("fundingRate")),
    )


def _levels(rows: Any, reverse: bool) -> tuple[Level, ...]:
    out = []
    for r in rows or []:
        p, s = num(r[0]), num(r[1])
        if p is None or s is None or p <= 0 or s <= 0:
            continue                        # drop zero/garbage levels rather than invent them
        out.append(Level(price=p, size=s))
    out.sort(key=lambda lv: lv.price, reverse=reverse)
    return tuple(out)


def parse_orderbook(data: Any, symbol: str, category: Category | str,
                    provenance: Provenance = Provenance.REPLAY_NATIVE) -> OrderBook:
    data = data or {}
    ts = num(data.get("ts"))
    return OrderBook(symbol=symbol, category=Category(category), ts_ms=int(ts) if ts is not None else 0,
                     bids=_levels(data.get("b"), reverse=True), asks=_levels(data.get("a"), reverse=False),
                     provenance=provenance)


def parse_candle(row: list) -> Candle:
    return Candle(ts_ms=int(_req(row[0], "ts")), open=_req(row[1], "open"), high=_req(row[2], "high"),
                  low=_req(row[3], "low"), close=_req(row[4], "close"),
                  base_volume=num(row[5]) if len(row) > 5 else None,
                  quote_volume=num(row[6]) if len(row) > 6 else None)


# --------------------------------------------------------------------------- fetcher


class Fetcher:
    """Public GETs only. Pass an httpx.Client (e.g. with a MockTransport in tests)."""

    def __init__(self, client: httpx.Client | None = None, base_url: str = BASE_URL, timeout: float = 10.0):
        self._own = client is None
        self.client = client or httpx.Client(timeout=timeout)
        self.base_url = base_url.rstrip("/")

    def close(self) -> None:
        if self._own:
            self.client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *a) -> None:
        self.close()

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self.client.get(self.base_url + path, params={k: v for k, v in (params or {}).items() if v is not None})
        try:
            body = r.json()
        except ValueError:
            raise BitgetAPIError(f"HTTP{r.status_code}", "non-JSON body", path)
        if r.status_code != 200 and not (isinstance(body, dict) and "code" in body):
            raise BitgetAPIError(f"HTTP{r.status_code}", str(body)[:200], path)
        return _unwrap(body, path)

    def instrument(self, symbol: str, category: Category | str = Category.SPOT) -> Instrument:
        rows = _list(self._get("/api/v3/market/instruments", {"category": Category(category).value, "symbol": symbol}))
        if not rows:
            raise BitgetAPIError("EMPTY", f"no instrument row for {symbol}", "/api/v3/market/instruments")
        return parse_instrument(rows[0])

    def ticker(self, symbol: str, category: Category | str = Category.SPOT) -> Ticker | None:
        rows = _list(self._get("/api/v3/market/tickers", {"category": Category(category).value, "symbol": symbol}))
        return parse_ticker(rows[0]) if rows else None

    def tickers(self, category: Category | str = Category.SPOT) -> list[Ticker]:
        return [parse_ticker(r) for r in _list(self._get("/api/v3/market/tickers", {"category": Category(category).value}))]

    def orderbook(self, symbol: str, category: Category | str = Category.SPOT, limit: int = 200) -> OrderBook:
        """limit: documented max 200. An empty book comes back as an OrderBook with no levels."""
        data = self._get("/api/v3/market/orderbook",
                         {"category": Category(category).value, "symbol": symbol, "limit": str(limit)})
        return parse_orderbook(data, symbol, category)

    def candles(self, symbol: str, category: Category | str = Category.SPOT, interval: str = "1m",
                limit: int = 100) -> list[Candle]:
        rows = _list(self._get("/api/v3/market/candles", {"category": Category(category).value, "symbol": symbol,
                                                          "interval": interval, "limit": str(limit)}))
        return sorted((parse_candle(r) for r in rows), key=lambda c: c.ts_ms)

    def spot_fees(self, symbol: str) -> SpotFees | None:
        rows = _list(self._get("/api/v2/spot/public/symbols", {"symbol": symbol}))
        if not rows:
            return None
        r = rows[0]
        return SpotFees(symbol=r["symbol"], maker_fee=num(r.get("makerFeeRate")), taker_fee=num(r.get("takerFeeRate")))

    def reality_states(self) -> list[SessionWindow]:
        data = self._get("/api/v3/reality/market/states") or {}
        return [SessionWindow(state=s["state"], start=s["startTime"], end=s["endTime"], tz_label=s.get("timeZone", ""))
                for s in (data.get("stateList") or [])]


# --------------------------------------------------------------------------- recorded books


def books_from_jsonl(path: str | Path) -> Iterator[OrderBook]:
    """Read a capture written by scripts/capture_books.py back as REPLAY_NATIVE books."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("error"):
                continue
            yield parse_orderbook(rec["data"], rec["symbol"], rec["category"], Provenance.REPLAY_NATIVE)
