"""Execution-cost estimates on ONE point-in-time order-book snapshot.

What this is: a zero-parameter depth walk (VWAP of consuming visible levels),
the same model VERIFY_paper_fills.md 4a replayed against real weekend rNVDA
prints (covered 74-78% at +0 bps, 93-97% within +2 bps; weekend native flow only).

What this is NOT (stated so no caller over-reads a number):
- no queue model, no hidden/iceberg liquidity, no latency, no price drift;
- no own impact beyond the walk itself (we do not model how others react);
- no refill model: we do not know how fast levels come back. Two labelled
  extremes are given instead: OPTIMISTIC_FULL_REFILL_ASSUMED (every child sees
  the full snapshot again) and PESSIMISTIC_NO_REFILL (children eat the snapshot
  cumulatively, i.e. one walk of the whole parent). Reality is not guaranteed to
  sit between them: the book can also thin or move away between snapshot and send;
- fees are excluded from cost_bps (reported separately by cost_report).

Policy knobs (participation fraction, 50 bps window, 3x depth rule) are choices
given in the brief, not measured quantities.

Provenance: every result carries the book's label. REPLAY_NATIVE = real Bitget
book (live or recorded); SIM_PAPER = synthetic book. SIM_* never calibrates.
These are PREDICTIONS; calibration needs observed fills compared against them.
"""
from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from .market import Instrument, OrderBook
from .schema import Provenance

PESSIMISTIC = "PESSIMISTIC_NO_REFILL"
OPTIMISTIC = "OPTIMISTIC_FULL_REFILL_ASSUMED"
SINGLE_WALK = "DEPTH_WALK_SNAPSHOT"


def may_calibrate(p: Provenance) -> bool:
    """Hard rule: nothing labelled SIM_* may move a model parameter."""
    return not p.value.startswith("SIM_")


def _side(side: str) -> str:
    s = side.lower()
    if s not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, got {side!r}")
    return s


class WalkResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: str
    size_in: str                   # "quote" (USDT) or "base"
    requested: float
    filled: float                  # same unit as requested
    unfilled: float                # remainder the visible book could NOT absorb; never assumed to clear
    fill_fraction: float
    filled_base: float
    filled_quote: float
    avg_price: float | None
    mid: float | None
    cost_bps: float | None         # vs mid, positive = worse than mid; None if no mid or nothing filled
    worst_price: float | None
    levels_used: int
    book_ts_ms: int
    label: str = SINGLE_WALK
    provenance: Provenance


def depth_walk(book: OrderBook, side: str, size: float, size_in: str = "quote", label: str = SINGLE_WALK) -> WalkResult:
    """Walk the visible levels for `size` (USDT by default). Buy walks asks, sell walks bids.

    Ignores the quantity step inside the walk (sub-step rounding is a validate_order concern).
    """
    side = _side(side)
    if size_in not in ("quote", "base"):
        raise ValueError("size_in must be 'quote' or 'base'")
    if size <= 0:
        raise ValueError("size must be positive")
    levels = book.asks if side == "buy" else book.bids
    rem, base, quote, used, worst = size, 0.0, 0.0, 0, None
    for lv in levels:
        if rem <= 1e-12:
            break
        if size_in == "quote":
            take_q = min(rem, lv.notional)
            take_b = take_q / lv.price
            rem -= take_q
        else:
            take_b = min(rem, lv.size)
            take_q = take_b * lv.price
            rem -= take_b
        base += take_b
        quote += take_q
        used += 1
        worst = lv.price
    rem = max(rem, 0.0)
    filled = size - rem
    avg = quote / base if base > 0 else None
    mid = book.mid
    cost = None
    if avg is not None and mid:
        cost = (avg - mid) / mid * 1e4 if side == "buy" else (mid - avg) / mid * 1e4
    return WalkResult(symbol=book.symbol, side=side, size_in=size_in, requested=size, filled=filled,
                      unfilled=rem if rem > 1e-9 else 0.0, fill_fraction=filled / size,
                      filled_base=base, filled_quote=quote, avg_price=avg, mid=mid, cost_bps=cost,
                      worst_price=worst, levels_used=used, book_ts_ms=book.ts_ms, label=label,
                      provenance=book.provenance)


def pessimistic_bound(book: OrderBook, side: str, size_usdt: float) -> WalkResult:
    """Whole parent walked through ONE snapshot: no refill between child orders.

    Pessimistic relative to the snapshot only. It is NOT a guaranteed worst case:
    the book can thin or move between the snapshot and the send.
    """
    return depth_walk(book, side, size_usdt, "quote", label=PESSIMISTIC)


def depth_within_bps(book: OrderBook, side: str, bps: float = 50.0) -> float | None:
    """USDT notional on the side we would take (asks for a buy) within `bps` of mid. None if no mid."""
    side = _side(side)
    mid = book.mid
    if mid is None:
        return None
    if side == "buy":
        lim = mid * (1 + bps / 1e4)
        return sum(lv.notional for lv in book.asks if lv.price <= lim + 1e-12)
    lim = mid * (1 - bps / 1e4)
    return sum(lv.notional for lv in book.bids if lv.price >= lim - 1e-12)


# --------------------------------------------------------------------------- order rules


class OrderCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    reasons: tuple[str, ...]
    notional_usdt: float
    min_order_usdt: float
    qty: float | None               # quantity floored to the step at `ref_price`
    notional_after_rounding: float | None
    ref_price: float | None
    notes: tuple[str, ...] = ()


def _floor_step(x: float, step: float) -> float:
    n = math.floor(x / step + 1e-9)
    dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(n * step, dec)


def validate_order(instr: Instrument, notional_usdt: float, ref_price: float | None,
                   limit_price: float | None = None, order_type: str = "market", side: str = "buy") -> OrderCheck:
    """Minimum order (USDT), quantity step, tick, status and the documented market-order cap.

    ref_price: price used to convert USDT into quantity (best price on the side taken,
    or the limit price). The price band field is NOT enforced: Bitget documents it only
    as a "ratio to market price" without the band or the reference, so we do not guess.
    Spot MARKET BUY is sized in the quote coin (CRIT5 2.1), so no quantity-step rounding
    applies to it. For every other order, if flooring to the step pushes the notional
    under the minimum we reject. That is conservative: whether Bitget checks the
    minimum before or after rounding was not verified (no orders are placed).
    """
    side = _side(side)
    reasons: list[str] = []
    notes = ["price band not checked: buyLimitPriceRatio semantics are not documented"]
    quote_sized = instr.category.value == "SPOT" and order_type == "market" and side == "buy"
    if quote_sized:
        notes.append("spot market buy is sized in USDT: quantity step does not apply")
    if instr.status != "online":
        reasons.append(f"instrument status is {instr.status!r}, not 'online'")
    if notional_usdt < instr.min_order_usdt - 1e-9:
        reasons.append(f"{notional_usdt:.2f} USDT is below the minimum order of {instr.min_order_usdt:g} USDT")
    if order_type == "market" and instr.max_market_order_usdt and notional_usdt > instr.max_market_order_usdt:
        reasons.append(f"above the market-order cap of {instr.max_market_order_usdt:g} USDT")
    if limit_price is not None:
        k = limit_price / instr.tick
        if abs(k - round(k)) > 1e-6:
            reasons.append(f"limit price {limit_price} is not on the {instr.tick:g} tick")
    px = limit_price if limit_price is not None else ref_price
    qty = after = None
    if px and px > 0 and quote_sized:
        qty, after = notional_usdt / px, notional_usdt          # indicative quantity only
    elif px and px > 0:
        qty = _floor_step(notional_usdt / px, instr.qty_step)
        after = qty * px
        if qty < instr.min_order_qty - 1e-12:
            reasons.append(f"quantity {qty:g} after rounding to step {instr.qty_step:g} is below the minimum "
                           f"quantity {instr.min_order_qty:g}")
        elif after < instr.min_order_usdt - 1e-9 and notional_usdt >= instr.min_order_usdt - 1e-9:
            reasons.append(f"after rounding to step {instr.qty_step:g} the order is {after:.2f} USDT, below the "
                           f"{instr.min_order_usdt:g} USDT minimum")
    else:
        notes.append("no reference price (empty side): quantity step not checked")
    return OrderCheck(ok=not reasons, reasons=tuple(reasons), notional_usdt=notional_usdt,
                      min_order_usdt=instr.min_order_usdt, qty=qty, notional_after_rounding=after,
                      ref_price=px, notes=tuple(notes))


# --------------------------------------------------------------------------- slicing


class SlicePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: str
    parent_usdt: float
    participation: float              # policy: child <= participation x depth within window
    window_bps: float
    depth_window_usdt: float | None
    child_cap_usdt: float | None
    n_children: int | None
    child_usdt: float | None
    child_check: OrderCheck | None
    feasible: bool
    advise_slower: bool
    advice: str
    optimistic: WalkResult | None     # each child sees the full snapshot again (refill ASSUMED, unmeasured)
    pessimistic: WalkResult           # no refill: one walk of the whole parent
    book_ts_ms: int
    provenance: Provenance


def slice_plan(book: OrderBook, instr: Instrument, side: str, parent_usdt: float, participation: float = 0.10,
               window_bps: float = 50.0, slow_multiple: float = 3.0) -> SlicePlan:
    """Participation-capped child orders priced on one snapshot.

    participation default 0.10 is a policy choice (not measured). Advice to slow down
    fires when visible depth within `window_bps` is under `slow_multiple` x the parent.
    """
    side = _side(side)
    if not 0 < participation <= 1:
        raise ValueError("participation must be in (0, 1]")
    pess = pessimistic_bound(book, side, parent_usdt)
    d = depth_within_bps(book, side, window_bps)
    common = dict(symbol=book.symbol, side=side, parent_usdt=parent_usdt, participation=participation,
                  window_bps=window_bps, depth_window_usdt=d, pessimistic=pess, book_ts_ms=book.ts_ms,
                  provenance=book.provenance)
    if not d:
        why = "book has no mid (a side is empty)" if d is None else f"no visible depth within {window_bps:g} bps"
        return SlicePlan(child_cap_usdt=None, n_children=None, child_usdt=None, child_check=None, feasible=False,
                         advise_slower=True, advice=f"Do not send: {why}. The snapshot shows nothing to trade against.",
                         optimistic=None, **common)
    cap = participation * d
    n = max(1, math.ceil(parent_usdt / cap - 1e-9))
    child = parent_usdt / n
    ref = book.best_ask if side == "buy" else book.best_bid
    chk = validate_order(instr, child, ref, side=side)
    slower = d < slow_multiple * parent_usdt
    opt = depth_walk(book, side, child, "quote", label=OPTIMISTIC)
    if not chk.ok:
        advice = (f"Cannot slice: a child of {child:.2f} USDT fails the order rules ({'; '.join(chk.reasons)}). "
                  f"Visible depth within {window_bps:g} bps is {d:,.0f} USDT; at {participation:.0%} participation "
                  f"the cap per child is {cap:,.2f} USDT. Reduce the order or wait for depth.")
    elif slower:
        advice = (f"Slower mode advised: depth within {window_bps:g} bps is {d:,.0f} USDT, under "
                  f"{slow_multiple:g}x the order ({slow_multiple * parent_usdt:,.0f} USDT). Send {n} children of "
                  f"{child:,.2f} USDT spaced out; how fast the book refills is NOT known from one snapshot.")
    elif n > 1:
        advice = f"Split into {n} children of {child:,.2f} USDT (each <= {participation:.0%} of visible depth)."
    else:
        advice = f"Single order is within {participation:.0%} of visible depth within {window_bps:g} bps."
    return SlicePlan(child_cap_usdt=cap, n_children=n, child_usdt=child, child_check=chk, feasible=chk.ok,
                     advise_slower=slower or not chk.ok, advice=advice, optimistic=opt, **common)


class TwapBenchmark(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: str
    parent_usdt: float
    minutes: int
    n_slices: int
    slice_usdt: float
    slice_check: OrderCheck
    optimistic: WalkResult      # every slice sees the full snapshot (refill assumed)
    pessimistic: WalkResult     # slices consume the snapshot cumulatively (no refill)
    assumptions: tuple[str, ...]
    book_ts_ms: int
    provenance: Provenance


def twap_benchmark(book: OrderBook, instr: Instrument, side: str, parent_usdt: float, minutes: int) -> TwapBenchmark:
    """Bitget-TWAP-LIKE benchmark: `minutes` equal slices, one per minute, on the SAME snapshot.

    Bitget's own TWAP parameters (interval, randomisation, price limits) are not modelled.
    """
    side = _side(side)
    if minutes < 1:
        raise ValueError("minutes must be >= 1")
    sl = parent_usdt / minutes
    ref = book.best_ask if side == "buy" else book.best_bid
    return TwapBenchmark(
        symbol=book.symbol, side=side, parent_usdt=parent_usdt, minutes=minutes, n_slices=minutes, slice_usdt=sl,
        slice_check=validate_order(instr, sl, ref, side=side),
        optimistic=depth_walk(book, side, sl, "quote", label=OPTIMISTIC),
        pessimistic=pessimistic_bound(book, side, parent_usdt),
        assumptions=("equal slices, one per minute (Bitget TWAP settings not modelled)",
                     "mid frozen at the snapshot for all minutes: no drift, no timing risk",
                     "refill unknown: optimistic assumes full refill, pessimistic assumes none"),
        book_ts_ms=book.ts_ms, provenance=book.provenance)
