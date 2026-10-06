"""Odd phrasings the deterministic QA parser used to misparse, and the Qwen fallback planner (mocked, no network, no key)."""
from __future__ import annotations

import pytest

from app import chat, llm, qa_chat

TID = "B"


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)


@pytest.mark.parametrize("msg,plan", [
    ("what did I lose on Tuesdays?", {"metric": "net_pnl", "filters": {"weekdays": [1]}}),
    ("pnl excluding weekends", {"metric": "net_pnl", "filters": {"weekdays": [0, 1, 2, 3, 4]}}),
    ("win rate except Mondays", {"metric": "win_rate", "filters": {"weekdays": [1, 2, 3, 4, 5, 6]}}),
    ("net pnl not counting shorts", {"metric": "net_pnl", "filters": {"side": "buy"}}),
    ("what did I earn on non-winning trades", {"metric": "net_pnl", "filters": {"outcome": "loss"}}),
    ("fees on weekdays", {"metric": "total_fees", "filters": {"weekdays": [0, 1, 2, 3, 4]}}),
    ("how many times did I lose on BTC", {"metric": "losses", "filters": {"symbol": "BTC"}}),
    ("how many losing trades on weekdays", {"metric": "losses", "filters": {"weekdays": [0, 1, 2, 3, 4], "outcome": "loss"}}),
])
def test_clean_fixes_build_the_right_plan(msg, plan):
    r = qa_chat.answer_qa(TID, msg)
    assert r["plan"] == plan, msg
    assert r["number_lock"] == "passed"


@pytest.mark.parametrize("msg,reason", [
    ("my win rate in the last 2 weeks", "window"),
    ("net pnl yesterday", "window"),
    ("net pnl since September", "window"),
    ("how many days did I lose money", "day_outcome"),
])
def test_unrepresentable_is_refused_not_guessed(msg, reason):
    r = qa_chat.answer_qa(TID, msg)
    assert r["plan"] is None and r["facts"] == [] and r["flags"] == [f"unparsed:{reason}"]
    assert "could not parse" in r["text"] and r["card"]["type"] == "unsupported"


def test_supported_windows_still_parse():
    assert qa_chat.answer_qa(TID, "my win rate in the last 7 days")["plan"]["period"] == {"kind": "last_7d"}
    assert qa_chat.answer_qa(TID, "net pnl last week")["plan"]["period"] == {"kind": "last_7d"}


def test_clarify_text_is_in_the_askers_language():
    en = qa_chat.answer_qa(TID, "how did I do on shorts")
    assert en["card"]["type"] == "clarify" and "Which number" in en["text"]
    zh = qa_chat.answer_qa(TID, "我做空的怎么样")
    assert zh is None or "要看哪个数字" in zh["text"] or zh["card"]["type"] != "clarify"


def test_without_key_unparseable_stays_honest_and_never_numeric():
    assert qa_chat.answer_qa(TID, "zzz blorp") is None            # not a data question: chat falls through
    out = chat.answer(TID, "zzz blorp")
    assert "could not parse" in out["text"] and out["number_lock"] == "passed"


# ---------------------------------------------------------------- Qwen as a fallback planner (mocked)
def test_planner_rescues_a_low_confidence_clarify_and_every_number_is_engine_computed():
    seen = []

    def planner(text, prev):
        seen.append(text)
        return {"metric": "win_rate", "filters": {"side": "sell"}}
    r = qa_chat.answer_qa(TID, "how did I do on shorts", planner=planner)
    assert seen and r["plan"] == {"metric": "win_rate", "filters": {"side": "sell"}}
    assert r["number_lock"] == "passed" and "Qwen" in r["llm"] and r["card"]["type"] != "clarify"


def test_planner_failure_on_clarify_falls_back_to_the_clarify_question():
    for bad in (None, "garbage", {"metric": "sharpe"}, {"not_a_data_question": True}, {"metric": "net_pnl", "text": "you made 5000"}):
        r = qa_chat.answer_qa(TID, "how did I do on shorts", planner=lambda t, p, b=bad: b)
        assert r["card"]["type"] == "clarify" and r["plan"] is None and r["facts"] == [], bad


def test_planner_free_text_numbers_are_refused():
    r = qa_chat.answer_qa(TID, "zzz blorp", planner=lambda t, p: {"metric": "net_pnl", "answer": "you made 12345"})
    assert r["plan"] is None and r["card"]["type"] == "refused" and "12345" not in r["text"]


def test_planner_plan_still_passes_negation_and_window_guards():
    r = qa_chat.answer_qa(TID, "how did I do except Mondays", planner=lambda t, p: {"metric": "net_pnl", "filters": {"weekdays": [0]}})
    assert r["plan"]["filters"]["weekdays"] == [1, 2, 3, 4, 5, 6]
    r = qa_chat.answer_qa(TID, "how did I do in the last 3 weeks", planner=lambda t, p: {"metric": "net_pnl"})
    assert r["plan"] is None and r["flags"] == ["unparsed:window"]


def test_planner_not_consulted_when_parser_is_confident():
    seen = []
    r = qa_chat.answer_qa(TID, "what did I lose on Tuesdays?", planner=lambda t, p: seen.append(t))
    assert seen == [] and r["plan"]["metric"] == "net_pnl"


def test_default_planner_respects_key_and_budget(monkeypatch):
    calls = []

    class Fake:
        def post(self, url, json=None, headers=None):
            calls.append(json)

            class R:
                def raise_for_status(self): pass
                def json(self): return {"choices": [{"message": {"content": '{"metric": "win_rate", "filters": {"side": "sell"}}'}}]}
            return R()
    assert qa_chat.qwen_plan("x", client=Fake()) is None and calls == []            # no key: no call
    monkeypatch.setenv("QWEN_API_KEY", "dummy-test-value")
    monkeypatch.setattr(llm, "_day", __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime()))
    monkeypatch.setattr(llm, "_total", 0)
    monkeypatch.setattr(llm, "_per", {})
    monkeypatch.setattr(llm, "SESSION_CAP", 1)
    assert qa_chat.qwen_plan("x", client=Fake(), sid="s1") == {"metric": "win_rate", "filters": {"side": "sell"}}
    assert qa_chat.qwen_plan("x", client=Fake(), sid="s1") is None and len(calls) == 1   # session cap reached: deterministic path
    assert "Authorization" not in str(calls)
