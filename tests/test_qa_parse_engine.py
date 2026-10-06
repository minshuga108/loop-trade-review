"""engine.qa.parse itself (no app layer) handles negation, weekdays, verb phrasings and refuses unrepresentable windows."""
import pytest

from engine import qa


@pytest.mark.parametrize("msg,metric,filters", [
    ("win rate except Mondays", "win_rate", {"weekdays": [1, 2, 3, 4, 5, 6]}),
    ("pnl excluding weekends", "net_pnl", {"weekdays": [0, 1, 2, 3, 4]}),
    ("net pnl not counting shorts", "net_pnl", {"side": "buy"}),
    ("fees on weekdays", "total_fees", {"weekdays": [0, 1, 2, 3, 4]}),
    ("what did I lose on Tuesdays?", "net_pnl", {"weekdays": [1]}),
    ("how many times did I lose on BTC", "losses", {"symbol": "BTC"}),
])
def test_parse_plans(msg, metric, filters):
    pr = qa.parse(msg)
    assert pr.kind == "plan" and pr.plan.metric == metric and pr.plan.compact().get("filters") == filters


@pytest.mark.parametrize("msg", ["net pnl yesterday", "win rate in the last 2 weeks", "net pnl since September", "how many days did I lose money"])
def test_parse_refuses_unrepresentable(msg):
    pr = qa.parse(msg)
    assert pr.kind == "unparsed" and pr.plan is None


def test_clarify_language_is_not_swapped():
    assert "Which number" in qa.render_clarify(qa.parse("how did I do on shorts"), "en")["text"]
    assert "要看哪个数字" in qa.render_clarify(qa.parse("how did I do on shorts"), "zh")["text"]
