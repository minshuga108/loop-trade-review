import pytest
from fastapi.testclient import TestClient

from app import chat
from app.main import app
from engine import numberlock, report
from app import service

c = TestClient(app)


def test_numberlock_accepts_facts_and_refuses_invented_numbers():
    numberlock.verify("effect is $1,234 and p=0.024", [1234.0, 0.024])
    with pytest.raises(numberlock.NumberLockError):
        numberlock.verify("effect is $9,999", [1234.0])


def test_intent_routing_english_and_chinese():
    assert chat.route("What is my biggest costly habit?") == "habit"
    assert chat.route("我最大的坏习惯是什么？") == "habit"
    assert chat.route("show my weekly review") == "report"
    assert chat.route("给我看这周的复盘") == "report"
    assert chat.route("what if I had kept rule 2?") == "rule"
    assert chat.route("blah blah") == "help"


def test_chat_answers_carry_only_computed_numbers():
    for tid in "ABF":
        for msg in ("What is my biggest costly habit?", "what if I had kept rule 2?", "rule court", "我最大的坏习惯是什么？"):
            r = c.post("/api/chat", json={"trader": tid, "message": msg}).json()
            assert r["number_lock"] == "passed", (tid, msg, r)


def test_chat_report_both_languages_and_unknown_trader():
    en = c.post("/api/chat", json={"trader": "B", "message": "weekly review"}).json()
    zh = c.post("/api/chat", json={"trader": "B", "message": "给我看这周的复盘"}).json()
    assert en["kind"] == "report" and "Weekly review" in en["markdown"]
    assert zh["kind"] == "report" and "复盘报告" in zh["markdown"]
    assert c.post("/api/chat", json={"trader": "Z", "message": "hi"}).status_code == 404


def test_report_diff_shows_nothing_changed_second_time(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "SNAP", tmp_path)
    rv = service.review("A")
    first = report.build(rv, report.previous_snapshot("A"))
    assert "first review" in first["markdown"]
    report.save_snapshot("A", first["facts"])
    second = report.build(rv, report.previous_snapshot("A"))
    assert "Nothing changed" in second["markdown"]


def test_overlong_message_rejected():
    assert c.post("/api/chat", json={"trader": "A", "message": "x" * 501}).status_code == 400


def test_qwen_helper_is_off_without_key_and_safe_with_mock(monkeypatch):
    import httpx

    from app import llm
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    assert llm.parse_intent("anything") is None and "off" in llm.label()
    monkeypatch.setenv("QWEN_API_KEY", "test-key-not-real")

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-key-not-real"
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"intent\": \"habit\"}"}}]})
    assert llm.parse_intent("what is wrong with me", client=httpx.Client(transport=httpx.MockTransport(handler))) == "habit"

    def bad(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"intent\": \"place_order\"}"}}]})
    assert llm.parse_intent("buy", client=httpx.Client(transport=httpx.MockTransport(bad))) is None   # off-list intent refused


def test_llm_spend_is_capped_per_session_and_per_day(monkeypatch):
    import httpx

    from app import llm
    monkeypatch.setenv("QWEN_API_KEY", "test-key-not-real")
    monkeypatch.setattr(llm, "SESSION_CAP", 2)
    monkeypatch.setattr(llm, "DAILY_CAP", 3)
    llm._day, llm._total, llm._per = "", 0, {}
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"intent\": \"habit\"}"}}]})
    cl = httpx.Client(transport=httpx.MockTransport(handler))
    assert llm.parse_intent("x", client=cl, sid="a") == "habit"
    assert llm.parse_intent("x", client=cl, sid="a") == "habit"
    assert llm.parse_intent("x", client=cl, sid="a") is None          # session cap reached: template path
    assert llm.parse_intent("x", client=cl, sid="b") == "habit"
    assert llm.parse_intent("x", client=cl, sid="c") is None          # daily cap reached
    assert calls["n"] == 3
