import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
c = TestClient(app)


def test_cohort_card_numbers_are_the_results_file():
    d = json.loads((ROOT / "cohort_results.json").read_text(encoding="utf-8"))
    j = c.get("/api/cohort_card").json()
    s = d["detectors"]["size_after_loss"]
    assert j["n_wallets"] == d["n_wallets"] and j["n_round_trips"] == d["n_round_trips"]
    assert j["habit_after_correction"] == s["bh_significant"] and j["tested"] == s["tested"]
    assert j["pooled_p"] == s["pooled"]["p_pooled_shuffle"]
    assert "Hyperliquid" in j["provenance"]
    js = (ROOT / "app/static/cohort_card.js").read_text(encoding="utf-8")
    assert "not Bitget users" in js and "/api/cohort_card" in js and "cohort_card.js" in (ROOT / "app/static/index.html").read_text(encoding="utf-8")


def test_walkforward_view_labels_both_views_and_counts_trials():
    h = {"X-Session": "pytest-wf"}
    j = c.get("/api/rulebook/F/walkforward?multiple=1.5", headers=h).json()
    assert j["paper_only"] and j["trials"] >= 1
    assert j["in_sample"]["n_trips"] > j["walk_forward"]["n_trips"]          # in-sample sees everything, walk-forward only unseen chunks
    assert j["in_sample"]["alpha"] == 0.05 and j["walk_forward"]["alpha"] <= 0.05 / j["trials"] + 1e-9
    assert j["walk_forward"]["verdict"] in ("ACCEPTED", "REJECTED", "UNDERPOWERED")
    assert c.get("/api/rulebook/F/walkforward?multiple=99", headers=h).status_code == 400
    assert c.get("/api/rulebook/ZZ/walkforward", headers=h).status_code == 404


def test_hostile_generator_plants_no_size_habit_and_applies_stress():
    sys.path.insert(0, str(ROOT / "scripts"))
    import robustness_suite as rs
    base = rs.hostile_trader("baseline_null", 200, 1)
    drift = rs.hostile_trader("size_drift", 200, 1)
    assert len(drift) == 200 and drift[-1].first_order_notional > 3 * base[-1].first_order_notional
    assert rs.hostile_trader("all_four", 200, 1)[0].provenance.name == "SIM_PLANTED"


def test_robustness_results_internally_consistent():
    r = json.loads((ROOT / "robustness_results.json").read_text(encoding="utf-8"))
    assert [x["stress"] for x in r["cells"]][0] == "baseline_null" and len(r["cells"]) == 6
    for x in r["cells"]:
        lo, hi = x["court_wrong_acceptance_ci"]
        assert lo <= x["court_wrong_acceptance"] <= hi and x["sims"] == r["sims_per_cell"]
    assert r["scalars"]["n_failures"] == str(len(r["failures"]))
