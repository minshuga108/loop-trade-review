"""Required (breakeven) win rate at the trader's real costs and payoff ratio.

breakeven win rate = average loss / (average win + average loss), computed from
the trips' NET results, so fees (and anything else inside net_pnl) are already in.
A trader whose actual win rate sits above it made money on average per trip.

The uncertainty is reported as a 95 percent block-bootstrap INTERVAL over the
time-ordered trips. It is an interval for the quantity, not a probability that
the trader is or is not profitable. Block length is fixed by a stated rule
(ceil(sqrt(n))) so streaks of correlated trips are resampled together.
A sensitivity line repeats everything without the single best trade.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .schema import RoundTrip

# --- pre-registered constants (fixed before looking at any demo wallet; never tuned on them) ---
MIN_TRIPS = 30          # fewer trips than this and no interval is reported
MIN_EACH_SIDE = 5       # at least this many winning and losing trips
N_BOOT = 2000
CI_LEVEL = 0.95


def block_size(n: int) -> int:
    """Stated rule: block length = ceil(sqrt(n)), at least 1."""
    return max(1, math.ceil(math.sqrt(n)))


def _point(net: np.ndarray) -> tuple[float, float, float, float]:
    """(breakeven win rate, actual win rate, average win, average loss). Zero-pnl trips count as neither."""
    w, l = net[net > 0], net[net < 0]
    decided = len(w) + len(l)
    if len(w) == 0 or len(l) == 0:
        return float("nan"), (len(w) / decided if decided else float("nan")), float("nan"), float("nan")
    aw, al = float(np.mean(w)), float(-np.mean(l))
    return al / (aw + al), len(w) / decided, aw, al


def _block_boot(net: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Moving-block bootstrap of (breakeven, actual) win rates."""
    n = len(net)
    b = block_size(n)
    k = math.ceil(n / b)
    g = np.random.default_rng(seed)
    be, act = np.empty(N_BOOT), np.empty(N_BOOT)
    starts_max = n - b + 1
    for i in range(N_BOOT):
        st = g.integers(0, starts_max, k)
        s = np.concatenate([np.arange(x, x + b) for x in st])[:n]
        be[i], act[i], _, _ = _point(net[s])
    return be, act


def _ci(x: np.ndarray) -> tuple[float, float]:
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return (float("nan"), float("nan"))
    a = (1 - CI_LEVEL) / 2
    return (float(np.quantile(x, a)), float(np.quantile(x, 1 - a)))


@dataclass
class WinRate:
    status: str                         # DESCRIPTIVE | UNDERPOWERED
    n: int
    block: int
    breakeven: float
    breakeven_ci: tuple[float, float]
    actual: float
    actual_ci: tuple[float, float]
    margin_ci: tuple[float, float]      # interval for actual minus breakeven
    avg_win: float
    avg_loss: float
    without_best: dict = field(default_factory=dict)
    detail: str = ""


def _summary(net: np.ndarray, seed: int) -> dict:
    be, act, aw, al = _point(net)
    bb, ba = _block_boot(net, seed)
    return {"n": int(len(net)), "block": block_size(len(net)), "breakeven": be, "breakeven_ci": _ci(bb),
            "actual": act, "actual_ci": _ci(ba), "margin_ci": _ci(ba - bb), "avg_win": aw, "avg_loss": al}


def required_win_rate(trips: list[RoundTrip], seed: int = 0) -> WinRate:
    trips = sorted(trips, key=lambda t: t.t_close_ms)
    net = np.array([t.net_pnl for t in trips], dtype=float)
    nw, nl = int(np.sum(net > 0)), int(np.sum(net < 0))
    if len(net) < MIN_TRIPS or min(nw, nl) < MIN_EACH_SIDE:
        be, act, aw, al = _point(net) if len(net) else (float("nan"),) * 4
        nan2 = (float("nan"), float("nan"))
        return WinRate("UNDERPOWERED", len(net), block_size(len(net)), be, nan2, act, nan2, nan2, aw, al, {},
                       f"needs at least {MIN_TRIPS} trips with {MIN_EACH_SIDE} winners and {MIN_EACH_SIDE} losers "
                       f"(has {len(net)} trips, {nw} winners, {nl} losers); no interval reported")
    s = _summary(net, seed)
    best = int(np.argmax(net))
    wb = _summary(np.delete(net, best), seed)
    wb["removed_trade_pnl"] = float(net[best])
    return WinRate("DESCRIPTIVE", s["n"], s["block"], s["breakeven"], s["breakeven_ci"], s["actual"], s["actual_ci"],
                   s["margin_ci"], s["avg_win"], s["avg_loss"], wb,
                   f"required win rate = average loss / (average win + average loss) on net results; "
                   f"{int(CI_LEVEL * 100)}% block-bootstrap interval, block length ceil(sqrt(n)) = {s['block']} trips. "
                   f"An interval, not a probability.")
