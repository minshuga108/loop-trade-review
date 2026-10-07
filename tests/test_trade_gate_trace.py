from fastapi.testclient import TestClient

from app import gate_plus, qa_chat, service
from app.main import app

c = TestClient(app)
TID = service.TRADERS[0]["id"]


def test_trade_page_and_404():
    assert c.get(f"/trade/{TID}/0").status_code == 200
    assert c.get("/trade/nope/0").status_code == 404
    assert c.get(f"/trade/{TID}/0").text.count("trade.js") == 1
    assert c.get(f"/api/trip/{TID}/0").status_code == 200


def test_gate_scenario_similar_and_logged():
    r = c.post(f"/api/gate/{TID}", json={"text": "buy $20k BTC", "scenario": ["after_loss", "bogus"]}, headers={"X-Session": "s1"})
    j = r.json()
    assert j["scenario"] == ["after_loss"] and j["last_trade_was_loss"] is True
    s = j["similar"]
    assert s["n"] >= len(s["rows"])
    assert "not a forecast" in s["label"]
    assert j["record_seq"]


def test_similar_filters():
    assert gate_plus.clean_scenarios(["bigger", "x", "high_funding"]) == ["bigger", "high_funding"]
    assert gate_plus.clean_scenarios("bigger") == []


def test_tool_trace_in_receipt():
    r = c.post("/api/chat", json={"trader": TID, "message": "what is my net pnl?"}, headers={"X-Session": "s2"}).json()
    tt = (r.get("receipt") or {}).get("tool_trace")
    assert tt and tt[0]["number_lock"] and "tool" in tt[0]


def test_qwen_phrase_locked(monkeypatch):
    out = {"number_lock": "passed", "text": "Net P&L is 120.", "facts": [{"fact": "n", "value": 120.0}]}
    assert qa_chat.phrase_locked(dict(out), "en", phraser=lambda t, l: "You made 120 in total.") == "qwen"
    o2 = dict(out)
    assert qa_chat.phrase_locked(o2, "en", phraser=lambda t, l: "You made 999.") == "template" and o2["text"] == out["text"]
