"""Serial-dependence handling: autocorrelation tools, block permutation, and the court's minimum-evidence guard."""
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from engine import dependence as D
from engine.court import Court, Rule
from engine.planted import planted_trader
from engine.stats import perm_p_greater
from engine.walkforward import judge_wf


def ar1(n, rho, seed):
    g = np.random.default_rng(seed)
    e = g.normal(size=n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return x


def test_acf_ljungbox_match_statsmodels():
    sm = pytest.importorskip("statsmodels.tsa.stattools")
    x = ar1(300, 0.5, 1)
    assert np.allclose(D.acf(x, 5), sm.acf(x, nlags=5, fft=False))
    q, p = D.ljung_box(x, 5)
    r = sm.q_stat(sm.acf(x, nlags=5, fft=False)[1:], len(x))
    assert q == pytest.approx(r[0][-1], rel=1e-9) and p == pytest.approx(r[1][-1], rel=1e-6)


def test_block_length_matches_arch_and_grows_with_rho():
    arch = pytest.importorskip("arch.bootstrap")
    for rho in (0.3, 0.6):
        x = ar1(400, rho, 2)
        ours = D.optimal_block_length(x)
        theirs = float(arch.optimal_block_length(x).iloc[0, 0])
        assert ours == pytest.approx(theirs, rel=0.6)
    assert D.optimal_block_length(ar1(400, 0.7, 3)) > D.optimal_block_length(ar1(400, 0.0, 3))


def test_assess_detects_ar_and_not_iid_and_ess_shrinks():
    dep = D.assess(ar1(300, 0.6, 4))
    assert dep.detected and dep.block > 1 and dep.ess < 150
    hits = sum(D.assess(np.random.default_rng(s).normal(size=300)).detected for s in range(200))
    assert hits <= 8                                         # about the 1% Ljung-Box level, never routinely
    assert D.assess(np.ones(100)).detected is False and D.assess(np.arange(5.0)).block == 1


@given(st.integers(2, 60), st.integers(1, 12), st.integers(0, 10_000))
@settings(max_examples=40, deadline=None)
def test_block_permute_is_a_permutation(n, block, seed):
    lab = np.random.default_rng(seed).random(n) < 0.4
    out = D.block_permute(lab, block, np.random.default_rng(seed))
    assert len(out) == n and out.sum() == lab.sum()


def test_block_permutation_fixes_size_of_test_on_dependent_outcomes():
    """Clustered labels (runs, like heavy days) independent of an AR(1) outcome: plain permutation rejects far above 5%, block version near it."""
    stat = lambda a, b: float(np.mean(a) - np.mean(b))      # noqa: E731
    plain = blocky = 0
    sims = 150
    for s in range(sims):
        x = ar1(200, 0.7, s)
        lab = np.repeat(np.random.default_rng(10_000 + s).random(20) < 0.3, 10)
        blk = D.assess(x).block
        plain += perm_p_greater(x, lab, stat, 199, s)[1] < 0.05
        blocky += perm_p_greater(x, lab, stat, 199, s, block=blk)[1] < 0.05
    assert plain / sims > 0.15 and blocky / sims < plain / sims * 0.6


def hostile(n, seed, rho=0.6):
    """No size habit; AR(1) returns, so a cap after a loss genuinely helps out of sample."""
    base = planted_trader(n=n, seed=seed)
    g = np.random.default_rng(seed + 1)
    prev, out = 0.0, []
    for t in base:
        r = 0.0005 + rho * prev + np.sqrt(1 - rho ** 2) * g.normal(0, 0.02)
        prev = r - 0.0005
        out.append(t.model_copy(update={"net_pnl": t.first_order_notional * r - t.first_order_notional * 0.001}))
    return out


def test_court_refuses_dependence_only_gain_and_says_so():
    acc, reasons = 0, []
    for s in range(12):
        c = Court(n_perm=200, seed=s)
        for m in (1.0, 1.5, 2.0, 3.0):
            c.propose(Rule(value=m))
        v = judge_wf(c, hostile(450, 50 + s), Rule(value=1.5))
        acc += v.status == "ACCEPTED"
        reasons.append(v.reason)
        assert v.status == "UNDERPOWERED" or (v.notes and "serial dependence" in v.notes[0])
    assert acc <= 1
    assert any("serial dependence" in r and "size" in r for r in reasons)


def test_court_still_accepts_a_real_habit_under_dependence_or_not():
    ok = 0
    for s in range(6):
        trips = planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=700 + s)
        c = Court(n_perm=300, seed=s)
        for m in (1.0, 1.5, 2.0, 3.0):
            c.propose(Rule(value=m))
        ok += judge_wf(c, trips, Rule(value=1.5)).status == "ACCEPTED"
    assert ok >= 4


def test_independent_clean_data_is_unchanged_by_the_guard():
    c = Court(n_perm=200, seed=1)
    v = judge_wf(c, planted_trader(n=300, seed=3), Rule(value=1.5))
    assert v.notes == [] and "serial dependence" not in v.reason


def test_size_after_loss_ignores_size_drift_but_finds_a_habit():
    from engine import detectors
    drift = [t.model_copy(update={"first_order_notional": t.first_order_notional * float(np.exp(1.5 * i / 300))}) for i, t in enumerate(planted_trader(n=300, seed=5))]
    hits = sum(detectors.size_after_loss([t.model_copy(update={"first_order_notional": t.first_order_notional * float(np.exp(1.5 * i / 300))})
                                           for i, t in enumerate(planted_trader(n=300, seed=s))], n_perm=200, seed=s).status == "FLAGGED" for s in range(20))
    assert hits <= 2 and drift
    f = detectors.size_after_loss(planted_trader(n=300, size_mult=3.0, seed=6), n_perm=300, seed=1)
    assert f.status == "FLAGGED" and f.effect > 2


def test_averaging_down_test_is_on_pre_fee_pnl():
    from engine import detectors3 as d3, planted3 as p3
    tr, fills = p3.planted_avgdown_trader(n=250, tilt=0.0, seed=11)
    f = d3.averaging_down(tr, fills, n_perm=200, seed=1)
    assert "fee_gap_per_trip" in f.extra and f.extra["fee_gap_per_trip"] > 0        # adds pay more fee; reported, not tested
