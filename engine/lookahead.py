"""Structural no-look-ahead guard for counterfactuals.

A statistical penalty does not catch a leaky rule: arXiv 2608.27734 shows a
deliberately leaky strategy (Sharpe 35) passing Deflated Sharpe and PBO. So the
guard here is structural, not statistical:

1. Every feature a counterfactual rule may use lives in a FeatureRegistry. A
   feature computes, for every trip, its value AND the timestamp at which that
   value became known (e.g. the close time of the trip whose outcome it reads).
2. The evaluator refuses a rule if any feature value it uses was known AFTER
   the order's open (known_at_ms > t_open_ms). Known exactly at the open is fine.
3. Tags can lie, so the evaluator also audits a sample of trips: it recomputes
   each feature on an as-of copy of the history (trips not yet opened removed,
   trips not yet closed have their outcome and close time blanked) and refuses
   the rule if any value changes. A mis-tagged leaky feature is caught here.
4. Every result carries the registry hash (feature names, tags and source), so a
   finding can be tied to the exact feature definitions that produced it.

Nothing here decides whether a rule is good; it decides whether the rule is
even allowed to be judged.
"""
from __future__ import annotations

import hashlib
import inspect
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .schema import RoundTrip

DAY_MS = 86_400_000
FAR_FUTURE = 2 ** 62           # close time given to trips that are still open as of the audit time
FeatureFn = Callable[[list[RoundTrip]], tuple[np.ndarray, np.ndarray]]


class LookAheadError(ValueError):
    pass


def sort_trips(trips: list[RoundTrip]) -> list[RoundTrip]:
    return sorted(trips, key=lambda t: (t.t_open_ms, t.symbol, t.first_order_id))


@dataclass(frozen=True)
class Feature:
    name: str
    known_at: str                 # human description of when the value becomes known
    fn: FeatureFn                 # trips sorted by open -> (values, known_at_ms), one per trip


class FeatureRegistry:
    def __init__(self) -> None:
        self.features: dict[str, Feature] = {}

    def register(self, name: str, known_at: str, fn: FeatureFn) -> None:
        if name in self.features:
            raise ValueError(f"feature {name} already registered")
        self.features[name] = Feature(name, known_at, fn)

    def hash(self) -> str:
        body = []
        for n in sorted(self.features):
            f = self.features[n]
            try:
                src = inspect.getsource(f.fn)
            except (OSError, TypeError):
                src = getattr(f.fn, "__qualname__", repr(f.fn))
            body.append(f"{n}|{f.known_at}|{src}")
        return hashlib.sha256("\n".join(body).encode()).hexdigest()[:16]

    def compute(self, trips: list[RoundTrip], names: tuple[str, ...]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        out = {}
        for n in names:
            if n not in self.features:
                raise LookAheadError(f"feature {n} is not in the registry; unregistered features are refused")
            v, k = self.features[n].fn(trips)
            out[n] = (np.asarray(v, dtype=float), np.asarray(k, dtype=np.int64))
        return out


# -- honest features ------------------------------------------------------------------

def _close_order(trips: list[RoundTrip]) -> list[int]:
    return sorted(range(len(trips)), key=lambda i: (trips[i].t_close_ms, i))


def f_open_notional(trips):
    """Opening order size: known at the open."""
    return (np.array([t.first_order_notional for t in trips], dtype=float),
            np.array([t.t_open_ms for t in trips], dtype=np.int64))


def f_prev_closed_loss(trips):
    """1 if the most recent trip that CLOSED before this one opened lost, 0 if it won, -1 if none.
    Known at that earlier trip's close (or at the open when there is none)."""
    order = _close_order(trips)
    closes = [trips[i].t_close_ms for i in order]
    vals = np.full(len(trips), -1.0)
    known = np.array([t.t_open_ms for t in trips], dtype=np.int64)
    import bisect
    for i, t in enumerate(trips):
        j = bisect.bisect_left(closes, t.t_open_ms) - 1          # strictly before the open
        if j >= 0:
            c = trips[order[j]]
            vals[i] = 1.0 if c.net_pnl < 0 else 0.0
            known[i] = c.t_close_ms
    return vals, known


def f_day_max_loss_run(trips):
    """Longest run of consecutive losing closes today (UTC) among trips closed before this open.
    Matches the state machine in engine/halt.py. Known at the latest of those closes."""
    order = _close_order(trips)
    vals = np.zeros(len(trips))
    known = np.array([t.t_open_ms for t in trips], dtype=np.int64)
    import bisect
    closes = [trips[i].t_close_ms for i in order]
    for i, t in enumerate(trips):
        d = t.t_open_ms // DAY_MS
        j = bisect.bisect_left(closes, t.t_open_ms)
        j0 = bisect.bisect_left(closes, d * DAY_MS)              # first close on this UTC day
        run = best = 0
        last = None
        for k in range(j0, j):
            c = trips[order[k]]
            if c.t_close_ms // DAY_MS != d:
                continue
            run = run + 1 if c.net_pnl < 0 else 0
            best = max(best, run)
            last = c.t_close_ms
        vals[i] = best
        if last is not None:
            known[i] = last
    return vals, known


# -- leaky features (registered only by the self-test, to prove the guard rejects them) ---

def f_own_outcome_loss(trips):
    """LEAKY: whether the trade being opened will lose. Known only at its own close."""
    return (np.array([1.0 if t.net_pnl < 0 else 0.0 if t.net_pnl == t.net_pnl else math.nan for t in trips]),
            np.array([t.t_close_ms for t in trips], dtype=np.int64))


def f_following_trade_loss(trips):
    """LEAKY: whether the trade after this one will lose. Known only at that trade's close."""
    n = len(trips)
    v = np.full(n, -1.0)
    k = np.array([t.t_open_ms for t in trips], dtype=np.int64)
    for i in range(n - 1):
        nx = trips[i + 1]
        v[i] = 1.0 if nx.net_pnl < 0 else 0.0 if nx.net_pnl == nx.net_pnl else math.nan
        k[i] = nx.t_close_ms
    return v, k


def f_own_outcome_mistagged(trips):
    """LEAKY and LYING: reads the trade's own outcome but tags it as known at the open.
    The tag check passes; the as-of audit must catch it."""
    v, _ = f_own_outcome_loss(trips)
    return v, np.array([t.t_open_ms for t in trips], dtype=np.int64)


def default_registry() -> FeatureRegistry:
    r = FeatureRegistry()
    r.register("open_notional", "at the order's open", f_open_notional)
    r.register("prev_closed_loss", "at the close of the last trip closed before the open", f_prev_closed_loss)
    r.register("day_max_loss_run", "at the latest same-day close before the open", f_day_max_loss_run)
    return r


def selftest_registry() -> FeatureRegistry:
    """Honest features plus three deliberately leaky ones (for the planted look-ahead test only)."""
    r = default_registry()
    r.register("own_outcome_loss", "at the trade's own close (LEAKY)", f_own_outcome_loss)
    r.register("following_trade_loss", "at the next trade's close (LEAKY)", f_following_trade_loss)
    r.register("own_outcome_mistagged", "claims: at the open (LIE; reads the trade's own close)", f_own_outcome_mistagged)
    return r


# -- counterfactual rules and the guarded evaluator ----------------------------------------

@dataclass(frozen=True)
class CounterfactualRule:
    name: str
    features: tuple[str, ...]
    action: str                                   # "skip" or "cap"
    predicate: Callable[[dict], bool]             # feature values for one trip -> rule applies
    cap_multiple: float = 1.5


def _as_of(trips: list[RoundTrip], i: int) -> tuple[list[RoundTrip], int]:
    """History as it looked at trips[i]'s open; returns the copy and trip i's index in it."""
    T = trips[i].t_open_ms
    out, pos = [], -1
    for j, t in enumerate(trips):
        if t.t_open_ms > T:
            continue
        if t.t_close_ms >= T:
            t = t.model_copy(update={"net_pnl": math.nan, "t_close_ms": FAR_FUTURE})
        if j == i:
            pos = len(out)
        out.append(t)
    return out, pos


def _same(a: float, b: float) -> bool:
    return (a != a and b != b) or a == b


@dataclass
class GuardResult:
    status: str                       # OK | REFUSED_LOOKAHEAD
    rule: str
    registry_hash: str
    reason: str = ""
    n_tag_violations: int = 0
    n_audit_mismatches: int = 0
    applies: np.ndarray | None = None
    values: dict = field(default_factory=dict)


def guard(trips: list[RoundTrip], rule: CounterfactualRule, registry: FeatureRegistry,
          audit_k: int = 12, seed: int = 0) -> GuardResult:
    """Refuse the rule if any feature it uses is known after the order's open (tag check),
    or changes when recomputed on the as-of history (audit). Otherwise return where it applies."""
    trips = sort_trips(trips)
    h = registry.hash()
    feats = registry.compute(trips, rule.features)
    opens = np.array([t.t_open_ms for t in trips], dtype=np.int64)
    bad_tags = {n: int(np.sum(k > opens)) for n, (_, k) in feats.items()}
    n_bad = sum(bad_tags.values())
    if n_bad:
        worst = max(bad_tags, key=bad_tags.get)
        return GuardResult("REFUSED_LOOKAHEAD", rule.name, h,
                           f"feature '{worst}' is known after the order's open on {bad_tags[worst]} of {len(trips)} trips",
                           n_tag_violations=n_bad)
    g = np.random.default_rng(seed)
    sample = g.choice(len(trips), size=min(audit_k, len(trips)), replace=False) if trips else []
    mism = 0
    culprit = ""
    for i in sample:
        past, pos = _as_of(trips, int(i))
        pf = registry.compute(past, rule.features)
        for n in rule.features:
            if not _same(float(feats[n][0][i]), float(pf[n][0][pos])):
                mism += 1
                culprit = n
    if mism:
        return GuardResult("REFUSED_LOOKAHEAD", rule.name, h,
                           f"feature '{culprit}' changes when recomputed on the history as of the open "
                           f"({mism} mismatches in {len(sample)} audited trips): its tag is wrong",
                           n_audit_mismatches=mism)
    applies = np.array([bool(rule.predicate({n: feats[n][0][i] for n in rule.features})) for i in range(len(trips))])
    return GuardResult("OK", rule.name, h, "every feature is known at or before the open", applies=applies,
                       values={n: feats[n][0] for n in rule.features})


def counterfactual_effect(trips: list[RoundTrip], applies: np.ndarray, action: str, cap: float | None = None) -> float:
    pnl = np.array([t.net_pnl for t in trips])
    if action == "skip":
        return float(-pnl[applies].sum())
    notional = np.array([t.first_order_notional for t in trips])
    f = np.where(applies & (notional > cap), cap / np.maximum(notional, 1e-12), 1.0)
    return float(np.sum(pnl * (f - 1.0)))


def judge_guarded(trips: list[RoundTrip], rule: CounterfactualRule, registry: FeatureRegistry, trials: int = 4,
                  train_frac: float = 0.6, n_perm: int = 1000, alpha: float = 0.05, min_affected: int = 8,
                  seed: int = 0) -> dict:
    """Guard first; then a held-out permutation test like the court's (random rule-application
    sets of the same size), with the threshold deflated by the trial count.

    `stats_only` is the verdict the permutation test alone would have given, guard ignored.
    It is reported so the self-test can show that statistics alone admit a leaky rule."""
    trips = sort_trips(trips)
    gr = guard(trips, rule, registry, seed=seed)
    # statistics-only path: compute the mask from raw feature values, ignoring the guard
    feats = registry.compute(trips, rule.features)
    raw = np.array([bool(rule.predicate({n: feats[n][0][i] for n in rule.features})) for i in range(len(trips))])
    cut = int(len(trips) * train_frac)
    test = trips[cut:]
    m = raw[cut:]
    cap = rule.cap_multiple * float(np.median([t.first_order_notional for t in trips[:cut]])) if rule.action == "cap" else None
    obs = counterfactual_effect(test, m, rule.action, cap)
    thr = alpha / max(trials, 1)
    if int(m.sum()) < min_affected:
        stats_only, p = "UNDERPOWERED", float("nan")
    else:
        g = np.random.default_rng(seed)
        sh, ge = m.copy(), 0
        for _ in range(n_perm):
            g.shuffle(sh)
            if counterfactual_effect(test, sh, rule.action, cap) >= obs - 1e-9:
                ge += 1
        p = (ge + 1) / (n_perm + 1)
        stats_only = "ACCEPTED" if (obs > 0 and p < thr) else "REJECTED"
    status = "REFUSED_LOOKAHEAD" if gr.status != "OK" else stats_only
    return {"rule": rule.name, "status": status, "stats_only": stats_only, "p": p, "held_out_effect": obs,
            "threshold": thr, "guard": gr.status, "guard_reason": gr.reason, "registry_hash": gr.registry_hash}


# -- the rules the court judges, written against the registry -------------------------------

CAP_AFTER_LOSS = CounterfactualRule("cap size after a loss", ("prev_closed_loss", "open_notional"), "cap",
                                    lambda v: v["prev_closed_loss"] == 1.0)


def halt_after_losses(n: int = 2) -> CounterfactualRule:
    return CounterfactualRule(f"halt for the day after {n} losses", ("day_max_loss_run",), "skip",
                              lambda v, n=n: v["day_max_loss_run"] >= n)


LEAKY_PEEK = CounterfactualRule("skip the trade if it is going to lose (peeks at the next trade's outcome)",
                                ("own_outcome_loss",), "skip", lambda v: v["own_outcome_loss"] == 1.0)
LEAKY_FOLLOWING = CounterfactualRule("skip if the following trade loses", ("following_trade_loss",), "skip",
                                     lambda v: v["following_trade_loss"] == 1.0)
LEAKY_MISTAGGED = CounterfactualRule("skip if it is going to lose (feature mis-tagged as known at open)",
                                     ("own_outcome_mistagged",), "skip", lambda v: v["own_outcome_mistagged"] == 1.0)
