import pytest
from app import chat

POS = ["Did I trade bigger after a loss?", "did I trade bigger after a loss", "do I size up after losing", "do I bet more after a losing trade",
       "do I increase my position size after losses", "do I trade larger after I lose", "am I trading bigger after losses",
       "does my size go up after a loss", "revenge sizing", "did I trade smaller after a loss", "do I bet less after losing",
       "我亏损后下单会更大吗", "亏了之后我是不是加大仓位", "输了以后我会不会加仓", "亏损后我的仓位变大了吗"]
NEG = ["what is my longest losing streak", "longest losing streak", "最长连亏是多少", "what is my win rate", "how many trades did I make"]


@pytest.mark.parametrize("q", POS)
def test_size_after_loss_phrasings_match(q):
    assert chat.SIZE_AFTER_LOSS(q)


@pytest.mark.parametrize("q", NEG)
def test_other_questions_do_not_match(q):
    assert not chat.SIZE_AFTER_LOSS(q)


@pytest.mark.parametrize("q", ["Did I trade bigger after a loss?", "我亏损后下单会更大吗", "did I trade smaller after a loss", "revenge sizing"])
def test_answer_is_habit_with_receipt_and_lock(q):
    from app import service
    tid = "B"
    out = chat.answer(tid, q)
    assert out["intent"] == "habit"
    assert out["number_lock"] == "passed"
    assert out.get("receipt") is not None


def test_longest_losing_streak_still_answers_the_streak():
    out = chat.answer("B", "what is my longest losing streak")
    assert out["intent"] != "habit" or "streak" in out["text"].lower()
    assert "size_after_loss" not in str(out.get("facts"))


def test_strip_probe_names_have_zh_keys():
    import pathlib
    from app import market_data as md
    js = pathlib.Path(__file__).resolve().parents[1].joinpath("app/static/i18n.js").read_text(encoding="utf-8")
    for n in md.NAMES.values():
        assert f'"Bitget public {n.lower()}"' in js
