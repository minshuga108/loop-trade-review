"""Review cards: replay, trend/drift, ledger drift, structural gap sandbox, decay, intent sandbox, export, share."""
import json
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import cards_api, service
from app.main import app
from engine import intent, signing, trend
from engine.detectors import after_loss_labels
from engine.schema import Provenance, RoundTrip

c = TestClient(app)


# ------------------------------------------------------------------ synthetic histories (SIM, tests only)
def _trips(n=600, mult_after=(1.0, 1.0), seed=1):
    """Trips that alternate at random between wins and losses; after-loss sizes are base * mult (first half, second half)."""
    g = np.random.default_rng(seed)
    out, t, last_loss = [], 1_700_000_000_000, False
    for i in range(n):
        m = mult_after[0] if i < n // 2 else mult_after[1]
        size = 1000 * float(np.exp(g.normal(0, 0.3))) * (m if last_loss else 1.0)
        pnl = float(g.normal(0, 50))
        out.append(RoundTrip(symbol="SIM", t_open_ms=t, t_close_ms=t + 600_000, side="buy", first_order_notional=size,
                             opened_notional=size, net_pnl=pnl, first_order_id=f"o{i}", provenance=Provenance.SIM_PLANTED))
        last_loss = pnl < 0
        t += 3_600_000
    return out


def test_trend_detects_planted_drift_and_alarms():
    tr = trend.trend(_trips(mult_after=(1.0, 2.0)), "size_after_loss")
    assert tr.cusum.status == "ALARM" and tr.cusum.alarm_direction == "habit grew"
    assert tr.test.status == "CHANGE_DETECTED" and tr.test.change_ci[0] > 1.0
    assert tr.windows[0].ratio < 1.3 < tr.windows[-1].ratio


def test_trend_no_change_reports_mde_and_power_based_trades_needed():
    tr = trend.trend(_trips(mult_after=(1.0, 1.0), seed=3), "size_after_loss")
    t = tr.test
    assert t.status == "NO_CHANGE_DETECTED"
    assert t.mde_ratio > 1.0 and t.target_ratio == 1.25
    # the MDE is the power formula, not a guess
    ref_sd = tr.cusum.reference["sd"]
    assert ref_sd > 0
    # trades needed follow from the habit-trip count and the trader's own rate
    if t.more_habit_trips_needed:
        assert t.more_trades_needed == math.ceil(t.more_habit_trips_needed / t.habit_share)


def test_power_helpers_are_consistent():
    sd, nr = 0.4, 60
    need = trend.n_after_needed(sd, nr, sd, math.log(1.25))
    assert need is not None
    assert trend.mde(sd, nr, sd, need) <= math.log(1.25) + 1e-9
    assert trend.mde(sd, nr, sd, need - 1) > math.log(1.25)
    assert trend.n_after_needed(2.0, 5, 2.0, math.log(1.25)) is None        # reference alone too noisy
    assert trend.two_sided_arl(0.0) > trend.two_sided_arl(1.0) > 0
    assert trend.siegmund_arl(0.0, 0.5, 5.0) == pytest.approx(938, rel=0.01)  # textbook value for k=0.5, h=5


def test_trend_underpowered_on_short_history_and_api():
    tr = trend.trend(_trips(n=30), "size_after_loss")
    assert tr.test.status == "UNDERPOWERED" and tr.cusum.status == "UNDERPOWERED"
    j = c.get("/api/trend/D?habit=hold_asymmetry").json()
    assert j["habit"] == "hold_asymmetry" and j["provenance"] == "REAL_PLATFORM_PUBLIC" and len(j["windows"]) == trend.N_WINDOWS
    assert c.get("/api/trend/Z").status_code == 404
    assert c.get("/api/trend/B?habit=nonsense").status_code == 422


# ------------------------------------------------------------------ replay
def test_trips_filter_matches_detector_groups_and_fills_add_up():
    meta, fills, orders, ts = service._load("B")
    j = c.get("/api/trips/B?finding=size_after_loss&limit=500").json()
    assert j["total"] == int((after_loss_labels(sorted(ts, key=lambda t: t.t_open_ms)) == 1).sum())
    assert all("after_loss" in r["tags"] for r in j["rows"])
    pn = [r["net_pnl"] for r in j["rows"]]
    assert pn == sorted(pn)                                        # worst first
    i = j["rows"][0]["index"]
    d = c.get(f"/api/trip/B/{i}").json()
    net = sum(f["realized_pnl"] for f in d["fills"]) - sum(f["fee"] for f in d["fills"])
    assert net == pytest.approx(d["trip"]["net_pnl"], abs=0.01)
    assert d["candles"] is None and "not computed" in d["candles_note"] and "mae_frac" not in d
    assert c.get("/api/trip/B/99999").status_code == 404
    f = c.get("/api/trip/F/0").json()
    assert f["fills"] == [] and "no fill records" in f["fills_note"]


def test_replay_uses_offline_candles_when_present(tmp_path, monkeypatch):
    meta, fills, orders, ts = service._load("B")
    j = c.get("/api/trip/B/0").json()
    t = j["trip"]
    rows = [[t["t_open_ms"] + k * 60_000, 1, 2, 0.5, 1.5] for k in range(0, max(2, (t["t_close_ms"] - t["t_open_ms"]) // 60_000 + 1))]
    (tmp_path / f"{t['symbol']}.json").write_text(json.dumps({"interval_ms": 60_000, "rows": rows}), encoding="utf-8")
    monkeypatch.setenv("LOOP_CANDLES_DIR", str(tmp_path))
    d = c.get("/api/trip/B/0").json()
    assert d["candles"]["interval_ms"] == 60_000 and d["mae_frac"] is not None and "approximate" in d["candles_note"]


# ------------------------------------------------------------------ ledger drift and structural gap
def test_ledger_card_real_demo_and_honest_empty_state():
    j = c.get("/api/ledger-drift/B").json()
    assert j["wallet"]["status"] == "NO_RECORDS"
    if not j["demo"]:
        pytest.skip("ccxt sample not found")
    fut, wal = j["demo"]
    assert fut["reconciliation"]["status"] == "RECONCILED"
    assert fut["reconciliation"]["totals"]["FUNDING"] == pytest.approx(-0.31399125)
    assert wal["reconciliation"]["status"] == "UNEXPLAINED" and wal["reconciliation"]["residual"] == pytest.approx(-1.5)
    assert [g["gap"] for g in wal["walk"]["gaps"]] == [pytest.approx(-1.5)]   # pinned to the withdrawal row, not plugged


def test_structural_gap_sandbox_tags():
    gap = {"side": "long", "stop": 100, "prints": [[0, 104], [1, 101.2], [2, 97], [3, 96.4]], "exit_minute": 2.5, "exit_price": 96.5}
    j = c.post("/api/structural-gap/sandbox", json=gap).json()
    assert j["tag"]["tag"] == "STRUCTURAL_GAP" and j["provenance"] == "SIM_PAPER" and "typed" in j["label"]
    late = dict(gap, prints=[[0, 104], [1, 100.05], [2, 99], [5, 96]], exit_minute=5, exit_price=96)
    assert c.post("/api/structural-gap/sandbox", json=late).json()["tag"]["tag"] == "BEHAVIOURAL_BREACH"
    none = dict(gap, prints=[[0, 104], [1, 103]], exit_minute=1, exit_price=103)
    assert c.post("/api/structural-gap/sandbox", json=none).json()["tag"]["tag"] == "NOT_TRIGGERED"
    assert c.post("/api/structural-gap/sandbox", json=dict(gap, stop=-1)).status_code == 422


# ------------------------------------------------------------------ decay
def test_decay_view_and_system_only_proposes(monkeypatch):
    H = {"X-Session": "pytest-decay"}
    assert c.get("/api/decay/F", headers=H).json()["rules"] == []
    r = c.post("/api/rulebook/F/propose", json={"multiple": 1.5}, headers=H).json()
    rid = r["rule_id"]
    assert c.post(f"/api/decay/F/{rid}/check", headers=H).status_code == 409          # not armed yet
    c.post("/api/rulebook/F/arm", json={"rule_id": rid}, headers=H)
    v = c.get("/api/decay/F", headers=H).json()["rules"][0]
    assert v["since_arming"]["n_trips"] == 0 and "REPLAY" in v["replay"]["label"] and v["replay"]["curve"]
    monkeypatch.setattr(cards_api.decay_mod, "cap_decay_check",
                        lambda *a, **k: {"status": "RETIRE", "n_trips": 99, "n_affected": 20, "effect": -5.0, "p": 0.6})
    j = c.post(f"/api/decay/F/{rid}/check", headers=H).json()
    assert j["proposed_retirement"] is True and j["state"] == "PENDING_RETIREMENT"     # proposed, never retired
    book = c.get("/api/rulebook/F", headers=H).json()
    assert book["entries"][0]["state"] == "PENDING_RETIREMENT" and book["chain_ok"]
    rb = service.book("pytest-decay", "F")
    assert rb.log[-1]["kind"] == "retire_proposed" and "replayed decay check" in rb.log[-1]["reason"]


# ------------------------------------------------------------------ intent sandbox
def _stamp(H, conf=0.6, **kw):
    body = {"thesis": "breakout holds above range", "side": "long", "symbol": "BTCUSDT", "entry": 100, "stop": 95, "size": 1000,
            "confidence": conf, **kw}
    return c.post("/api/intent/stamp", json=body, headers=H)


def test_intent_stamp_resolve_grid_and_refusal():
    H = {"X-Session": "pytest-intent"}
    r = _stamp(H)
    assert r.status_code == 200
    e = r.json()["stamped"]
    assert e["payload"]["provenance"] == "SIM_PAPER" and e["payload"]["risk_usdt"] == 50.0 and len(e["hash"]) == 64
    assert _stamp(H, stop=105).status_code == 400                                     # stop on the wrong side
    j = c.post("/api/intent/resolve", json={"seq": e["seq"], "followed_plan": True, "won": False}, headers=H).json()
    assert j["view"]["grid"]["cells"]["good_loss"] == 1 and j["view"]["chain"]["intact"]
    assert c.post("/api/intent/resolve", json={"seq": e["seq"], "followed_plan": True, "won": True}, headers=H).status_code == 409
    assert c.get("/api/intent", headers={"X-Session": "pytest-other"}).json()["entries"] == []
    m = c.get("/api/intent/metrics/B").json()
    assert m["status"] == "REFUSED" and "BEFORE the order" in m["reason"]


def test_calibration_only_at_30_and_chain_detects_tampering():
    book = intent.IntentBook(clock=iter(range(10**12, 10**12 + 1000)).__next__)
    for k in range(29):
        e = book.stamp(intent.StampIn(thesis="x" * 5, side="short", symbol="ETH", entry=100, stop=110, size=10, confidence=0.7))
        book.resolve(intent.ResolveIn(seq=e["seq"], followed_plan=k % 2 == 0, won=k % 3 == 0))
    v = book.view()
    assert v["calibration"]["status"] == "NOT_ENOUGH" and v["calibration"]["needed"] == 1
    e = book.stamp(intent.StampIn(thesis="x" * 5, side="short", symbol="ETH", entry=100, stop=110, size=10, confidence=0.7))
    book.resolve(intent.ResolveIn(seq=e["seq"], followed_plan=True, won=True))
    cal = book.view()["calibration"]
    won = sum(1 for k in range(29) if k % 3 == 0) + 1
    assert cal["status"] == "MEASURED" and cal["n"] == 30
    assert cal["brier"] == pytest.approx(((0.7 - 1) ** 2 * won + 0.7 ** 2 * (30 - won)) / 30)
    assert book.verify()["intact"]
    book.entries[0]["payload"]["confidence"] = 0.99                                   # edit after the fact
    assert book.verify() == {"intact": False, "first_bad_seq": 1}


# ------------------------------------------------------------------ export and signing
def test_report_md_and_html_same_sections_self_contained(monkeypatch):
    monkeypatch.delenv("LOOP_SIGNING_KEY", raising=False)
    md = c.get("/api/report/B.md")
    html = c.get("/api/report/B.html")
    assert md.status_code == html.status_code == 200 and md.headers["x-loop-signed"] == "no"
    for sec in ("What happened", "Priority finding", "What would make this finding wrong", "Rule court", "Tomorrow", "Assumed and missing"):
        assert sec in md.text and sec in html.text
    low = html.text.lower()
    assert "<script" not in low and "src=" not in low and "@import" not in low and "url(" not in low
    assert "http://" not in low and "https://" not in low
    assert c.post("/api/report/verify", json={"text": md.text}).json()["status"] == "UNSIGNED"
    assert c.get("/api/report/B").json()["markdown"].startswith("# Weekly review")    # the JSON route still works
    assert c.get("/api/report/Q.md").status_code == 404


def test_signed_export_verifies_and_detects_alteration(monkeypatch):
    monkeypatch.setenv("LOOP_SIGNING_KEY", "test-secret")
    for ext in ("md", "html"):
        t = c.get(f"/api/report/B.{ext}").text
        assert "loop-signature v1 hmac-sha256" in t
        assert c.post("/api/report/verify", json={"text": t}).json()["status"] == "VERIFIED"
        assert c.post("/api/report/verify", json={"text": t.replace("\n", "\r\n")}).json()["status"] == "VERIFIED"
        bad = t.replace("wins", "winz", 1)
        assert c.post("/api/report/verify", json={"text": bad}).json()["status"] == "ALTERED"
    monkeypatch.setenv("LOOP_SIGNING_KEY", "another")
    assert signing.verify(t)["status"] == "OTHER_KEY"
    monkeypatch.delenv("LOOP_SIGNING_KEY")
    assert signing.verify(t)["status"] == "KEY_UNAVAILABLE"


# ------------------------------------------------------------------ share card
@pytest.mark.parametrize("tid", ["A", "B", "F"])
def test_share_svg_is_valid_sized_and_labelled(tid):
    r = c.get(f"/api/share/{tid}.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(r.text)
    assert root.get("width") == "1200" and root.get("height") == "630"
    rv = service.review(tid)
    assert rv["trader"]["provenance"] in r.text and "feTurbulence" in r.text
    ys = [float(t.get("y")) for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert max(ys) <= 620
    body_ys = [y for y in ys if y < 526]
    assert body_ys and max(body_ys) <= 520                                            # text never runs into the provenance band
    assert "https://" not in r.text.replace("http://www.w3.org/2000/svg", "")
