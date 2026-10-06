"""Leak pricing and the rule court.

The LLM may only turn a sentence into a Rule (strict schema). Code decides.
Counterfactuals use only information available when the trip opened (the
outcome of the previously closed trip) and scale pnl linearly with size, which
is conservative for a cap: a smaller order cannot have worse impact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, ConfigDict

from .detectors import after_loss_labels
from .schema import RoundTrip


class Rule(BaseModel):
    """Strict schema: metric, operator, number, action. No free text."""
    model_config = ConfigDict(frozen=True)
    metric: str = "size_after_loss"
    operator: str = "cap_multiple_of_median"
    value: float
    action: str = "cap_size"


def _baseline(trips: list[RoundTrip]) -> float:
    """The trader's usual size: median opening size of trips that did NOT follow a loss.

    Using all trips would let a size-up habit inflate its own yardstick; at least 10 calm trips
    are needed, otherwise the overall median is used."""
    lab = after_loss_labels(trips)
    calm = [t.first_order_notional for t, l in zip(trips, lab) if l == 0]
    pool = calm if len(calm) >= 10 else [t.first_order_notional for t in trips]
    return float(np.median(pool))


def _effect(notional: np.ndarray, pnl: np.ndarray, applies: np.ndarray, cap: float) -> float:
    """Total pnl change if sizes of the trips where the rule applies were capped."""
    f = np.where(applies & (notional > cap), cap / np.maximum(notional, 1e-12), 1.0)
    return float(np.sum(pnl * (f - 1.0)))


def price_rule(trips: list[RoundTrip], rule: Rule, baseline: float | None = None, seed: int = 0, n_boot: int = 2000) -> dict:
    """Dollar effect of the rule on this set of trips, with a bootstrap interval."""
    lab = after_loss_labels(trips)
    keep = lab >= 0
    idx = np.where(keep)[0]
    notional = np.array([trips[i].first_order_notional for i in idx])
    pnl = np.array([trips[i].net_pnl for i in idx])
    after = lab[idx] == 1
    base = baseline if baseline is not None else _baseline(trips)
    cap = rule.value * base
    eff = _effect(notional, pnl, after, cap)
    g = np.random.default_rng(seed)
    n = len(idx)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        s = g.integers(0, n, n)
        boots[i] = _effect(notional[s], pnl[s], after[s], cap)
    return {
        "effect": eff,
        "ci": (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))),
        "n_trips": int(n),
        "n_affected": int(np.sum(after & (notional > cap))),
        "cap": cap,
    }


@dataclass
class Verdict:
    rule: Rule
    status: str                 # ACCEPTED | REJECTED | UNDERPOWERED
    reason: str
    train: dict
    test: dict
    p: float
    trials: int
    alpha_used: float
    notes: list[str] = field(default_factory=list)


class Court:
    """Walk-forward court with a trial-count ledger.

    Every proposed rule, accepted or not, increments the ledger and the
    multiple-testing penalty (Bonferroni over proposals) uses that count.
    """

    def __init__(self, train_frac: float = 0.6, min_test_trips: int = 30, min_affected: int = 10,
                 alpha: float = 0.05, n_perm: int = 4000, seed: int = 0):
        self.train_frac, self.min_test_trips, self.min_affected = train_frac, min_test_trips, min_affected
        self.alpha, self.n_perm, self.seed = alpha, n_perm, seed
        self.proposed: list[Rule] = []

    @property
    def trials(self) -> int:
        return len(self.proposed)

    def propose(self, rule: Rule) -> None:
        self.proposed.append(rule)

    def judge(self, trips: list[RoundTrip], rule: Rule) -> Verdict:
        if rule not in self.proposed:
            self.propose(rule)
        trips = sorted(trips, key=lambda t: t.t_open_ms)
        cut = int(len(trips) * self.train_frac)
        train, test = trips[:cut], trips[cut:]
        base = _baseline(train)                       # fixed from the TRAIN window only
        tr = price_rule(train, rule, base, self.seed)
        te = price_rule(test, rule, base, self.seed)
        alpha = self.alpha / max(self.trials, 1)
        if te["n_trips"] < self.min_test_trips or te["n_affected"] < self.min_affected:
            return Verdict(rule, "UNDERPOWERED",
                           f"held-out window has {te['n_trips']} trips and the rule touches {te['n_affected']}; "
                           f"needs {self.min_test_trips} and {self.min_affected}", tr, te, float("nan"), self.trials, alpha)
        # permutation null on the held-out window: apply the cap to a random set of the same size
        lab = after_loss_labels(test)
        idx = np.where(lab >= 0)[0]
        notional = np.array([test[i].first_order_notional for i in idx])
        pnl = np.array([test[i].net_pnl for i in idx])
        after = lab[idx] == 1
        cap = te["cap"]
        obs = _effect(notional, pnl, after, cap)
        g = np.random.default_rng(self.seed)
        sh = after.copy()
        ge = 0
        for _ in range(self.n_perm):
            g.shuffle(sh)
            if _effect(notional, pnl, sh, cap) >= obs - 1e-9:
                ge += 1
        p = (ge + 1) / (self.n_perm + 1)
        if obs > 0 and p < alpha:
            status, reason = "ACCEPTED", f"held-out effect is positive and p={p:.4f} is below the trial-adjusted threshold {alpha:.4f}"
        elif obs <= 0:
            status, reason = "REJECTED", "held-out effect is not positive"
        else:
            status, reason = "REJECTED", f"held-out effect is positive but p={p:.4f} does not clear the trial-adjusted threshold {alpha:.4f}"
        return Verdict(rule, status, reason, tr, te, p, self.trials, alpha)
