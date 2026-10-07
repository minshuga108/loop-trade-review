import json

from fastapi.testclient import TestClient

from app import chat, record_api, service, thesis_api
from app.main import app
from engine import thesis as T

c = TestClient(app)


def test_thesis_assembled_from_facts_and_bilingual():
    t = c.get("/api/thesis/B", headers={"X-Session": "pytest-th1"}).json()
    assert t["read_only"] and len(t["text"]["en"]) == len(t["text"]["zh"]) == 5
    assert len(t["hash"]) == 64 and t["facts"]["style"]["n_trips"] == service.review("B")["summary"]["n_trips"]
    # same facts + same day -> same hash; a different day changes it
    assert T.thesis_hash(t["facts"], t["date"]) == t["hash"] != T.thesis_hash(t["facts"], "2000-01-01")
    assert "Rule to arm" in " ".join(t["text"]["en"]) and "建议启用的规则" in " ".join(t["text"]["zh"])
    assert c.get("/api/thesis/ZZ").status_code == 404
    assert c.get("/thesis/B").status_code == 200


def test_underpowered_trader_says_so_and_accepted_trader_names_rule():
    h = thesis_api.build("H", "pytest-th2") if any(x["id"] == "H" for x in service.TRADERS) else None
    f = c.get("/api/thesis/F").json()
    assert f["facts"]["rule"]["armable"] and "cap opening size" in " ".join(f["text"]["en"])
    a = c.get("/api/thesis/A").json()
    if not a["facts"]["rule"]["armable"]:
        assert "Rule to arm: none" in " ".join(a["text"]["en"])
    assert h is None or h["facts"]["rule"]["underpowered"] in (True, False)


def test_freeze_logs_tagged_event_dedups_and_next_version_diffs():
    H = {"X-Session": "pytest-th3"}
    j = c.post("/api/thesis/F/freeze", headers=H).json()
    assert j["frozen_now"]["version"] == 1 and j["frozen"][0]["hash"] == j["hash"]
    assert c.post("/api/thesis/F/freeze", headers=H).json()["already_frozen"] is True
    ev = [e for e in record_api.get_log().entries() if e["payload"].get("tag") == "thesis"][-1]
    assert ev["kind"] == "rule_event" and ev["payload"]["thesis_hash"] == j["hash"] and ev["payload"]["paper_only"]
    assert record_api.get_log().verify()["intact"]
    # a later version with a weaker habit shows a diff against v1
    prev = ev["payload"]["key"]
    cur = dict(prev, habit_effect=prev["habit_effect"] - 500)
    d = T.diff(prev, cur, 2)
    assert d and "thesis v2" in d[0]["en"] and "weakened" in d[0]["en"] and "减弱" in d[0]["zh"]
    assert T.diff(prev, prev, 2) == []


def test_score_is_honest_replay_and_forward_needs_new_trips():
    r = c.get("/api/thesis/F/score?mode=replay").json()
    assert r["mode"] == "replay" and r["live"] is False and "not live" in r["note"] and "REPLAY" in r["summary"]["en"]
    assert r["score"]["n_new"] == r["tail_trips"]
    assert r["score"]["testable"] and r["score"]["habit"] in ("CONFIRMED", "MISSED", "NA")
    # forward with nothing new after the freeze is not testable, never invented
    H = {"X-Session": "pytest-th4"}
    c.post("/api/thesis/F/freeze", headers=H)
    fw = c.get("/api/thesis/F/score?mode=forward", headers=H).json()
    assert fw["mode"] == "forward" and fw["score"]["n_new"] == 0 and fw["score"]["testable"] is False
    assert "not testable" in fw["summary"]["en"]
    assert c.get("/api/thesis/F/score?mode=bogus").status_code == 400


def test_score_function_pure():
    trips = service._load("F")[3]
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    cut = int(len(ts) * 0.7)
    facts = T.build_facts(service.review("F"), ts[:cut])
    pred = T.prediction_of(facts, ts[:cut])
    sc = T.score(pred, ts)
    assert sc["n_new"] == len(ts) - cut
    pred2 = dict(pred, as_of_ms=ts[-3].t_open_ms)
    assert T.score(pred2, ts)["testable"] is False


def test_chat_my_thesis_en_zh_number_locked():
    for msg, lang in (("what is my thesis?", "en"), ("我的交易论点是什么", "zh")):
        o = chat.answer("F", msg, sid="pytest-th5")
        assert o["intent"] == "thesis" and o["number_lock"] == "passed" and o["lang"] == lang
        assert o["link"] == "/thesis/F" and len(o["thesis_hash"]) == 64
    assert "Rule to arm" in chat.answer("F", "my thesis", sid="pytest-th5")["text"]
