"""Counterfactual for the rule "halt for the rest of the day after N consecutive losing trips".

Parameter N is fixed in advance (never tuned on the history it is judged on).
A trip that would have opened after the halt is skipped; its pnl is removed.
This only uses information available when the trip opened (earlier closes).
Effect is positive when skipping those trips would have saved money.
"""
from __future__ import annotations

import numpy as np

from .schema import RoundTrip

DAY_MS = 86_400_000


def skip_mask(trips: list[RoundTrip], n_losses: int = 2) -> np.ndarray:
    """True for trips that the rule would have skipped (trips sorted by open time)."""
    order = sorted(range(len(trips)), key=lambda i: trips[i].t_open_ms)
    closed = sorted(range(len(trips)), key=lambda i: trips[i].t_close_ms)
    skip = np.zeros(len(trips), dtype=bool)
    j = 0
    streak, day, halted = 0, None, False
    for i in order:
        t = trips[i]
        d = t.t_open_ms // DAY_MS
        if d != day:
            day, streak, halted = d, 0, False
        # fold in every trip that had CLOSED before this one opened (and closed today)
        while j < len(closed) and trips[closed[j]].t_close_ms < t.t_open_ms:
            c = trips[closed[j]]
            if c.t_close_ms // DAY_MS == d:
                streak = streak + 1 if c.net_pnl < 0 else 0
                if streak >= n_losses:
                    halted = True
            j += 1
        if halted:
            skip[i] = True
    return skip


def effect(trips: list[RoundTrip], n_losses: int = 2) -> dict:
    m = skip_mask(trips, n_losses)
    pnl = np.array([t.net_pnl for t in trips])
    return {"effect": float(-pnl[m].sum()), "n_skipped": int(m.sum()), "n_trips": len(trips)}


def judge(trips: list[RoundTrip], n_losses: int = 2, train_frac: float = 0.6, n_perm: int = 3000, seed: int = 0,
          min_test_trips: int = 30, min_skipped: int = 8, alpha: float = 0.01) -> dict:
    """In-sample and held-out effect side by side, with a permutation p on the held-out part.

    alpha defaults to 0.05 / 5: the trial ledger holds five pre-declared rules (four caps and this halt rule)."""
    trips = sorted(trips, key=lambda t: t.t_open_ms)
    cut = int(len(trips) * train_frac)
    train, test = trips[:cut], trips[cut:]
    e_in, e_out = effect(train, n_losses), effect(test, n_losses)
    out = {"rule": f"halt for the day after {n_losses} consecutive losing trips", "in_sample": e_in, "held_out": e_out}
    if e_out["n_trips"] < min_test_trips or e_out["n_skipped"] < min_skipped:
        out.update(status="UNDERPOWERED", p=None,
                   reason=f"held-out window has {e_out['n_trips']} trips and the rule would skip {e_out['n_skipped']}; "
                          f"needs {min_test_trips} and {min_skipped}")
        return out
    pnl = np.array([t.net_pnl for t in test])
    k = e_out["n_skipped"]
    g = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        pick = g.choice(len(pnl), size=k, replace=False)
        if -pnl[pick].sum() >= e_out["effect"] - 1e-9:
            ge += 1
    p = (ge + 1) / (n_perm + 1)
    if e_out["effect"] > 0 and p < alpha:
        status, reason = "ACCEPTED", f"held-out effect is positive and p={p:.3f} is below the trial-adjusted threshold {alpha:.3f}"
    elif e_out["effect"] <= 0:
        status, reason = "REJECTED", "held-out effect is not positive"
    else:
        status, reason = "REJECTED", f"held-out effect is positive but p={p:.3f} does not clear the trial-adjusted threshold {alpha:.3f}"
    out.update(status=status, p=p, reason=reason)
    return out
