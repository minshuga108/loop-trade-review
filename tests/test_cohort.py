"""Cohort study code on synthetic data only (no network, no real wallet)."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import build_cohort as bc  # noqa: E402
import cohort_study as cs  # noqa: E402
from engine.schema import Provenance, RoundTrip  # noqa: E402

T0 = 1_780_000_000_000  # a Thursday


def trip(t_open, t_close, pnl, notional=1000.0, sym="BTC", oid="o"):
    return RoundTrip(symbol=sym, t_open_ms=t_open, t_close_ms=t_close, side="buy", first_order_notional=notional,
                     opened_notional=notional, net_pnl=pnl, first_order_id=oid, provenance=Provenance.SIM_PLANTED)


def synthetic_csv(path: Path, n: int, seed: int, size_mult_after_loss: float = 1.0) -> None:
    """Flat-to-flat open/close pairs on a few symbols, in the sampled CSV column format."""
    g = np.random.default_rng(seed)
    t = T0
    prev_loss = False
    oid = 1000
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(bc.COLUMNS)
        for i in range(n):
            sym = ["BTC", "ETH", "SOL"][i % 3]
            px = 100.0
            sz = round(float(np.exp(g.normal(0, 0.3))) * (size_mult_after_loss if prev_loss else 1.0), 4)
            ret = float(g.normal(0, 0.02))
            px2 = round(px * (1 + ret), 4)
            pnl = (px2 - px) * sz
            hold = int(g.integers(5, 600)) * 60_000
            w.writerow([t, sym, "B", "Open Long", px, sz, 0.01, 0.0, 0.0, oid])
            w.writerow([t + hold, sym, "A", "Close Long", px2, sz, 0.01, pnl, sz, oid + 1])
            oid += 2
            prev_loss = pnl - 0.02 < 0
            t += hold + int(g.integers(30, 2000)) * 60_000


# ------------------------------------------------------------------ sampling rule

def _lb_row(addr, av, pnl, vlm, mvlm):
    perf = lambda p, v: {"pnl": str(p), "roi": "0", "vlm": str(v)}  # noqa: E731
    return {"ethAddress": addr, "accountValue": str(av),
            "windowPerformances": [["day", perf(0, 0)], ["week", perf(0, 0)], ["month", perf(0, mvlm)],
                                   ["allTime", perf(pnl, vlm)]]}


def test_eligibility_filter():
    rows = [_lb_row("0xA", 5000, 1, 2e6, 2e5), _lb_row("0xB", 500, 1, 2e6, 2e5),      # too small
            _lb_row("0xC", 5000, 1, 6e8, 2e5), _lb_row("0xD", 5000, 1, 2e6, 5e4),      # MM-scale, inactive
            {"ethAddress": "0xE", "accountValue": "x", "windowPerformances": []}]       # malformed
    assert [r["addr"] for r in bc.eligible(rows)] == ["0xa"]


def test_draw_order_is_stratified_deterministic_round_robin():
    elig = [{"addr": f"0x{i:03d}", "pnl": float(i), "account_value": 1e4, "vlm": 1e7} for i in range(50)]
    a, b = bc.draw_order(elig, seed=7), bc.draw_order(elig, seed=7)
    assert a == b
    assert [s for s, _ in a[:10]] == [1, 2, 3, 4, 5] * 2
    assert sorted(r["addr"] for _, r in a) == sorted(r["addr"] for r in elig)
    for s, r in a:                                    # quintiles of pnl: stratum 1 holds the lowest 10
        assert (s - 1) * 10 <= r["pnl"] < s * 10
    assert bc.draw_order(elig, seed=8) != a


def test_write_csv_and_trip_count_round_trip(tmp_path):
    fills = [{"time": T0, "coin": "BTC", "side": "B", "dir": "Open Long", "px": "100", "sz": "1", "fee": "0.1",
              "closedPnl": "0", "startPosition": "0", "oid": 1, "tid": 1},
             {"time": T0 + 60_000, "coin": "BTC", "side": "A", "dir": "Close Long", "px": "101", "sz": "1",
              "fee": "0.1", "closedPnl": "1", "startPosition": "1", "oid": 2, "tid": 2}]
    p = tmp_path / "x.csv"
    bc.write_csv(p, fills)
    assert p.read_text(encoding="utf-8").splitlines()[0] == ",".join(bc.COLUMNS)
    assert bc.count_trips(p) == 1


class FakeClient:
    """Serves 4500 fills in pages of 2000 by startTime, like userFillsByTime."""

    def __init__(self):
        self.fills = [{"time": T0 + i // 3, "tid": i, "oid": i, "coin": "BTC"} for i in range(4500)]
        self.calls = 0

    def info(self, body):
        self.calls += 1
        return [f for f in self.fills if f["time"] >= body["startTime"]][:2000]


def test_fetch_fills_pages_forward_without_losing_or_duplicating():
    c = FakeClient()
    got = bc.fetch_fills(c, "0xabc")
    assert len(got) == 4500 and len({f["tid"] for f in got}) == 4500
    assert c.calls <= bc.MAX_PAGES


def test_rate_limit_stops_on_429(monkeypatch):
    class R:
        status_code = 429

    c = bc.Client.__new__(bc.Client)
    c.last, c.requests = 0.0, 0
    c.window = bc.deque()

    class H:
        def post(self, *a, **k):
            return R()
    c.http = H()
    with pytest.raises(bc.RateLimited):
        c.info({"type": "userFillsByTime"})
    assert c.requests == 1                            # no retry on 429


# ------------------------------------------------------------------ statistics

def test_bh_reject_matches_textbook_example():
    p = [0.01, 0.04, 0.03, 0.005, float("nan"), 0.5]
    # m = 5 tested; thresholds at q=0.10: .02 .04 .06 .08 .10; sorted .005 .01 .03 .04 .5 -> first four pass
    assert cs.bh_reject(p, 0.10).tolist() == [True, True, True, True, False, False]
    assert not cs.bh_reject([0.2, 0.3], 0.10).any()
    assert not cs.bh_reject([float("nan")], 0.10).any()


def test_pooled_gap_from_composition_vanishes_within_trader():
    """Wallet 0 trades small and is mostly 'labelled'; wallet 1 trades big and rarely is.
    Inside each wallet the label means nothing, so only the pooled test should fire."""
    g = np.random.default_rng(1)
    x0, x1 = g.lognormal(0, 0.3, 300), g.lognormal(3, 0.3, 300)
    l0, l1 = g.random(300) < 0.8, g.random(300) < 0.2
    x, lab = np.r_[x0, x1], np.r_[l0, l1]
    grp = np.r_[np.zeros(300), np.ones(300)]
    stat = lambda a, b: -cs.median_log_gap(a, b)  # noqa: E731  (labelled is SMALLER here)
    _, p_pool = cs.perm_p_grouped(x, lab, grp, stat, within=False, n_perm=300)
    _, p_within = cs.perm_p_grouped(x, lab, grp, stat, within=True, n_perm=300)
    assert p_pool < 0.01 and p_within > 0.05


def test_real_within_trader_gap_survives_both_shuffles():
    g = np.random.default_rng(2)
    xs, labs, grps = [], [], []
    for k in range(5):
        lab = g.random(200) < 0.5
        xs.append(g.lognormal(k, 0.3, 200) * np.where(lab, 1.5, 1.0))
        labs.append(lab)
        grps.append(np.full(200, k))
    x, lab, grp = np.concatenate(xs), np.concatenate(labs), np.concatenate(grps)
    _, p_within = cs.perm_p_grouped(x, lab, grp, cs.median_log_gap, within=True, n_perm=300)
    assert p_within < 0.01


def test_within_shuffle_keeps_each_wallets_label_count():
    x = np.arange(10.0)
    lab = np.array([1, 1, 0, 0, 0, 1, 0, 0, 0, 0], bool)
    grp = np.array([0] * 5 + [1] * 5)
    seen = []
    cs.perm_p_grouped(x, lab, grp, lambda a, b: seen.append(len(a)) or 0.0, within=True, n_perm=20)
    assert set(seen) == {3}


def test_weekend_and_recent_loss_labels():
    day = 86_400_000
    sat = T0 + 2 * day                                    # T0 is a Thursday
    trips = [trip(T0, T0 + 60_000, -5.0, oid="a"),          # loss, closes at T0+1m
             trip(T0 + 30 * 60_000, T0 + 40 * 60_000, 3.0, sym="ETH", oid="b"),   # 29 min after a loss
             trip(T0 + 120 * 60_000, T0 + 130 * 60_000, 1.0, oid="c"),            # last close was a win
             trip(sat, sat + 60_000, -1.0, oid="d"),
             trip(sat + 61 * 60_000 + 60_000, sat + 3 * 3_600_000, 1.0, oid="e")]  # 61 min after a loss
    assert cs.weekend_labels(trips).tolist() == [False, False, False, True, True]
    assert cs.recent_loss_labels(trips).tolist() == [False, True, False, False, False]


def test_win_rate_gap_sign():
    assert cs.win_rate_gap(np.array([0.0, 0.0, 1.0]), np.array([1.0, 1.0])) == pytest.approx(1 - 1 / 3)


# ------------------------------------------------------------------ end to end on synthetic wallets

def test_wallet_job_and_aggregate_end_to_end(tmp_path):
    paths = []
    for k in range(3):
        p = tmp_path / f"W{k + 1:03d}.csv"
        synthetic_csv(p, 150, seed=k, size_mult_after_loss=3.0 if k == 0 else 1.0)
        paths.append(p)
    wallets = [cs.wallet_job((p.stem, str(p), 200, 100, 0)) for p in paths]
    for w in wallets:
        assert w["n_trips"] == 150
        assert set(w["detectors"]) == set(cs.DETECTORS)
        assert len(w["court"]) == 4 and w["court_trials"] == 4
        assert all(c["alpha_used"] == pytest.approx(0.0125) for c in w["court"])
    # the planted size-up wallet is the one with the large size ratio
    assert wallets[0]["detectors"]["size_after_loss"]["effect"] > 2.0
    assert wallets[0]["detectors"]["size_after_loss"]["p"] < 0.01
    agg = cs.aggregate(wallets, n_perm_pooled=100)
    assert agg["n_wallets"] == 3 and agg["n_round_trips"] == 450
    s = agg["detectors"]["size_after_loss"]
    assert s["tested"] == 3 and s["bh_significant"] >= 1
    assert {"p_pooled_shuffle", "p_within_trader_shuffle"} <= set(s["pooled"])
    assert agg["court"]["cohort_trials"] == 12
    assert set(agg["blotter_replication"]) == set(cs.BLOTTER)
    rows = cs.public_wallet_rows(wallets, {"W001": 1, "W002": 3, "W003": 5})
    text = json.dumps(cs._clean({"wallets": rows, **agg}))
    assert all("_pooled" not in r for r in rows) and '"_pooled"' not in text and "0x" not in text
    json.loads(text)                                    # NaN cleaned to null, valid JSON
