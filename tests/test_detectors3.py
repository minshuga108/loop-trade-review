"""Stock-perp habit detectors: chasing a prior move, off-hours trading, averaging down (planted fixtures, SIM_PLANTED)."""
import math

from engine import detectors3 as d
from engine import planted3 as p
from engine.schema import Provenance
from engine.stats import holm

NP = 400


def test_off_hours_window_and_baseline():
    mon = p.MON0                                          # a Monday 00:00 UTC
    assert d.is_off_hours(mon) and d.is_off_hours(mon + 13 * 3_600_000)         # before 13:30
    assert not d.is_off_hours(mon + 14 * 3_600_000) and not d.is_off_hours(mon + 20 * 3_600_000 + 59 * 60_000)
    assert d.is_off_hours(mon + 21 * 3_600_000)
    assert d.is_off_hours(mon + 5 * 86_400_000 + 15 * 3_600_000)                # Saturday mid-session hours
    assert math.isclose(d.BASELINE_OFF_SHARE, 1 - 5 * 450 / 10080)


def test_not_applicable_returns_none_and_is_not_in_the_family():
    tr, fills = p.planted_avgdown_trader(n=60, seed=1)          # symbol PLANTED is not an equity
    assert d.off_hours_trading(tr, n_perm=NP) is None
    assert d.chase_after_move(tr, fills, {}, n_perm=NP) is None
    assert d.averaging_down(tr, None) is None
    assert [f.detector for f in d.run_all(tr, fills, {}, n_perm=NP)] == ["averaging_down"]


def test_equity_symbols_recognised():
    for s in ("xyz:TSLA", "RNVDAUSDT", "NVDA", "rTSLA"):
        assert d.equity_base(s) in {"TSLA", "NVDA"}
    assert d.equity_base("BTC") is None and d.equity_base("xyz:GOLD") is None


def test_chase_detects_costly_chasing_with_candles_and_with_own_fills():
    tr, fills, c = p.planted_chase_trader(n=300, p_chase=0.5, tilt=-0.01, seed=3)
    assert all(t.provenance == Provenance.SIM_PLANTED for t in tr)
    for f in (d.chase_after_move(tr, None, c, n_perm=NP), d.chase_after_move(tr, fills, {}, n_perm=NP)):
        assert f.status == "FLAGGED" and f.effect < 0
        assert f.extra["chase_share"] > 1.2 * f.extra["chance_share"]             # behaviour share versus chance baseline
    assert d.chase_after_move(tr, None, c, n_perm=NP).extra["chase_share"] > 2 * d.chase_after_move(tr, None, c, n_perm=NP).extra["chance_share"]
    assert d.chase_after_move(tr, None, c, n_perm=NP).extra["price_source"] == "candles"
    assert d.chase_after_move(tr, fills, {}, n_perm=NP).extra["price_source"] == "own_fills"


def test_chase_not_flagged_when_chasing_is_costless_or_absent():
    tr, fills, c = p.planted_chase_trader(n=300, p_chase=0.5, tilt=0.0, seed=4)
    assert d.chase_after_move(tr, None, c, n_perm=NP).status != "FLAGGED"
    tr, fills, c = p.planted_chase_trader(n=300, p_chase=0.0, tilt=-0.01, seed=5)
    f = d.chase_after_move(tr, None, c, n_perm=NP)
    assert f.status != "FLAGGED" and abs(f.extra["chase_share"] - f.extra["chance_share"]) < 0.08   # chance baseline holds


def test_off_hours_planted_and_null():
    f = d.off_hours_trading(p.planted_offhours_trader(n=300, p_off=0.7, tilt=-0.01, seed=6), n_perm=NP)
    assert f.status == "FLAGGED" and f.extra["off_share"] > 0.6 and f.extra["baseline_off_share_of_hours"] > 0.77
    assert d.off_hours_trading(p.planted_offhours_trader(n=300, p_off=0.7, tilt=0.0, seed=6), n_perm=NP).status != "FLAGGED"
    thin = d.off_hours_trading(p.planted_offhours_trader(n=25, p_off=0.5, tilt=-0.02, seed=1), n_perm=NP)
    assert thin.status in ("UNDERPOWERED", "NOT_FLAGGED", "FLAGGED")


def test_averaging_down_planted_and_null_and_pyramiding_not_counted():
    tr, fills = p.planted_avgdown_trader(n=250, tilt=-0.01, seed=7)
    f = d.averaging_down(tr, fills, n_perm=NP)
    assert f.status == "FLAGGED" and f.effect < 0 and 0.2 < f.extra["share_of_trips"] < 0.5
    known, lab, adds, under = d.avg_down_labels(fills, tr)
    assert known.all() and adds > under > 0                                       # better-priced adds (pyramids) are adds, not averaging down
    tr, fills = p.planted_avgdown_trader(n=250, tilt=0.0, seed=9)
    assert d.averaging_down(tr, fills, n_perm=NP).status != "FLAGGED"
    tr, fills = p.planted_avgdown_trader(n=250, p_avg=0.0, seed=8)
    assert d.avg_down_labels(fills, tr)[1].sum() == 0


def test_larger_holm_family_is_stricter_and_none_stays_out():
    ps = [0.012, 0.3, 0.8, 1.0]
    base = holm(ps)
    big = holm(ps + [1.0, 1.0, 1.0])
    assert all(b >= a for a, b in zip(base, big)) and big[0] > base[0]
    assert holm([0.01, None, 0.5]) == [0.02, None, 0.5]


def test_service_family_counts_only_applicable_detectors():
    from app import service
    r = service.review("F")                                    # planted wallet, no fills, symbol PLANTED
    assert {f["detector"] for f in r["findings"]} == {"size_after_loss", "hold_asymmetry", "overtrading_clusters", "revenge_reentry"}
    a = service.review("A")                                    # equity perps with fills: all three apply
    assert {"chase_after_move", "off_hours_trading", "averaging_down"} <= {f["detector"] for f in a["findings"]}
