import numpy as np

from engine import detectors2 as d
from engine import ledger
from engine.planted2 import planted_fills, planted_overtrader, planted_revenge_trader
from engine.schema import Provenance, RoundTrip

N_PERM = 600


# ---------------------------------------------------------------- overtrading clusters

def test_overtrading_flags_planted_bad_heavy_days():
    f = d.overtrading_clusters(planted_overtrader(heavy_tilt=-0.006, seed=1), n_perm=N_PERM)
    assert f.status == "FLAGGED"
    assert f.effect < 0 and f.ci[1] < 0
    assert f.extra["heavy_days"] >= 5


def test_overtrading_null_heavy_days_without_a_cost_is_not_flagged():
    # the trader does have heavy days, but they cost nothing: must not be flagged
    f = d.overtrading_clusters(planted_overtrader(heavy_tilt=0.0, seed=1), n_perm=N_PERM)
    assert f.status == "NOT_FLAGGED"


def test_overtrading_false_positive_rate_is_low_on_nulls():
    flags = sum(d.overtrading_clusters(planted_overtrader(heavy_tilt=0.0, seed=s), n_perm=300).status == "FLAGGED"
                for s in range(20))
    assert flags <= 2      # nominal rate is 5 percent before the effect floor; 20 nulls


def test_overtrading_threshold_is_the_traders_own_percentile():
    trips = planted_overtrader(seed=3)
    labels, thr, n_days = d.heavy_day_labels(trips)
    days = [t.t_open_ms // d.DAY_MS for t in trips]
    counts = np.unique(days, return_counts=True)[1]
    assert thr == float(np.percentile(counts, 90))
    assert all(days.count(day) > thr for day, h in zip(days, labels) if h)


def test_overtrading_few_days_is_underpowered():
    f = d.overtrading_clusters(planted_overtrader(n_days=10, heavy_tilt=-0.01, seed=2), n_perm=N_PERM)
    assert f.status == "UNDERPOWERED" and "active UTC days" in f.detail


# ---------------------------------------------------------------- fee drag

def test_trip_fees_match_fills_and_ledger_net():
    fills = planted_fills(n=60, seed=4)
    trips = ledger.to_round_trips(fills)
    fees = d.trip_fees(fills, trips)
    assert len(trips) == 60 and not np.isnan(fees).any()
    assert abs(fees.sum() - sum(f.fee for f in fills)) < 1e-6
    seg = d.trip_fills(fills)
    for t, fee in zip(trips, fees):
        fs = seg[(t.symbol, t.t_open_ms, t.first_order_id)]
        assert abs(sum(x.realized_pnl for x in fs) - fee - t.net_pnl) < 1e-9


def test_fee_drag_matches_direct_arithmetic_and_interval_covers_it():
    fills = planted_fills(n=200, fee_rate=0.0006, seed=1)
    trips = ledger.to_round_trips(fills)
    fd = d.fee_drag(trips, d.trip_fees(fills, trips))
    seg = d.trip_fills(fills)
    gross = np.array([sum(x.realized_pnl for x in seg[(t.symbol, t.t_open_ms, t.first_order_id)]) for t in trips])
    direct = sum(f.fee for f in fills) / gross[gross > 0].sum()
    assert fd.status == "DESCRIPTIVE"
    assert abs(fd.share - direct) < 1e-9
    assert fd.ci[0] <= fd.share <= fd.ci[1]


def test_fee_drag_orders_a_high_fee_trader_above_a_low_fee_one():
    lo_f, hi_f = planted_fills(n=200, fee_rate=0.0002, seed=5), planted_fills(n=200, fee_rate=0.0010, seed=5)
    lo_t, hi_t = ledger.to_round_trips(lo_f), ledger.to_round_trips(hi_f)
    lo, hi = d.fee_drag(lo_t, d.trip_fees(lo_f, lo_t)), d.fee_drag(hi_t, d.trip_fees(hi_f, hi_t))
    assert hi.share > lo.share and hi.ci[0] > lo.ci[1]


def test_fee_drag_unknown_fees_are_dropped_not_guessed_and_small_samples_underpowered():
    fills = planted_fills(n=30, seed=6)
    trips = ledger.to_round_trips(fills)
    other = RoundTrip(symbol="ZZZ", t_open_ms=1, t_close_ms=2, side="buy", first_order_notional=1.0,
                      opened_notional=1.0, net_pnl=1.0, first_order_id="none", provenance=Provenance.SIM_PLANTED)
    fees = d.trip_fees(fills, trips + [other])
    assert np.isnan(fees[-1])
    fd = d.fee_drag(trips + [other], fees)
    assert fd.extra["trips_without_fee_data"] == 1 and fd.n_trips == 30
    small = d.fee_drag(trips[:10], d.trip_fees(fills, trips[:10]))
    assert small.status == "UNDERPOWERED" and np.isnan(small.share)


# ---------------------------------------------------------------- revenge re-entry

def test_revenge_reentry_flags_planted_leak():
    f = d.revenge_reentry(planted_revenge_trader(tilt=-0.006, seed=1), n_perm=N_PERM)
    assert f.status == "FLAGGED" and f.effect < 0
    assert f.extra["mean_return_revenge"] < f.extra["mean_return_other_reentries"]


def test_revenge_reentry_bigger_size_but_same_edge_is_not_flagged():
    f = d.revenge_reentry(planted_revenge_trader(tilt=0.0, seed=1), n_perm=N_PERM)
    assert f.status == "NOT_FLAGGED"


def test_revenge_reentry_false_positive_rate_is_low_on_nulls():
    flags = sum(d.revenge_reentry(planted_revenge_trader(tilt=0.0, seed=s), n_perm=300).status == "FLAGGED"
                for s in range(20))
    assert flags <= 2


def test_revenge_labels_respect_symbol_window_loss_and_size():
    def trip(i, sym, t_open, hold, notional, net):
        return RoundTrip(symbol=sym, t_open_ms=t_open, t_close_ms=t_open + hold, side="buy",
                         first_order_notional=notional, opened_notional=notional, net_pnl=net,
                         first_order_id=str(i), provenance=Provenance.SIM_PLANTED)
    m = 60_000
    trips = [
        trip(0, "A", 0, m, 100, -5),            # loss on A
        trip(1, "A", 5 * m, m, 200, 1),         # A, 4 min after a loss, 2x median -> revenge
        trip(2, "B", 7 * m, m, 200, -1),        # different symbol, no prior on B -> not a re-entry
        trip(3, "A", 30 * m, m, 200, 1),        # A, 24 min after the close -> outside the window
        trip(4, "A", 32 * m, m, 100, -1),       # A, 1 min after a WIN -> re-entry, not revenge
        trip(5, "A", 34 * m, m, 120, 1),        # A, after a loss but only 1.2x median -> re-entry, not revenge
    ]
    is_re, is_rv, med = d.reentry_labels(trips)
    assert med == 160.0
    # median is 160 here, so 200 is 1.25x: still under 1.4x -> trip 1 is a re-entry only
    assert is_re.tolist() == [False, True, False, False, True, True]
    assert is_rv.tolist() == [False] * 6
    trips[1] = trip(1, "A", 5 * m, m, 1000, 1)  # now clearly above 1.4x the median
    is_re, is_rv, med = d.reentry_labels(trips)
    assert is_rv.tolist() == [False, True, False, False, False, False]


def test_revenge_reentry_underpowered_with_few_reentries():
    f = d.revenge_reentry(planted_revenge_trader(n=60, tilt=-0.01, seed=2), n_perm=N_PERM)
    assert f.status == "UNDERPOWERED"
