"""Separate a stop the trader did not honour from a stop the market made impossible to honour.

Pure functions, no network: the caller supplies the price prints. A stop that the
market jumped over (a gap, e.g. a stock perp across a session break or a halt)
still costs money and stays in every cost number, but it is excluded from the
behavioural score, because no action of the trader could have filled it at the
stated level.

Tags per plan:
  NOT_TRIGGERED       no print reached the stop between open and exit (not a stop-out; ignored by the score)
  HONOURED            price reached the stop with prints near the level and the trader was out within EXIT_GRACE_MS
  BEHAVIOURAL_BREACH  price traded through the stop with prints near the level (or after a gap) and the trader
                      was still in the position more than EXIT_GRACE_MS later
  STRUCTURAL_GAP      the first print at or beyond the stop was already beyond it by more than GAP_TOLERANCE
                      (no print near the level, so the stop could not have been honoured at its price), and the
                      trader was out within EXIT_GRACE_MS of that print
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

from pydantic import BaseModel, ConfigDict

# --- pre-registered constants (fixed before looking at any demo wallet; never tuned on them) ---
GAP_TOLERANCE = 0.002     # 0.2 percent of the stop price: a first breaching print further than this is a gap
EXIT_GRACE_MS = 60_000    # the trader has 60 seconds after the breaching print to be out of the position
MIN_TRIGGERED = 10        # the behavioural score needs at least this many non-structural triggered stops

TAGS = ("NOT_TRIGGERED", "HONOURED", "BEHAVIOURAL_BREACH", "STRUCTURAL_GAP")


class StopPlan(BaseModel):
    """One trip's stated stop. The three fields the trader states (trip id, stop, side) plus the trip's
    window and exit, which come from the RoundTrip and its closing fill: "did the trader exit" cannot be
    decided without them."""
    model_config = ConfigDict(frozen=True)

    trip_id: str
    stop: float
    side: str              # "long"/"buy" or "short"/"sell": direction of the position
    t_open_ms: int
    t_exit_ms: int
    exit_price: float


class StopTag(BaseModel):
    model_config = ConfigDict(frozen=True)

    trip_id: str
    tag: str
    t_breach_ms: int | None = None
    breach_price: float | None = None
    gap_frac: float | None = None          # how far beyond the stop the first breaching print was (fraction of stop)
    exit_lag_ms: int | None = None         # exit time minus breach time
    exit_beyond_frac: float | None = None  # how far beyond the stop the actual exit was (cost, kept for every tag)


def _is_long(side: str) -> bool:
    s = side.lower()
    if s in ("long", "buy"):
        return True
    if s in ("short", "sell"):
        return False
    raise ValueError(f"unknown side {side!r}")


def _beyond(price: float, stop: float, long: bool) -> float:
    """Signed fraction by which `price` is past the stop (positive = past it, on the losing side)."""
    return (stop - price) / stop if long else (price - stop) / stop


def tag_stop_exits(plans: list[StopPlan | tuple], price_series: list[tuple[int, float]]) -> list[StopTag]:
    """Tag each plan. price_series is a list of (t_ms, price) sorted by time, for the plan's symbol.

    Plans may be StopPlan objects or tuples (trip_id, stop, side, t_open_ms, t_exit_ms, exit_price).
    """
    ts = [p[0] for p in price_series]
    if any(ts[i] > ts[i + 1] for i in range(len(ts) - 1)):
        raise ValueError("price_series must be sorted by time")
    out = []
    for raw in plans:
        p = raw if isinstance(raw, StopPlan) else StopPlan(**dict(zip(StopPlan.model_fields, raw)))
        long = _is_long(p.side)
        exit_beyond = _beyond(p.exit_price, p.stop, long)
        lo, hi = bisect_left(ts, p.t_open_ms), bisect_right(ts, p.t_exit_ms)
        breach = next((k for k in range(lo, hi) if _beyond(price_series[k][1], p.stop, long) >= 0), None)
        if breach is None:
            out.append(StopTag(trip_id=p.trip_id, tag="NOT_TRIGGERED", exit_beyond_frac=exit_beyond))
            continue
        tb, pb = price_series[breach]
        gap = _beyond(pb, p.stop, long)
        lag = p.t_exit_ms - tb
        late = lag > EXIT_GRACE_MS
        if late:
            tag = "BEHAVIOURAL_BREACH"
        elif gap > GAP_TOLERANCE:
            tag = "STRUCTURAL_GAP"
        else:
            tag = "HONOURED"
        out.append(StopTag(trip_id=p.trip_id, tag=tag, t_breach_ms=tb, breach_price=pb, gap_frac=gap,
                           exit_lag_ms=lag, exit_beyond_frac=exit_beyond))
    return out


def behavioural_score(tags: list[StopTag]) -> dict:
    """Share of triggered stops the trader honoured, EXCLUDING structural gaps (and untriggered stops).

    Structural gaps are still counted and returned (with their cost) so they stay in cost numbers.
    status: SCORED, or UNDERPOWERED below MIN_TRIGGERED behavioural-eligible stops.
    """
    counts = {k: sum(1 for t in tags if t.tag == k) for k in TAGS}
    eligible = counts["HONOURED"] + counts["BEHAVIOURAL_BREACH"]
    gap_cost = [t.exit_beyond_frac for t in tags if t.tag == "STRUCTURAL_GAP" and t.exit_beyond_frac is not None]
    res = {"counts": counts, "eligible": eligible,
           "structural_gap_exit_beyond_frac_sum": float(sum(gap_cost)),
           "score": float(counts["HONOURED"] / eligible) if eligible else float("nan")}
    if eligible < MIN_TRIGGERED:
        res["status"] = "UNDERPOWERED"
        res["detail"] = f"needs at least {MIN_TRIGGERED} triggered stops that were not gaps (has {eligible})"
    else:
        res["status"] = "SCORED"
        res["detail"] = "share of triggered stops honoured; structural gaps excluded from the score, kept in costs"
    return res
