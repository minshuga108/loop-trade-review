"""CRIT23 items 4-8: receipts, feedback in the public record, silent-wrong chat cases, slow-model fallback, starter chips, banner and fills tile."""
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import chat, llm, qa_chat, service
from app.main import app
from engine.record import verify_file

ROOT = Path(__file__).resolve().parents[1]
CASES = [json.loads(l) for l in (ROOT / "eval" / "selftest_regress.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
client = TestClient(app)


def _run(case):
    hist = []
    for q in case.get("after", []):
        a = chat.answer(case["trader"], q, hist, "ci-regress")
        hist.append({"intent": a["intent"], "plan": a.get("plan")})
    return chat.answer(case["trader"], case["text"], hist, "ci-regress")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_regression_case(case):
    out = _run(case)
    text = out.get("text") or out.get("markdown") or ""
    assert out["intent"] == case["intent"], (case["text"], out["intent"], text[:200])
    for w in case.get("has", []):
        assert w in text, (case["text"], w, text[:300])
    for w in case.get("not", []):
        assert w not in text, (case["text"], w, text[:300])
    assert out["number_lock"] == "passed"


def test_every_answer_carries_a_receipt_built_from_its_own_fields():
    for q in ["what is my win rate", "show my weekly review", "where does this data come from", "what is my biggest costly habit?", "Buy $5k rNVDA"]:
        o = chat.answer("G", q, [], "ci-receipt")
        r = o["receipt"]
        assert r and r["sources"] and r["intent"] == o["intent"] and r["trader"] == "G"
        assert "ledger" in r and r["number_lock"] == o["number_lock"]
        if o["intent"] == "qa":
            assert r["rows"]["used"] == o["computed"]["n"] and r["rows"]["of"] == o["computed"]["n_total"]
            assert r["ledger"]["seq"] is None            # a read is never claimed as a ledger entry
        if o["intent"] == "gate":
            assert isinstance(r["ledger"]["seq"], int)   # the gate decision really is in the record
    z = chat.answer("G", "我的胜率是多少？", [], "ci-receipt")
    assert "钱包" in z["receipt"]["sources"][0]


def test_feedback_is_a_tagged_entry_in_the_public_record():
    r = client.post("/api/feedback", json={"trader": "G", "intent": "qa", "vote": "down"}, headers={"X-Session": "ci-feedback"})
    assert r.status_code == 200 and r.json()["tag"] == "feedback"
    seq = r.json()["seq"]
    from app import record_api
    e = next(e for e in record_api.get_log().entries() if e["seq"] == seq)
    assert e["kind"] == "rule_event" and e["payload"]["tag"] == "feedback" and e["payload"]["vote"] == "down"
    assert "message" not in e["payload"] and e["payload"]["session"].startswith("s_")        # no question text, hashed session
    assert verify_file(record_api.get_log().path)["intact"]
    assert client.post("/api/feedback", json={"trader": "G", "vote": "maybe"}).status_code == 400
    assert client.post("/api/feedback", json={"trader": "nope", "vote": "up"}).status_code == 404


STARTERS = re.findall(r'"([^"]+)"', (lambda s: s[s.index("const CHIP_GROUPS"):s.index("const CHIPS =")])((ROOT / "app/static/home.js").read_text(encoding="utf-8")))
GROUP_LABELS = {"New trader", "Review", "Rules", "Costs", "中文", "What would make this wrong", "What did the gate block"}


def test_starter_chips_are_grouped_and_every_one_is_answered():
    qs = [q for q in STARTERS if q not in GROUP_LABELS]
    assert 20 <= len(qs) <= 30
    for q in qs:
        o = chat.answer("B", q, [], "ci-chips")
        text = o.get("text") or o.get("markdown") or ""
        assert not (o["intent"] == "help" and "could not parse" in text) and "没能读懂" not in text and "没读懂" not in text, q
        assert not text.startswith(("Which number", "要看哪个")), q


def test_slow_model_cannot_hold_an_answer_and_a_routable_question_never_calls_it(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    calls = {"n": 0}

    def slow(*a, **k):
        calls["n"] += 1
        time.sleep(6)
        return None
    monkeypatch.setattr(qa_chat, "qwen_plan", slow)
    monkeypatch.setattr(llm, "parse_intent", slow)
    t0 = time.perf_counter()
    o = chat.answer("G", "blorp the zibble", [], "ci-slow")
    dt = time.perf_counter() - t0
    assert dt < 2.5, dt
    assert o["number_lock"] == "passed" and o["text"]                  # the deterministic fallback answered
    assert calls["n"] == 1                                              # one slow call, and no second one after the timeout
    calls["n"] = 0
    for q in ["What is my biggest costly habit?", "Show my weekly review", "what is my win rate", "Which rules were tested?"]:
        t0 = time.perf_counter()
        chat.answer("G", q, [], "ci-fast")
        assert time.perf_counter() - t0 < 1.5, q
    assert calls["n"] == 0                                              # the model is only for what the typed paths cannot place


def test_banner_is_in_the_first_byte_and_follows_engine_state():
    service.review("B")
    page = client.get("/").text
    assert 'id="vbanner"' in page and 'id="dropzone"' in page and "Paste or drop your fills" in page
    assert "nothing is armed" in page and "tested on trades it never saw" in page
    b = chat.verdict_banner("F")
    assert "you can arm it" in b["en"] and "可以启用" in b["zh"] and b["status"] == "ACCEPTED"
    assert "nothing is armed" in chat.verdict_banner("B")["en"]
    assert 'data-pick="F"' in page and 'data-pick="D"' in page              # a visible path to an accepted rule


def test_sample_csv_imports_in_well_under_twenty_seconds():
    t0 = time.perf_counter()
    csv = client.get("/api/sample-fills").text
    r = client.post("/api/import", json={"text": csv}, headers={"X-Session": "ci-sample"})
    assert r.status_code == 200 and r.json()["n_trips"] >= 30
    assert time.perf_counter() - t0 < 20


def test_cards_loaders_ignore_a_stale_render():
    js = (ROOT / "app/static/cards.js").read_text(encoding="utf-8")
    assert js.count("isConnected") >= 5 and 'el.querySelector("#c-int-f")' in js
