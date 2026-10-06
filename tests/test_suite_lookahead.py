import numpy as np

from engine import halt, lookahead, register
from engine.court import Court, Rule
from engine.decay import apply_to_rulebook, cap_decay_check
from engine.detectors import after_loss_labels
from engine.planted import planted_trader
from engine.rulebook import Rulebook
from engine.schema import Provenance, RoundTrip
from engine.suite import suite_trader, wilson

MIN = 60_000


def test_guard_refuses_leaky_rules_in_100_of_100_runs():
    reg = lookahead.selftest_registry()
    refused = {"peek": 0, "following": 0, "mistagged": 0}
    for s in range(100):
        trips = suite_trader(200, 0.25, size_mult=3.0, k=0.5, seed=7000 + s)
        for key, rule in (("peek", lookahead.LEAKY_PEEK), ("following", lookahead.LEAKY_FOLLOWING),
                          ("mistagged", lookahead.LEAKY_MISTAGGED)):
            refused[key] += lookahead.guard(trips, rule, reg, seed=s).status == "REFUSED_LOOKAHEAD"
    assert refused == {"peek": 100, "following": 100, "mistagged": 100}


def test_statistics_alone_would_admit_the_peek_rule_but_the_guard_refuses_it():
    trips = suite_trader(500, 0.25, size_mult=3.0, k=0.5, seed=11)
    r = lookahead.judge_guarded(trips, lookahead.LEAKY_PEEK, lookahead.selftest_registry(), n_perm=300)
    assert r["stats_only"] == "ACCEPTED" and r["status"] == "REFUSED_LOOKAHEAD" and len(r["registry_hash"]) == 16


def test_mistagged_feature_is_caught_by_the_audit_not_the_tag_check():
    trips = suite_trader(150, 0.25, seed=3)
    g = lookahead.guard(trips, lookahead.LEAKY_MISTAGGED, lookahead.selftest_registry())
    assert g.status == "REFUSED_LOOKAHEAD" and g.n_tag_violations == 0 and g.n_audit_mismatches > 0


def test_honest_rules_pass_and_match_the_court_and_halt_masks():
    reg = lookahead.default_registry()
    for s in range(5):
        trips = lookahead.sort_trips(suite_trader(300, 0.6, size_mult=3.0, seed=s))
        gc = lookahead.guard(trips, lookahead.CAP_AFTER_LOSS, reg, seed=s)
        gh = lookahead.guard(trips, lookahead.halt_after_losses(2), reg, seed=s)
        assert gc.status == "OK" and gh.status == "OK"
        assert np.array_equal(gc.applies, after_loss_labels(trips) == 1)
        assert np.array_equal(gh.applies, halt.skip_mask(trips, 2))


def test_unregistered_feature_is_refused_and_hash_tracks_the_registry():
    reg = lookahead.default_registry()
    bad = lookahead.CounterfactualRule("x", ("not_there",), "skip", lambda v: True)
    try:
        lookahead.guard(suite_trader(50, 0.25), bad, reg)
        raise AssertionError("should refuse")
    except lookahead.LookAheadError:
        pass
    assert reg.hash() != lookahead.selftest_registry().hash()
    assert reg.hash() == lookahead.default_registry().hash()


def test_generator_loss_rate_is_the_nominal_base_rate():
    for b in (0.05, 0.25, 0.60, 0.75):
        r = np.mean([np.mean([t.net_pnl < 0 for t in suite_trader(500, b, size_mult=3.0, k=0.5, seed=s)]) for s in range(40)])
        assert abs(r - b) < 0.01


def test_wilson_interval():
    lo, hi = wilson(0, 100)
    assert lo == 0.0 and abs(hi - 0.037) < 0.001
    lo, hi = wilson(50, 100)
    assert abs(lo - 0.404) < 0.002 and abs(hi - 0.596) < 0.002


def test_decay_check_proposes_retirement_through_the_rulebook():
    c = Court(n_perm=800)
    c.propose(Rule(value=1.5))
    v = c.judge(planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=2), Rule(value=1.5))
    assert v.status == "ACCEPTED"
    rb = Rulebook("t")
    e = rb.record_verdict(v)
    rb.arm(e.rule_id, "owner")
    # after arming, after-loss trades do BETTER (k < 0): the cap now costs money -> retirement proposed
    later = suite_trader(400, 0.4, size_mult=3.0, k=-0.9, seed=5)
    chk = cap_decay_check(later, Rule(value=1.5), baseline=5000.0, n_perm=300)
    assert chk["status"] == "RETIRE"
    assert apply_to_rulebook(rb, e.rule_id, chk) == "PENDING_RETIREMENT"
    assert rb.active_rules()                     # still guarding until the owner confirms
    strong = suite_trader(1000, 0.4, size_mult=3.0, k=0.9, seed=6)
    assert cap_decay_check(strong, Rule(value=1.5), baseline=5000.0, n_perm=300)["status"] == "KEEP"


# -- register --------------------------------------------------------------------------

def _t(i, t_open, hold_min, notional, net, sym="X"):
    return RoundTrip(symbol=sym, t_open_ms=t_open, t_close_ms=t_open + hold_min * MIN, side="buy", first_order_notional=notional,
                     opened_notional=notional, net_pnl=net, first_order_id=f"t{i}", provenance=Provenance.SIM_PLANTED)


def test_trademirror_revenge_reimplementation():
    T = 1_700_000_000_000
    trips = [_t(0, T, 10, 100, -5), _t(1, T + 20 * MIN, 10, 300, -7),       # 10 min after a loss, 3x the others
             _t(2, T + 200 * MIN, 10, 100, 2), _t(3, T + 300 * MIN, 10, 100, 1)]
    d = register.tm_revenge_tilt(trips)
    assert d.flagged and d.n_triggers == 1 and d.priced == 7
    assert "INDEPENDENT RE-IMPLEMENTATION" in d.provenance


def test_nyse_closed_and_weekend_rule_not_applicable_without_metadata():
    assert register.nyse_closed(1_699_747_200_000)          # 2023-11-12 00:00 UTC, a Sunday
    assert register.nyse_closed(1_699_970_400_000)          # Tue 2023-11-14 14:00 UTC = 09:00 New York, before the bell
    assert not register.nyse_closed(1_699_974_000_000)      # 15:00 UTC = 10:00 New York, open
    d = register.tm_weekend_rtoken([_t(0, 1_699_747_200_000, 5, 100, 1)], None)
    assert d.flagged is None


def test_exhaustion_cluster_and_tradememory_stats():
    T = 1_700_000_000_000
    trips = [_t(i, T + i * 10 * MIN, 5, 1000, -1.0) for i in range(7)]
    meta = [register.TripMeta(fee=2.0) for _ in trips]
    d = register.tm_exhaustion(trips, meta)
    assert d.flagged and d.n_triggers == 7 and abs(d.priced - (14.0 + 0.25 * 7.0)) < 1e-9
    det, st = register.tradememory_stats(trips)
    assert st["after_2_losses"] == 5 and st["of_which_1_5x"] == 0 and det.flagged is False
