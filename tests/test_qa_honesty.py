"""CRIT19 round 3: no filter leaking between questions, honest refusals, USDT units, grammar, card hygiene."""
from __future__ import annotations

import re

import pytest

from app import chat, qa_chat

TID = "B"


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)


def _chain(*msgs):
    hist, out = [], None
    for m in msgs:
        out = chat.answer(TID, m, hist)
        hist.append({"intent": out.get("intent"), "plan": out.get("plan")})
    return out


def test_weekday_filter_does_not_leak_into_fresh_grouping():
    o = _chain("net pnl by weekday", "and on fridays?", "which weekday is my worst")
    assert o["plan"] == {"metric": "net_pnl", "group_by": "weekday"}
    assert "Only one group" not in o["text"] and "lowest" in o["text"]


def test_fresh_grouping_drops_all_inherited_filters():
    o = _chain("net pnl on BTC", "which weekday is my worst")
    assert o["plan"] == {"metric": "net_pnl", "group_by": "weekday"}


def test_named_slice_replaces_inherited_grouping():
    o = _chain("net pnl by weekday", "and on fridays?")
    assert o["plan"] == {"metric": "net_pnl", "filters": {"weekdays": [4]}}


@pytest.mark.parametrize("msg", ["what was my pnl on the first of september", "what was my pnl on 2026-09-01", "pnl on sept 1",
                                 "win rate on september 3rd", "net pnl on the 5th of the month"])
def test_named_date_is_refused_not_answered_with_the_total(msg):
    r = qa_chat.answer_qa(TID, msg)
    assert r["plan"] is None and r["facts"] == [] and r["flags"] == ["unparsed:date"]
    assert "calendar date" in r["text"] and "2,035" not in r["text"]


def test_after_losses_is_applied_not_dropped():
    r = qa_chat.answer_qa(TID, "how much did I lose after losses")
    assert r["plan"]["filters"] == {"after_loss": True}
    assert "112 trades" not in r["text"]


def test_lowest_weekday_groups_by_weekday():
    r = qa_chat.answer_qa(TID, "what is the lowest weekday pnl")
    assert r["plan"] == {"metric": "net_pnl", "group_by": "weekday"} and "lowest on" in r["text"]


def test_every_money_amount_in_chat_has_usdt():
    for msg in ["what is my net pnl", "what was my biggest loss", "how much did fees cost me", "net pnl by weekday", "what was my best day"]:
        r = qa_chat.answer_qa(TID, msg)
        assert "USDT" in r["text"], msg
    r = qa_chat.answer_qa(TID, "what is my net pnl")
    assert r["card"]["tiles"][0]["value"].endswith("USDT")
    r = chat.answer(TID, "what if I had kept rule 1?")
    assert "USDT" in r["text"]


def test_singular_grammar_and_one_trade_group_not_compared():
    r = qa_chat.answer_qa(TID, "net pnl on shorts")
    assert "1 trade," in r["text"] or "1 trade is" in r["text"] or "over 1 trade " in r["text"]
    assert not re.search(r"(?<![\d.,])1 trades", r["text"])
    r = qa_chat.answer_qa(TID, "compare long vs short")
    assert not re.search(r"(?<![\d.,])1 trades", r["text"]) and "lowest for shorts" not in r["text"] and "too few to compare" in r["text"]
    assert r["number_lock"] == "passed"


def test_no_duplicate_tiles_and_no_chinese_labels_in_english_cards():
    for msg in ["how many trades on tuesdays", "what was my worst trade", "what was my best day"]:
        t = qa_chat.answer_qa(TID, msg)["card"]["tiles"]
        pairs = [(x["label"], x["value"]) for x in t]
        assert len(pairs) == len(set(pairs)), msg
        assert not any(re.search(r"[一-鿿]", x["label"]) for x in t), msg
    zh = qa_chat.answer_qa(TID, "我最差的一笔是什么")
    assert zh is None or any(re.search(r"[一-鿿]", x["label"]) for x in zh["card"].get("tiles", [{"label": "品种"}]))
