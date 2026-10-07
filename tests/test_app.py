from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_health_is_read_only():
    assert c.get("/api/health").json() == {"ok": True, "mode": "read-only", "writes": False}


def test_first_screen_loads_without_login():
    r = c.get("/")
    assert r.status_code == 200 and "Loop" in r.text


def test_traders_control_first_and_labelled():
    t = c.get("/api/traders").json()
    assert t[0]["role"] == "control"
    assert all(x["label"] for x in t)
    assert any(x["provenance"] == "SIM_PLANTED" for x in t)       # simulated trader is labelled as such


def test_review_numbers_are_computed_and_honest_on_a_real_wallet():
    r = c.get("/api/review/B").json()
    assert r["trader"]["provenance"] == "REAL_PLATFORM_PUBLIC"
    assert r["court"]["proposed"] == 4 and r["court"]["tested"] == 4
    got = {f["detector"] for f in r["findings"]}
    assert {"size_after_loss", "hold_asymmetry", "overtrading_clusters", "revenge_reentry"} <= got
    assert got - {"size_after_loss", "hold_asymmetry", "overtrading_clusters", "revenge_reentry"} <= {"chase_after_move", "off_hours_trading", "averaging_down"}


def test_planted_trader_shows_the_accept_path():
    r = c.get("/api/review/F").json()
    assert r["trader"]["provenance"] == "SIM_PLANTED" and r["court"]["accepted"] >= 1


def test_toggle_has_both_effects_and_unknown_trader_404():
    t = c.get("/api/toggle/B").json(); t2 = c.get("/api/toggle/F?rule=cap").json(); assert t2["status"] == "ACCEPTED" and t2["held_out"]["effect"] > 0
    assert "in_sample" in t and "held_out" in t and t["curve_actual"] and t["curve_rule"]
    assert c.get("/api/toggle/Z").status_code == 404


def test_habit_family_is_corrected_so_a_weak_flag_is_only_suggestive():
    from engine.stats import holm
    assert holm([0.01, 0.04, None, 0.5]) == [0.03, 0.08, None, 0.5]
    b = c.get("/api/review/B").json()
    sa = next(f for f in b["findings"] if f["detector"] == "size_after_loss")
    assert sa["p"] < 0.05 and sa["p_adj"] >= 0.05 and sa["status"] == "SUGGESTIVE"      # raw p passes, corrected p does not
    f = c.get("/api/review/F").json()
    assert next(x for x in f["findings"] if x["detector"] == "size_after_loss")["status"] == "FLAGGED"   # a real planted leak survives
