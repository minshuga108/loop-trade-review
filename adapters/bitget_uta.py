"""Adapter for Bitget UTA v3 API responses (fills, history-position).

Facts used here come from data/bitget_samples/SCHEMA.md (every field sourced):
- all numbers are strings; times are Unix milliseconds
- fills feeDetail fee is POSITIVE (a cost); history-position fees are NEGATIVE
- tradeSide may be missing in older rows: fall back to execPnl
- history-position netProfit = cumRealisedPnl + openFeeTotal + closeFeeTotal + totalFunding
- a position appears only once it is flat; its life is [createdTime, updatedTime]

The API gives no start_position on fills, so round trips are anchored on
history-position (authoritative flat-to-flat lifecycle), not rebuilt from fills.
An unknown response shape raises SchemaDrift instead of being guessed.
"""
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict

from engine.schema import Fill, Provenance, RoundTrip

QUOTE_COINS = {"USDT", "USDC"}


class SchemaDrift(ValueError):
    """The response does not look like the documented shape."""


class PositionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    position_id: str
    symbol: str
    category: str
    pos_side: str
    t_open_ms: int
    t_close_ms: int
    open_avg: float
    open_total: float
    gross_pnl: float          # cumRealisedPnl, excludes fees and funding
    net_pnl: float            # netProfit, includes fees and funding
    fees: float               # POSITIVE number = cost (sign normalised)
    funding: float            # negative = paid


def _rows(resp: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(resp, dict) or "data" not in resp:
        raise SchemaDrift("response has no 'data' envelope")
    if str(resp.get("code")) != "00000":
        raise SchemaDrift(f"API error code {resp.get('code')}: {resp.get('msg')}")
    data = resp["data"]
    lst = data.get("list") if isinstance(data, dict) else None
    return lst or []                       # real empty pages carry null, not []


def _need(row: dict[str, Any], keys: tuple[str, ...], what: str) -> None:
    missing = [k for k in keys if k not in row]
    if missing:
        raise SchemaDrift(f"{what} row is missing {missing}")


def _f(x: Any) -> float:
    if x is None or x == "":
        return 0.0
    if isinstance(x, bool) or not isinstance(x, (str, int, float)):
        raise SchemaDrift(f"expected a number string, got {type(x).__name__}")
    try:
        v = float(x)
    except ValueError:
        raise SchemaDrift(f"not a number: {str(x)[:40]!r}") from None
    if not math.isfinite(v):
        raise SchemaDrift(f"non-finite number {str(x)[:40]!r}")
    return v


def _ms(x: Any) -> int:
    if isinstance(x, bool) or not isinstance(x, (str, int)):
        raise SchemaDrift(f"timestamp must be integer milliseconds, got {type(x).__name__}")
    try:
        return int(x)
    except ValueError:
        raise SchemaDrift(f"timestamp is not integer milliseconds: {str(x)[:40]!r}") from None


def _row(r: Any, what: str) -> dict[str, Any]:
    if not isinstance(r, dict):
        raise SchemaDrift(f"{what} row is not an object")
    return r


def parse_fills(resp: dict[str, Any], account: str, provenance: Provenance = Provenance.REAL_OWN) -> list[Fill]:
    out: list[Fill] = []
    for r in _rows(resp):
        r = _row(r, "fill")
        _need(r, ("execId", "orderId", "symbol", "side", "execPrice", "execQty", "createdTime"), "fill")
        price, qty = _f(r["execPrice"]), _f(r["execQty"])
        pnl = _f(r.get("execPnl"))
        ts = str(r.get("tradeSide") or "").lower()
        if ts:
            if ts.startswith("open"):
                is_open = True
            elif any(k in ts for k in ("close", "reduce", "burst", "offset", "delivery")):
                is_open = False
            else:                              # one-way mode (buy_single / sell_single): only execPnl tells
                is_open = pnl == 0.0
        else:
            is_open = pnl == 0.0              # tradeSide missing in older rows: fall back to execPnl
        fee = 0.0
        details = r.get("feeDetail") or []
        if not isinstance(details, list):
            raise SchemaDrift("feeDetail is not a list")
        for d in details:
            d = _row(d, "feeDetail")
            fee_amt = _f(d.get("fee"))
            fee += fee_amt if d.get("feeCoin") in QUOTE_COINS or not d.get("feeCoin") else fee_amt * price
        if str(r["side"]).lower() not in ("buy", "sell"):
            raise SchemaDrift(f"fill side must be buy or sell, got {str(r['side'])[:20]!r}")
        out.append(Fill(venue="bitget", account=account, exec_id=str(r["execId"]), order_id=str(r["orderId"]),
                        t_ms=_ms(r["createdTime"]), symbol=str(r["symbol"]).upper(), side=str(r["side"]).lower(),
                        is_open=is_open, price=price, size=qty, fee=fee, realized_pnl=pnl,
                        start_position=0.0, provenance=provenance))
    return out


def parse_positions(resp: dict[str, Any]) -> list[PositionRecord]:
    out: list[PositionRecord] = []
    for r in _rows(resp):
        r = _row(r, "position")
        _need(r, ("positionId", "symbol", "posSide", "createdTime", "updatedTime", "netProfit", "cumRealisedPnl"), "position")
        fees = -(_f(r.get("openFeeTotal")) + _f(r.get("closeFeeTotal")))   # stored negative; normalise to a positive cost
        gross, funding, net = _f(r["cumRealisedPnl"]), _f(r.get("totalFunding")), _f(r["netProfit"])
        # documented identity; a mismatch means the sign convention or the schema changed
        if abs(net - (gross - fees + funding)) > 0.01:
            raise SchemaDrift(f"position {r['positionId']}: netProfit {net} != gross {gross} - fees {fees} + funding {funding}")
        out.append(PositionRecord(position_id=str(r["positionId"]), symbol=str(r["symbol"]).upper(),
                                  category=str(r.get("category", "")), pos_side=str(r["posSide"]).lower(),
                                  t_open_ms=_ms(r["createdTime"]), t_close_ms=_ms(r["updatedTime"]),
                                  open_avg=_f(r.get("openPriceAvg")), open_total=_f(r.get("openTotalPos")),
                                  gross_pnl=gross, net_pnl=net, fees=fees, funding=funding))
    return out


def trips_from_positions(positions: list[PositionRecord], fills: list[Fill],
                         provenance: Provenance = Provenance.REAL_OWN) -> list[RoundTrip]:
    """One RoundTrip per closed position. First-order notional comes from the opening
    fills of the earliest opening order inside the position's life; if no fill is
    available (window cut) the whole opened notional is used and nothing is guessed."""
    trips = []
    for p in positions:
        inside = [f for f in fills if f.symbol == p.symbol and f.is_open and p.t_open_ms - 5_000 <= f.t_ms <= p.t_close_ms]
        opened = p.open_total * p.open_avg
        if inside:
            first_oid = min(inside, key=lambda f: f.t_ms).order_id
            first = sum(f.price * f.size for f in inside if f.order_id == first_oid)
        else:
            first = opened
        trips.append(RoundTrip(symbol=p.symbol, t_open_ms=p.t_open_ms, t_close_ms=p.t_close_ms,
                               side="buy" if p.pos_side == "long" else "sell", first_order_notional=first,
                               opened_notional=opened, net_pnl=p.net_pnl, first_order_id=p.position_id,
                               provenance=provenance))
    return sorted(trips, key=lambda t: t.t_open_ms)
