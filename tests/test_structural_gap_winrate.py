import numpy as np
import pytest

from engine import winrate as w
from engine.planted2 import planted_pnl_trips
from engine.structural_gap import (EXIT_GRACE_MS, GAP_TOLERANCE, MIN_TRIGGERED, StopPlan, behavioural_score,
                                   tag_stop_exits)

S = 1000  # ms


# ---------------------------------------------------------------- structural gap

def _series():
    # long stop at 100. prints: 101, 100.5, 100.05, 99.9 (near the stop, at t=40s), 99.5 ...
    return [(0, 101.0), (10 * S, 100.5), (20 * S, 100.05), (40 * S, 99.9), (90 * S, 99.5), (300 * S, 98.0)]


def test_honoured_when_exit_follows_a_near_print():
    tags = tag_stop_exits([("t1", 100.0, "long", 0, 50 * S, 99.9)], _series())
    assert tags[0].tag == "HONOURED" and tags[0].t_breach_ms == 40 * S


def test_behavioural_breach_when_trader_stays_in():
    tags = tag_stop_exits([("t1", 100.0, "long", 0, 300 * S, 98.0)], _series())
    assert tags[0].tag == "BEHAVIOURAL_BREACH" and tags[0].exit_lag_ms > EXIT_GRACE_MS
    assert tags[0].exit_beyond_frac == pytest.approx(0.02)


def test_structural_gap_when_first_print_beyond_is_far():
    # session break: last print 100.4, next print 97 (3 percent through a 100 stop), trader out right away
    series = [(0, 101.0), (10 * S, 100.4), (3_600 * S, 97.0), (3_610 * S, 96.9)]
    tags = tag_stop_exits([StopPlan(trip_id="g", stop=100.0, side="buy", t_open_ms=0, t_exit_ms=3_620 * S,
                                    exit_price=96.9)], series)
    assert tags[0].tag == "STRUCTURAL_GAP" and tags[0].gap_frac == pytest.approx(0.03)
    assert tags[0].gap_frac > GAP_TOLERANCE


def test_short_side_and_not_triggered():
    series = [(0, 100.0), (10 * S, 100.5), (20 * S, 101.5)]
    tags = tag_stop_exits([("s1", 101.0, "short", 0, 25 * S, 101.5),   # stop at 101 hit at 101.5, gap 0.5% -> gap
                           ("s2", 102.0, "short", 0, 25 * S, 101.5)],  # never reached
                          series)
    assert [t.tag for t in tags] == ["STRUCTURAL_GAP", "NOT_TRIGGERED"]


def test_prints_outside_the_trip_window_are_ignored():
    tags = tag_stop_exits([("t1", 100.0, "long", 0, 30 * S, 100.05)], _series())
    assert tags[0].tag == "NOT_TRIGGERED"


def test_unsorted_series_is_refused():
    with pytest.raises(ValueError):
        tag_stop_exits([("t1", 100.0, "long", 0, 50 * S, 99.9)], [(10, 1.0), (5, 1.0)])


def test_behavioural_score_excludes_gaps_but_keeps_their_cost():
    honoured = [("h%d" % i, 100.0, "long", 0, 50 * S, 99.9) for i in range(8)]
    breached = [("b%d" % i, 100.0, "long", 0, 300 * S, 98.0) for i in range(4)]
    gap_series = [(0, 101.0), (10 * S, 100.4), (3_600 * S, 97.0)]
    tags = tag_stop_exits(honoured + breached, _series())
    gaps = tag_stop_exits([("g%d" % i, 100.0, "long", 0, 3_610 * S, 96.0) for i in range(5)], gap_series)
    res = behavioural_score(tags + gaps)
    assert res["counts"]["STRUCTURAL_GAP"] == 5 and res["eligible"] == 12
    assert res["score"] == pytest.approx(8 / 12) and res["status"] == "SCORED"
    assert res["structural_gap_exit_beyond_frac_sum"] == pytest.approx(5 * 0.04)
    # adding gaps never changes the score
    assert behavioural_score(tags)["score"] == res["score"]


def test_behavioural_score_underpowered_below_minimum():
    tags = tag_stop_exits([("h", 100.0, "long", 0, 50 * S, 99.9)] * (MIN_TRIGGERED - 1), _series())
    assert behavioural_score(tags)["status"] == "UNDERPOWERED"


# ---------------------------------------------------------------- required win rate

def test_breakeven_arithmetic_from_net_results():
    # 20 wins of +30, 20 losses of -10 -> required = 10 / (30 + 10) = 0.25, actual = 0.5
    net = [30.0, -10.0] * 20
    r = w.required_win_rate(planted_pnl_trips(net))
    assert r.status == "DESCRIPTIVE"
    assert r.breakeven == pytest.approx(0.25) and r.actual == pytest.approx(0.5)
    assert r.block == w.block_size(40) == 7
    assert r.breakeven_ci[0] <= r.breakeven <= r.breakeven_ci[1]
    assert "interval" in w.__doc__ and "not a probability" in w.__doc__


def test_without_best_trade_sensitivity():
    g = np.random.default_rng(0)
    net = list(g.normal(0, 10, 80)) + [500.0]   # one outsized winner
    r = w.required_win_rate(planted_pnl_trips(net))
    wb = r.without_best
    assert wb["removed_trade_pnl"] == 500.0 and wb["n"] == 80
    assert wb["breakeven"] > r.breakeven   # the big win lifted the average win, so the required rate rises without it


def test_win_rate_null_margin_interval_usually_straddles_zero():
    # symmetric zero-mean pnl: true margin is 0; a 95% interval should cover it in most of 20 nulls
    covered = 0
    for s in range(20):
        r = w.required_win_rate(planted_pnl_trips(np.random.default_rng(s).normal(0, 10, 300)))
        covered += r.margin_ci[0] < 0 < r.margin_ci[1]
    assert covered >= 16


def test_win_rate_underpowered_on_small_or_one_sided_samples():
    assert w.required_win_rate(planted_pnl_trips([5.0, -3.0] * 10)).status == "UNDERPOWERED"
    r = w.required_win_rate(planted_pnl_trips([5.0] * 50))
    assert r.status == "UNDERPOWERED" and np.isnan(r.breakeven_ci[0])
