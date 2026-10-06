"""Cached Bitget public book snapshots for the Check line.

The request path NEVER calls Bitget: a background thread refreshes a small
watchlist and requests read the cache. If the cache is empty or stale the card
says so instead of inventing a cost. Public read-only GETs only; no keys.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from engine import cost_report
from engine.market import Category, Fetcher

WATCH = [("RNVDAUSDT", Category.SPOT), ("RTSLAUSDT", Category.SPOT), ("RSPYUSDT", Category.SPOT), ("RQQQUSDT", Category.SPOT),
         ("RAAPLUSDT", Category.SPOT), ("RMSTRUSDT", Category.SPOT), ("NVDAUSDT", Category.USDT_FUTURES), ("TSLAUSDT", Category.USDT_FUTURES),
         ("BTCUSDT", Category.USDT_FUTURES), ("ETHUSDT", Category.USDT_FUTURES), ("SOLUSDT", Category.USDT_FUTURES)]
REFRESH_S = 60
STALE_S = 300


@dataclass
class Snap:
    instr: object
    book: object
    ticker: object
    fee: float | None
    fee_source: str
    windows: object
    fetched_at: float


CACHE: dict[str, Snap] = {}
_started = False


def refresh_once(fetcher: Fetcher | None = None) -> int:
    own = fetcher is None
    f = fetcher or Fetcher(timeout=4.0)
    ok = 0
    try:
        try:
            windows = f.reality_states()
        except Exception:
            windows = None
        for sym, cat in WATCH:
            try:
                instr = f.instrument(sym, cat)
                book = f.orderbook(sym, cat)
                tick = f.ticker(sym, cat)
                if cat is Category.SPOT:
                    sf = f.spot_fees(sym)
                    fee, src = (sf.taker_fee if sf else None), "standard spot taker fee, before discounts"
                else:
                    fee, src = instr.taker_fee, "instrument takerFeeRate"
                CACHE[sym] = Snap(instr, book, tick, fee, src, windows, time.time())
                ok += 1
            except Exception:
                continue                      # keep the previous snapshot for this symbol
    finally:
        if own:
            f.close()
    return ok


def start_refresher() -> None:
    global _started
    if _started or os.environ.get("LOOP_NO_REFRESH"):
        return
    _started = True

    def loop():
        while True:
            try:
                refresh_once()
            except Exception:
                pass
            time.sleep(REFRESH_S)
    threading.Thread(target=loop, daemon=True, name="book-refresher").start()


def resolve(symbol: str | None) -> str | None:
    """Map what a trader typed (RNVDA, rNVDA, NVDA, NVDAUSDT) to a cached symbol.

    A leading R means the rToken (spot); a bare ticker prefers the stock perp, then the rToken."""
    if not symbol:
        return None
    s = symbol.upper().replace("USDT", "")
    cands = [f"{s}USDT"] if (symbol[:1] == "r" or symbol[:1] == "R" and f"{s}USDT" in CACHE) else [f"{s}USDT", f"R{s}USDT"]
    for cand in cands:
        if cand in CACHE:
            return cand
    return None


def cost_line(symbol: str | None, size_usdt: float | None, side: str | None = "buy") -> dict:
    """The Check line for the gate and the card: from the cache only."""
    sym = resolve(symbol)
    if sym is None or not size_usdt:
        return {"available": False, "reason": "no recent book for that symbol, or no order size was read"}
    snap = CACHE[sym]
    age = time.time() - snap.fetched_at
    try:
        rep = cost_report.build_cost_report(snap.instr, snap.book, size_usdt, side or "buy", ticker=snap.ticker, taker_fee=snap.fee,
                                            fee_source=snap.fee_source, windows=snap.windows, now_ms=int(time.time() * 1000))
    except Exception as e:                    # a malformed snapshot must not take the gate or the card down
        return {"available": False, "reason": f"the cached book could not be used ({type(e).__name__}), so no cost estimate"}
    return {"available": True, "stale": age > STALE_S, "cache_age_s": round(age), "report": rep,
            "cost_bps": rep["cost"]["cost_bps"], "fill_fraction": rep["cost"]["fill_fraction"], "limit_bps": 30}


def price_of(symbol: str | None) -> dict | None:
    """Last cached book mid (else ticker last) for converting a coin quantity into USDT; None if absent or stale."""
    sym = resolve(symbol)
    if sym is None:
        return None
    snap = CACHE[sym]
    if time.time() - snap.fetched_at > STALE_S:
        return None
    px = snap.book.mid if snap.book is not None else None
    if px is None and snap.ticker is not None:
        px = snap.ticker.last
    return {"symbol": sym, "price": px, "age_s": round(time.time() - snap.fetched_at)} if px else None
