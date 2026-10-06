"""The "Check line" card: what would this order cost on the visible book right now?

Returns plain dicts (JSON-ready) for the web card. Every number comes from the
live/recorded book, the instrument row, or the ticker. Nothing is filled in.

Assumptions, stated plainly:
- Session windows come from GET /api/v3/reality/market/states. They are labelled
  "EST" by Bitget; CRIT5 2.2 judged that label stale, so we read them as
  America/New_York wall-clock times [inferred].
- "Weekend" = Saturday or Sunday on the America/New_York calendar. US holidays
  are out of scope (Bitget's own calendar endpoint was incomplete, CRIT5 2.2).
- Funding: only the measured CRIT5 3.1 finding is cited (settlement slots Sat 08:00
  to Mon 08:00 UTC were 0 in 13 of 13 observed weeks on NVDAUSDT, TSLAUSDT,
  SPYUSDT). Bitget does not document a weekend freeze; we never claim it for a
  slot outside that window, and we flag other symbols as unmeasured.
- Deep vs thin is relative to the order size (depth within 50 bps vs 3x size),
  ranked from live depth. No symbol is hard-coded as deep or thin.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .execution import (depth_walk, depth_within_bps, may_calibrate, slice_plan, twap_benchmark,
                        validate_order)
from .market import Category, Fetcher, Instrument, OrderBook, SessionWindow, Ticker

NY = ZoneInfo("America/New_York")
FUNDING_MEASURED_SYMBOLS = ("NVDAUSDT", "TSLAUSDT", "SPYUSDT")
# (weekday, hour UTC) of settlement slots measured as 0 in 13/13 weeks (CRIT5 3.1)
_ZERO_SLOTS = {(5, 8), (5, 16), (6, 0), (6, 8), (6, 16), (0, 0), (0, 8)}
DEPTH_WINDOW_BPS = 50.0
SLOW_MULTIPLE = 3.0


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def session_label(ts_ms: int, windows: list[SessionWindow] | None) -> dict:
    t = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc).astimezone(NY)
    out = {"et_time": t.strftime("%a %Y-%m-%d %H:%M %Z"), "weekend": t.weekday() >= 5,
           "source": "reality/market/states windows read as America/New_York; weekend = Sat/Sun ET; holidays not handled"}
    if out["weekend"]:
        out["label"] = "weekend (US market closed)"
        return out
    if not windows:
        out["label"] = "unknown (no session windows supplied)"
        return out
    m = t.hour * 60 + t.minute
    for w in windows:
        a, b = _hm(w.start), _hm(w.end)
        inside = a <= m < b if a < b else (m >= a or m < b)
        if inside:
            out["label"] = w.state
            return out
    out["label"] = "unknown (outside every published window)"
    return out


def funding_note(instr: Instrument, ts_ms: int, live_rate: float | None = None) -> dict:
    if instr.category is Category.SPOT:
        return {"applies": False, "text": "Spot rToken: no funding."}
    t = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc)
    nxt = (t.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=t.hour % 8)) + dt.timedelta(hours=8)
    slot = (nxt.weekday(), nxt.hour)
    out = {"applies": True, "next_slot_utc": nxt.strftime("%a %H:%M UTC"), "live_rate": live_rate,
           "assumption": "8h settlement grid at 00/08/16 UTC (fundInterval 8 for 320 of 325 stock perps, CRIT5)"}
    if slot in _ZERO_SLOTS:
        txt = ("Next settlement slot is in the Sat 08:00 to Mon 08:00 UTC window, where funding was 0 in 13 of 13 "
               "observed weeks (CRIT5 3.1, measured on NVDAUSDT, TSLAUSDT, SPYUSDT). Empirical, not documented by Bitget.")
        if instr.symbol not in FUNDING_MEASURED_SYMBOLS:
            txt += f" {instr.symbol} itself was not measured."
        out["measured_zero"] = True
    else:
        txt = "No zero-funding claim for this slot; use the live rate."
        out["measured_zero"] = False
    out["text"] = txt
    return out


def _ticker_vs_book(ticker: Ticker | None, book: OrderBook, tick: float) -> dict | None:
    if ticker is None or book.best_bid is None or book.best_ask is None or ticker.bid1 is None or ticker.ask1 is None:
        return None
    inside = ticker.bid1 > book.best_bid + tick / 2 or ticker.ask1 < book.best_ask - tick / 2
    d = {"ticker_bid": ticker.bid1, "ticker_ask": ticker.ask1, "book_bid": book.best_bid, "book_ask": book.best_ask,
         "ticker_inside_book": inside}
    if inside:
        d["note"] = ("The ticker quotes a tighter touch than the public order book. Bitget says US-session rToken "
                     "liquidity connects to brokerage infrastructure (VERIFY_paper_fills 4a); that routed price is not "
                     "in this book, so this estimate may overstate the cost. Not validated: no public weekday prints.")
    return d


def depth_rank(books: list[OrderBook], size_usdt: float, bps: float = DEPTH_WINDOW_BPS,
               multiple: float = SLOW_MULTIPLE) -> list[dict]:
    """Rank symbols by the thinner side's USDT depth within `bps` of mid. deep = >= multiple x size."""
    rows = []
    for b in books:
        bid = depth_within_bps(b, "sell", bps)
        ask = depth_within_bps(b, "buy", bps)
        if bid is None or ask is None:
            rows.append({"symbol": b.symbol, "depth_usdt": 0.0, "bid_depth_usdt": bid, "ask_depth_usdt": ask,
                         "spread_bps": None, "tier": "empty", "book_ts_ms": b.ts_ms, "provenance": b.provenance.value})
            continue
        d = min(bid, ask)
        rows.append({"symbol": b.symbol, "depth_usdt": d, "bid_depth_usdt": bid, "ask_depth_usdt": ask,
                     "spread_bps": b.spread_bps, "tier": "deep" if d >= multiple * size_usdt else "thin",
                     "book_ts_ms": b.ts_ms, "provenance": b.provenance.value})
    rows.sort(key=lambda r: r["depth_usdt"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _walk_dict(w) -> dict:
    return {"label": w.label, "cost_bps": w.cost_bps, "avg_price": w.avg_price, "fill_fraction": w.fill_fraction,
            "unfilled_usdt": w.unfilled, "levels_used": w.levels_used, "worst_price": w.worst_price}


def build_cost_report(instr: Instrument, book: OrderBook, size_usdt: float, side: str = "buy", *,
                      ticker: Ticker | None = None, taker_fee: float | None = None, fee_source: str | None = None,
                      windows: list[SessionWindow] | None = None, now_ms: int | None = None,
                      participation: float = 0.10, twap_minutes: int | None = None) -> dict:
    """Pure function: everything it needs is passed in, so it runs on fixtures and recordings."""
    as_of = now_ms if now_ms is not None else book.ts_ms
    walk = depth_walk(book, side, size_usdt)
    plan = slice_plan(book, instr, side, size_usdt, participation, DEPTH_WINDOW_BPS, SLOW_MULTIPLE)
    ref = book.best_ask if side == "buy" else book.best_bid
    chk = validate_order(instr, size_usdt, ref, side=side)
    fee_bps = taker_fee * 1e4 if taker_fee is not None else None
    caveats = [
        "Point-in-time snapshot: no queue, latency, hidden liquidity or price drift; no own impact beyond the walk.",
        "Cost is versus mid and excludes fees unless all_in_bps is shown.",
        "Optimistic assumes the book fully refills between children; pessimistic assumes no refill. Refill speed is unknown.",
    ]
    if walk.fill_fraction < 1:
        caveats.insert(0, f"The visible book cannot absorb the order: {walk.unfilled:,.2f} USDT unfilled. "
                          "We do not assume the rest clears.")
    if book.is_empty:
        caveats.insert(0, "The order book is empty: there is nothing to trade against.")
    sess = session_label(as_of, windows)
    if instr.is_reality and not sess["weekend"]:
        caveats.append("Weekday rToken cost cannot be validated from the public tape (no public weekday prints).")
    rep = {
        "symbol": instr.symbol, "category": instr.category.value, "side": side, "size_usdt": size_usdt,
        "as_of_ms": as_of, "book_ts_ms": book.ts_ms,
        "book_age_s": (as_of - book.ts_ms) / 1000 if book.ts_ms else None,
        "provenance": book.provenance.value,
        "calibration": ("estimate only; may be compared against real fills" if may_calibrate(book.provenance)
                        else "SIM book: never used for calibration"),
        "session": sess,
        "book": {"best_bid": book.best_bid, "best_ask": book.best_ask, "mid": book.mid, "spread_bps": book.spread_bps,
                 "levels_bid": len(book.bids), "levels_ask": len(book.asks),
                 "depth_50bps_usdt": plan.depth_window_usdt},
        "cost": _walk_dict(walk),
        "fees": {"taker_fee_bps": fee_bps, "source": fee_source},
        "all_in_bps": (walk.cost_bps + fee_bps) if (walk.cost_bps is not None and fee_bps is not None
                                                    and walk.fill_fraction >= 1) else None,
        "min_order": {"ok": chk.ok, "min_order_usdt": instr.min_order_usdt, "reasons": list(chk.reasons),
                      "qty": chk.qty, "tick": instr.tick, "qty_step": instr.qty_step, "notes": list(chk.notes)},
        "slicing": {"participation": participation, "window_bps": DEPTH_WINDOW_BPS, "n_children": plan.n_children,
                    "child_usdt": plan.child_usdt, "feasible": plan.feasible, "advise_slower": plan.advise_slower,
                    "advice": plan.advice,
                    "optimistic": _walk_dict(plan.optimistic) if plan.optimistic else None,
                    "pessimistic": _walk_dict(plan.pessimistic),
                    "policy_note": "participation 10%, 50 bps window and the 3x rule are policy choices, not measurements"},
        "ticker_vs_book": _ticker_vs_book(ticker, book, instr.tick),
        "funding": funding_note(instr, as_of, ticker.funding_rate if ticker else None),
        "caveats": caveats,
    }
    if twap_minutes:
        tw = twap_benchmark(book, instr, side, size_usdt, twap_minutes)
        rep["twap"] = {"minutes": tw.minutes, "slice_usdt": tw.slice_usdt, "slice_ok": tw.slice_check.ok,
                       "slice_reasons": list(tw.slice_check.reasons), "optimistic": _walk_dict(tw.optimistic),
                       "pessimistic": _walk_dict(tw.pessimistic), "assumptions": list(tw.assumptions)}
    return rep


def cost_report(fetcher: Fetcher, symbol: str, size_usdt: float, side: str = "buy",
                category: Category | str = Category.SPOT, twap_minutes: int | None = None,
                participation: float = 0.10, now_ms: int | None = None) -> dict:
    """Fetch instrument, book, ticker, fee and session windows (public GETs), then build the card."""
    cat = Category(category)
    instr = fetcher.instrument(symbol, cat)
    book = fetcher.orderbook(symbol, cat)
    tick = fetcher.ticker(symbol, cat)
    if cat is Category.SPOT:
        f = fetcher.spot_fees(symbol)
        fee, src = (f.taker_fee if f else None), "GET /api/v2/spot/public/symbols takerFeeRate (standard, before discounts)"
    else:
        fee, src = instr.taker_fee, "GET /api/v3/market/instruments takerFeeRate"
    try:
        windows = fetcher.reality_states()
    except Exception:                       # session label degrades to "unknown", the card still renders
        windows = None
    return build_cost_report(instr, book, size_usdt, side, ticker=tick, taker_fee=fee, fee_source=src,
                             windows=windows, now_ms=now_ms, participation=participation, twap_minutes=twap_minutes)


def rank_symbols(fetcher: Fetcher, symbols: list[str], size_usdt: float,
                 category: Category | str = Category.SPOT) -> list[dict]:
    return depth_rank([fetcher.orderbook(s, category) for s in symbols], size_usdt)


