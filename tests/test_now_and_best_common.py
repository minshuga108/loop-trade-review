"""Live 'how is BTC' routing and the descriptive best-trades answer. No network: market_data.get is mocked."""
import pytest

from app import chat, market_data, service

TID = next(t["id"] for t in service.traders())
NOW_Q = ["What is BTC doing now?", "BTC现在怎么样？", "how is BTC", "BTC price", "BTC right now", "ETH currently", "SOL at the moment",
         "DOGE现在多少", "BTC行情", "what is rNVDA doing now?"]
HIST_Q = ["my largest loss on BTC", "worst BTC trade", "what was my biggest BTC loss"]


@pytest.mark.parametrize("q", NOW_Q)
def test_now_questions_are_market(q):
    assert market_data.is_market_question(q)


@pytest.mark.parametrize("q", HIST_Q)
def test_history_questions_are_not_market(q):
    assert not market_data.is_market_question(q)


def _ticker(kind, sym):
    if kind == "ticker":
        return {"ok": True, "symbol": sym, "fetched_at": "2026-10-08T00:00:00+00:00", "latency_ms": 5, "fetched_ts": 1,
                "data": {"lastPr": 67000.5, "bidPr": 67000.0, "askPr": 67001.0, "change24h": 0.0123}}
    if kind == "funding":
        return {"ok": True, "symbol": sym, "fetched_at": "2026-10-08T00:00:00+00:00", "latency_ms": 5, "fetched_ts": 1,
                "data": {"rate": 0.0001, "interval_h": 8.0}}
    return market_data._unavailable(kind, sym, "x")


@pytest.mark.parametrize("q", ["What is BTC doing now?", "BTC现在怎么样？"])
def test_market_answer_live_and_framed(monkeypatch, q):
    monkeypatch.setattr(market_data, "get", _ticker)
    out = chat.answer(TID, q, [], "t-now")
    assert out["intent"] == "market" and out["number_lock"] == "passed"
    assert "67000.5" in out["text"]
    assert ("not evidence" in out["text"]) or ("不是证据" in out["text"])


def test_market_answer_degrades_honestly(monkeypatch):
    monkeypatch.setattr(market_data, "get", lambda k, s: market_data._unavailable(k, s, "down"))
    out = chat.answer(TID, "What is BTC doing now?", [], "t-now")
    assert out["intent"] == "market" and "not available" in out["text"] and out["facts"] == []


def test_historical_btc_still_historical():
    out = chat.answer(TID, "my largest loss on BTC", [], "t-hist")
    assert out["intent"] != "market"


@pytest.mark.parametrize("q", ["What do my best trades have in common?", "我最好的交易有什么共同点？"])
def test_best_common(q):
    out = chat.answer(TID, q, [], "t-best")
    assert out["intent"] == "best_common" and out["number_lock"] == "passed", out["text"]
    t = out["text"]
    assert ("描述" in t) if "共同" in q else ("descriptive, not a tested habit" in t)
    assert "p=" not in t and "p-value" not in t
    assert chat.receipt(out, TID)["computations"]


def test_best_common_too_few():
    from app import best_common
    assert best_common.answer([], "en")["number_lock"] == "passed"
