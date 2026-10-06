"""Walk-forward court: every trade after the first chunk is judged out of sample.

The history is cut into folds+1 chunks in time order. For chunk j (j >= 1) the rule
is applied with a baseline taken ONLY from chunks before j (expanding window, no
look-ahead) and judged on chunk j. The pooled out-of-sample effect is compared with
a permutation null that shuffles the "after a loss" labels within each chunk. The
rule parameter is fixed before looking at any of this; nothing is tuned.

Compared with a single 60/40 split this uses about folds/(folds+1) of the history as
held-out data, which is where the extra power comes from. The multiple-testing bar
still comes from the trial-count ledger (Bonferroni over every proposal).
"""
from __future__ import annotations

import numpy as np

from .court import Court, Rule, Verdict, _baseline, _effect, price_rule
from .detectors import after_loss_labels
from .schema import RoundTrip


def judge_wf(court: Court, trips: list[RoundTrip], rule: Rule, folds: int = 5) -> Verdict:
    if rule not in court.proposed:
        court.propose(rule)
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    n = len(ts)
    edges = np.linspace(0, n, folds + 2).astype(int)
    alpha = court.alpha / max(court.trials, 1)
    lab_all = after_loss_labels(ts)
    chunks = []
    for j in range(1, folds + 1):
        lo, hi = edges[j], edges[j + 1]
        base = _baseline(ts[:lo])
        idx = [i for i in range(lo, hi) if lab_all[i] >= 0]
        if not idx:
            continue
        chunks.append((np.array([ts[i].first_order_notional for i in idx]), np.array([ts[i].net_pnl for i in idx]),
                       lab_all[idx] == 1, rule.value * base))
    train = price_rule(ts[:edges[1]], rule, _baseline(ts[:edges[1]]), court.seed) if edges[1] > 5 else {"effect": 0.0, "n_trips": int(edges[1]), "n_affected": 0, "cap": float("nan"), "ci": (0.0, 0.0)}
    n_test = sum(len(c[0]) for c in chunks)
    obs = sum(_effect(nt, pn, af, cap) for nt, pn, af, cap in chunks)
    n_aff = int(sum(np.sum(af & (nt > cap)) for nt, pn, af, cap in chunks))
    test = {"effect": float(obs), "n_trips": n_test, "n_affected": n_aff, "cap": chunks[-1][3] if chunks else float("nan"), "ci": (0.0, 0.0)}
    if n_test < court.min_test_trips or n_aff < court.min_affected:
        return Verdict(rule, "UNDERPOWERED", f"out-of-sample part has {n_test} trips and the rule touches {n_aff}; needs {court.min_test_trips} and {court.min_affected}",
                       train, test, float("nan"), court.trials, alpha)
    g = np.random.default_rng(court.seed)
    ge = 0
    sh = [c[2].copy() for c in chunks]
    for _ in range(court.n_perm):
        tot = 0.0
        for k, (nt, pn, af, cap) in enumerate(chunks):
            g.shuffle(sh[k])
            tot += _effect(nt, pn, sh[k], cap)
        if tot >= obs - 1e-9:
            ge += 1
    p = (ge + 1) / (court.n_perm + 1)
    if obs > 0 and p < alpha:
        status, reason = "ACCEPTED", f"out-of-sample effect is positive and p={p:.4f} is below the trial-adjusted threshold {alpha:.4f}"
    elif obs <= 0:
        status, reason = "REJECTED", "out-of-sample effect is not positive"
    else:
        status, reason = "REJECTED", f"out-of-sample effect is positive but p={p:.4f} does not clear the trial-adjusted threshold {alpha:.4f}"
    return Verdict(rule, status, reason, train, test, p, court.trials, alpha)
