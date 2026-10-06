from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
H = {"X-Session": "pytest-1"}


def test_full_loop_on_the_planted_trader_propose_arm_gate_retire():
    r = c.post("/api/rulebook/F/propose", json={"multiple": 1.5}, headers=H).json()
    assert r["state"] == "ACCEPTED" and r["trials"] == 1
    rid = r["rule_id"]
    assert c.post("/api/rulebook/F/arm", json={"rule_id": rid}, headers=H).status_code == 200
    g = c.post("/api/gate/F", json={"text": "Buy $200k RNVDA", "after_loss": True}, headers=H).json()
    assert g["state"] == "BLOCKED_BY_YOUR_RULES" and g["paper_only"] and g["checklist"]
    assert c.post("/api/gate/F", json={"text": "Buy $200k RNVDA", "after_loss": False}, headers=H).json()["state"] != "BLOCKED_BY_YOUR_RULES"
    c.post("/api/rulebook/F/retire_propose", json={"rule_id": rid}, headers=H)
    assert c.get("/api/rulebook/F", headers=H).json()["entries"][0]["state"] == "PENDING_RETIREMENT"
    assert c.post("/api/rulebook/F/retire_confirm", json={"rule_id": rid}, headers=H).json()["entries"][0]["state"] == "RETIRED"
    assert c.get("/api/rulebook/F", headers=H).json()["chain_ok"] is True


def test_sessions_are_isolated_and_bad_input_refused():
    c.post("/api/rulebook/F/propose", json={"multiple": 1.0}, headers={"X-Session": "pytest-A"})
    other = c.get("/api/rulebook/F", headers={"X-Session": "pytest-B"}).json()
    assert other["entries"] == []
    assert c.post("/api/rulebook/F/propose", json={"multiple": 99}, headers=H).status_code == 400
    assert c.post("/api/rulebook/F/arm", json={"rule_id": "R999"}, headers=H).status_code == 409
    assert c.post("/api/rulebook/F/explode", json={"rule_id": "R1"}, headers=H).status_code == 404
    assert c.post("/api/gate/F", json={"text": "x" * 301}, headers=H).status_code == 400


def test_gate_decisions_and_rule_events_land_in_the_public_record_before_any_outcome():
    H2 = {"X-Session": "pytest-record"}
    before = c.get("/api/record/counter").json()
    r = c.post("/api/rulebook/F/propose", json={"multiple": 1.5}, headers=H2).json()
    g = c.post("/api/gate/F", json={"text": "Buy $5k RNVDA", "after_loss": False}, headers=H2).json()
    after = c.get("/api/record/counter").json()
    assert g.get("record_seq") is not None
    assert after["decisions_logged"] >= before["decisions_logged"] + 1
    assert c.get("/api/record/verify").json()["intact"] is True
