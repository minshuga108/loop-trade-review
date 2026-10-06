"""Decay check for armed rules: is the rule still earning its keep on trades since it was armed?

Pre-registered (fixed before any suite run, same spirit as engine/checklist.py):
- Only trades AFTER the rule was armed are used (never the window that admitted it).
- The effect is the same counterfactual the court priced, with the cap baseline frozen
  at arming time; p is a one-sided permutation p (random rule-application sets of the
  same size), so it tests "still better than chance".
- UNDERPOWERED if the window is too small to say anything; the rule stays armed.
- RETIRE (propose retirement) if the effect is not positive or p > RETIRE_P.
- Otherwise KEEP.
Proposing is all it does: the owner confirms or declines in the rulebook.
"""
from __future__ import annotations

import numpy as np

from . import halt
from .court import Rule, _effect
from .detectors import after_loss_labels
from .rulebook import Rulebook
from .schema import RoundTrip

RETIRE_P = 0.3
MIN_TRIPS = 30
MIN_AFFECTED_CAP = 10
MIN_SKIPPED_HALT = 8


def cap_decay_check(trips_since: list[RoundTrip], rule: Rule, baseline: float, n_perm: int = 1000, seed: int = 0) -> dict:
    trips = sorted(trips_since, key=lambda t: t.t_open_ms)
    lab = after_loss_labels(trips)
    idx = np.where(lab >= 0)[0]
    notional = np.array([trips[i].first_order_notional for i in idx])
    pnl = np.array([trips[i].net_pnl for i in idx])
    after = lab[idx] == 1
    cap = rule.value * baseline
    n_aff = int(np.sum(after & (notional > cap)))
    if len(idx) < MIN_TRIPS or n_aff < MIN_AFFECTED_CAP:
        return {"status": "UNDERPOWERED", "n_trips": int(len(idx)), "n_affected": n_aff, "effect": float("nan"), "p": float("nan")}
    obs = _effect(notional, pnl, after, cap)
    g = np.random.default_rng(seed)
    sh, ge = after.copy(), 0
    for _ in range(n_perm):
        g.shuffle(sh)
        if _effect(notional, pnl, sh, cap) >= obs - 1e-9:
            ge += 1
    p = (ge + 1) / (n_perm + 1)
    status = "RETIRE" if (obs <= 0 or p > RETIRE_P) else "KEEP"
    return {"status": status, "n_trips": int(len(idx)), "n_affected": n_aff, "effect": obs, "p": p}


def halt_decay_check(trips_since: list[RoundTrip], n_losses: int = 2, n_perm: int = 1000, seed: int = 0) -> dict:
    trips = sorted(trips_since, key=lambda t: t.t_open_ms)
    e = halt.effect(trips, n_losses)
    if e["n_trips"] < MIN_TRIPS or e["n_skipped"] < MIN_SKIPPED_HALT:
        return {"status": "UNDERPOWERED", "n_trips": e["n_trips"], "n_affected": e["n_skipped"], "effect": float("nan"), "p": float("nan")}
    pnl = np.array([t.net_pnl for t in trips])
    k = e["n_skipped"]
    g = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        if -pnl[g.choice(len(pnl), size=k, replace=False)].sum() >= e["effect"] - 1e-9:
            ge += 1
    p = (ge + 1) / (n_perm + 1)
    status = "RETIRE" if (e["effect"] <= 0 or p > RETIRE_P) else "KEEP"
    return {"status": status, "n_trips": e["n_trips"], "n_affected": k, "effect": e["effect"], "p": p}


def apply_to_rulebook(rb: Rulebook, rule_id: str, check: dict) -> str:
    """Propose retirement in the rulebook when the check says RETIRE; the owner still decides."""
    if check["status"] == "RETIRE":
        rb.propose_retirement(rule_id, f"decay check on trades since arming: effect {check['effect']:.2f}, "
                                       f"p={check['p']:.3f} (retire if effect <= 0 or p > {RETIRE_P})")
    return rb.entries[rule_id].state
