"""Tests written for the mutants that survived scripts/mutate.py (docs/stress/mutation_results.json).
Each one pins an invariant the existing suite did not check."""
from __future__ import annotations

import numpy as np
import pytest

from engine import numberlock
from engine.court import Court, Rule, Verdict, _baseline
from engine.detectors import after_loss_labels
from engine.planted import planted_trader
from engine.rulebook import Rulebook, RulebookError
from engine.walkforward import judge_wf

LEAK = planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=2)


# M04 / M12: an underpowered guard must trip on EITHER shortfall
def test_split_court_underpowered_when_too_few_affected_even_with_enough_trips():
    v = Court(n_perm=50, min_affected=10**6).judge(LEAK, Rule(value=1.5))
    assert v.test["n_trips"] >= 30 and v.status == "UNDERPOWERED"


def test_split_court_underpowered_when_too_few_trips_even_with_enough_affected():
    v = Court(n_perm=50, min_test_trips=10**6, min_affected=0).judge(LEAK, Rule(value=1.5))
    assert v.status == "UNDERPOWERED"


def test_walk_forward_underpowered_on_either_shortfall():
    assert judge_wf(Court(n_perm=50, min_affected=10**6), LEAK, Rule(value=1.5)).status == "UNDERPOWERED"
    assert judge_wf(Court(n_perm=50, min_test_trips=10**6, min_affected=0), LEAK, Rule(value=1.5)).status == "UNDERPOWERED"


# M06: train and test are disjoint and cover the history
def test_split_court_train_and_test_do_not_overlap():
    trips = sorted(LEAK, key=lambda t: t.t_open_ms)
    cut = int(len(trips) * 0.6)
    v = Court(n_perm=20).judge(trips, Rule(value=1.5))
    expect_test = int(np.sum(after_loss_labels(trips[cut:]) >= 0))
    expect_train = int(np.sum(after_loss_labels(trips[:cut]) >= 0))
    assert (v.train["n_trips"], v.test["n_trips"]) == (expect_train, expect_test)


# M07 / M09: no look-ahead. Changing the judged (future) trips must not move the cap they are judged with.
def _inflate(trips, start):
    return [t.model_copy(update={"first_order_notional": t.first_order_notional * 100}) if i >= start else t
            for i, t in enumerate(trips)]


def test_split_court_cap_uses_the_train_window_only():
    trips = sorted(LEAK, key=lambda t: t.t_open_ms)
    cut = int(len(trips) * 0.6)
    v = Court(n_perm=20).judge(trips, Rule(value=1.5))
    assert v.test["cap"] == pytest.approx(1.5 * _baseline(trips[:cut]))
    v2 = Court(n_perm=20).judge(_inflate(trips, cut), Rule(value=1.5))
    assert v2.test["cap"] == pytest.approx(v.test["cap"])


def test_walk_forward_cap_never_sees_the_chunk_it_judges():
    trips = sorted(LEAK, key=lambda t: t.t_open_ms)
    edges = np.linspace(0, len(trips), 7).astype(int)          # folds=5 -> 7 edges
    v = judge_wf(Court(n_perm=20), trips, Rule(value=1.5))
    assert v.test["cap"] == pytest.approx(1.5 * _baseline(trips[:edges[5]]))
    v2 = judge_wf(Court(n_perm=20), _inflate(trips, edges[5]), Rule(value=1.5))
    assert v2.test["cap"] == pytest.approx(v.test["cap"])


# M11: with no planted effect the permutation p must look like a p-value, not collapse to 1/(n+1)
def test_walk_forward_p_is_not_tiny_without_a_real_effect():
    ps = []
    for seed in range(6):
        trips = planted_trader(n=600, size_mult=1.0, tilt=0.0, seed=100 + seed)
        v = judge_wf(Court(n_perm=300), trips, Rule(value=1.0))
        if v.status != "UNDERPOWERED":
            ps.append(v.p)
    assert len(ps) >= 4 and float(np.median(ps)) > 0.1 and min(ps) > 1 / 301


# M15: a REJECTED verdict is quarantined and can never be armed
def test_rejected_verdict_is_quarantined_and_cannot_be_armed():
    rb = Rulebook()
    v = Verdict(Rule(value=1.5), "REJECTED", "held-out effect is not positive", {}, {}, 0.5, 1, 0.05)
    e = rb.record_verdict(v)
    assert e.state == "QUARANTINED"
    with pytest.raises(RulebookError):
        rb.arm(e.rule_id, "owner")
    assert rb.active_rules() == []


# M23: the number-lock tolerance is half a unit of the last shown digit, no more
@pytest.mark.parametrize("text,fact", [("effect 1235", 1234.0), ("p=0.03", 0.024), ("12.6 trades", 12.0), ("$1,236", 1234.4)])
def test_numberlock_refuses_a_near_miss(text, fact):
    with pytest.raises(numberlock.NumberLockError):
        numberlock.verify(text, [fact])


@pytest.mark.parametrize("text,fact", [("effect 1,234", 1234.4), ("p=0.024", 0.0244), ("12.5", 12.46)])
def test_numberlock_accepts_rounding_within_half_a_digit(text, fact):
    numberlock.verify(text, [fact])
