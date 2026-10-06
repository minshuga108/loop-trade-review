"""Behaviour detectors on round trips. Every finding is tested within the trader.

A finding is only called FLAGGED when it clears an effect-size floor, a minimum
sample and a permutation p-value; otherwise it is NOT_FLAGGED or UNDERPOWERED.
Nothing here guesses intent or emotion.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .schema import RoundTrip
from .stats import bootstrap_ci, median_log_gap, perm_p_greater

MIN_PER_GROUP = 20


@dataclass
class Finding:
    detector: str
    status: str                      # FLAGGED | NOT_FLAGGED | UNDERPOWERED
    n_a: int
    n_b: int
    effect: float                    # ratio of group medians (a over b)
    ci: tuple[float, float]
    p: float
    detail: str = ""
    extra: dict = field(default_factory=dict)


def after_loss_labels(trips: list[RoundTrip]) -> np.ndarray:
    """True if the most recent trip that CLOSED before this one opened was a loss.

    Trips with no earlier closed trip get NaN-like False and are excluded by the caller.
    """
    order_close = sorted(range(len(trips)), key=lambda i: trips[i].t_close_ms)
    lab = np.zeros(len(trips), dtype=int) - 1   # -1 unknown, 0 win, 1 loss
    j = 0
    last = None
    close_sorted = [trips[i] for i in order_close]
    for i, t in sorted(enumerate(trips), key=lambda it: it[1].t_open_ms):
        while j < len(close_sorted) and close_sorted[j].t_close_ms < t.t_open_ms:
            last = close_sorted[j]
            j += 1
        if last is not None:
            lab[i] = 1 if last.net_pnl < 0 else 0
    return lab


def size_after_loss(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> Finding:
    lab = after_loss_labels(trips)
    keep = lab >= 0
    notional = np.array([t.first_order_notional for t in trips])[keep]
    after_loss = lab[keep] == 1
    ok = notional > 0
    notional, after_loss = notional[ok], after_loss[ok]
    n_a, n_b = int(after_loss.sum()), int((~after_loss).sum())
    if min(n_a, n_b) < MIN_PER_GROUP:
        return Finding("size_after_loss", "UNDERPOWERED", n_a, n_b, float("nan"), (float("nan"),) * 2, float("nan"),
                       f"needs at least {MIN_PER_GROUP} trades in each group (has {n_a} after a loss, {n_b} after a win)")
    obs, p = perm_p_greater(notional, after_loss, median_log_gap, n_perm, seed)
    ratio = float(np.exp(obs))
    # bootstrap interval on the ratio, resampling each group
    g = np.random.default_rng(seed)
    a, b = notional[after_loss], notional[~after_loss]
    boots = [float(np.exp(median_log_gap(a[g.integers(0, len(a), len(a))], b[g.integers(0, len(b), len(b))]))) for _ in range(1500)]
    ci = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
    flagged = p < 0.05 and ratio >= 1.25
    return Finding("size_after_loss", "FLAGGED" if flagged else "NOT_FLAGGED", n_a, n_b, ratio, ci, p,
                   "median opening size after a losing trip versus after a winning trip (within-trader permutation test)")


def hold_asymmetry(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> Finding:
    hold = np.array([max(t.hold_ms, 1) for t in trips], dtype=float)
    loser = np.array([t.net_pnl < 0 for t in trips])
    n_a, n_b = int(loser.sum()), int((~loser).sum())
    if min(n_a, n_b) < MIN_PER_GROUP:
        return Finding("hold_asymmetry", "UNDERPOWERED", n_a, n_b, float("nan"), (float("nan"),) * 2, float("nan"),
                       f"needs at least {MIN_PER_GROUP} winning and losing trips (has {n_b} winners, {n_a} losers)")
    obs, p = perm_p_greater(hold, loser, median_log_gap, n_perm, seed)
    ratio = float(np.exp(obs))
    g = np.random.default_rng(seed)
    a, b = hold[loser], hold[~loser]
    boots = [float(np.exp(median_log_gap(a[g.integers(0, len(a), len(a))], b[g.integers(0, len(b), len(b))]))) for _ in range(1500)]
    ci = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
    flagged = p < 0.05 and ratio >= 1.5
    return Finding("hold_asymmetry", "FLAGGED" if flagged else "NOT_FLAGGED", n_a, n_b, ratio, ci, p,
                   "median hold time of losing trips versus winning trips (within-trader permutation test)")


def run_all(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> list[Finding]:
    return [size_after_loss(trips, n_perm, seed), hold_asymmetry(trips, n_perm, seed)]
