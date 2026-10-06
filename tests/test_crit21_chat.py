from app import chat, service, router
from engine import qa

TID = None


def _tid():
    return service.traders()[0]["id"]


def test_unrelated_question_not_hijacked_by_report_context():
    h = [{"intent": "report"}]
    for q in ["what is my Sharpe ratio", "do I trade better in the morning", "how volatile am I"]:
        o = chat.answer(_tid(), q, h)
        assert o["intent"] != "report" and o["kind"] != "report"


def test_sharpe_says_not_computed():
    o = chat.answer(_tid(), "what is my Sharpe ratio", None)
    assert "do not compute" in o["text"] and o["facts"] == []
    z = chat.answer(_tid(), "我的夏普比率是多少", None)
    assert "不计算" in z["text"]


def test_morning_is_honest_unsupported():
    assert qa.parse("do I trade better in the morning").reason == "session"


def test_followup_still_inherits():
    assert router.route("and rule 3?", "rule") == "rule"
    assert router.route("简短一点的版本", "report") == "report"


def test_zh_rule_answer_has_no_english_rule_name():
    o = chat.answer(_tid(), "如果我遵守规则 2 会怎样？", None)
    assert "your median" not in o["text"] and "ACCEPTED" not in o["text"] and "REJECTED" not in o["text"]


def test_zh_gate_reasons_translated():
    assert chat.gate_zh("Single order is within 10% of visible depth within 25 bps.").startswith("单笔订单")
    assert chat.rule_zh("halt for the day after 2 consecutive losing trips") == "连续亏损 2 笔后当天停手"
