"""Bitget public market data: recorded real responses (tests/fixtures/bitget_market), mocked httpx, no network."""
import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from app import chat, market_data as md, status_api

from app import service
TID = service.TRADERS[0]["id"]
FX = Path(__file__).parent / "fixtures" / "bitget_market"
ROUTES = {"/ticker": "ticker", "/current-fund-rate": "current_fund_rate", "/history-fund-rate": "history_fund_rate",
          "/open-interest": "open_interest", "/candles": "candles_1h", "/fills": "fills", "/account-long-short": "long_short"}


def _client(counter=None, fail=False):
    def handler(req: httpx.Request):
        if counter is not None:
            counter.append(req.url.path)
        if fail:
            raise httpx.ConnectError("offline")
        for suffix, name in ROUTES.items():
            if req.url.path.endswith(suffix):
                time.sleep(0.01)
                return httpx.Response(200, text=(FX / f"{name}.json").read_text())
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _iso():
    md.reset()
    yield
    md.configure(None, force=False)
    md.reset()


def test_all_endpoints_parse_and_carry_provenance():
    md.configure(_client())
    for kind in md.PATHS:
        r = md.get(kind, "BTC")
        assert r["ok"], kind
        assert r["provenance"] == "REAL_PLATFORM_PUBLIC" and r["fetched_at"] and isinstance(r["latency_ms"], int)
    assert all(e["tier"] == "answering" for e in md.probe_status()["endpoints"])


def test_cache_and_single_flight():
    calls = []
    md.configure(_client(calls))
    ts = [threading.Thread(target=md.get, args=("funding", "BTCUSDT")) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1
    assert md.get("funding", "BTC")["cached"] is True


def test_offline_is_graceful_and_not_invented():
    md.configure(_client(fail=True))
    r = md.get("funding", "BTC")
    assert r["ok"] is False and "data" not in r
    assert md.probe_status()["endpoints"][1]["tier"] == "attempted"
    assert md.gate_context("BTC")["available"] is False
    out = chat.answer(TID, "what is funding on BTC")
    assert out["intent"] == "market" and "not available right now" in out["text"] and out["facts"] == []


def test_disabled_without_configure():
    md.configure(None, force=False)          # conftest sets LOOP_NO_REFRESH
    assert md.get("funding", "BTC")["ok"] is False


def test_gate_context_funding_meaning():
    md.configure(_client())
    c = md.gate_context("BTCUSDT")
    assert c["available"] and c["label"] == "context, not evidence" and "a long pays" in c["text"] and "open interest" in c["text"]


def test_chat_en_zh_number_lock_and_receipt():
    md.configure(_client())
    en = chat.answer(TID, "what is funding on BTC and the open interest")
    assert en["intent"] == "market" and en["number_lock"] == "passed" and "REAL_PLATFORM_PUBLIC" not in en["text"]
    assert {f["fact"] for f in en["facts"]} == {"funding_rate_pct", "open_interest"}
    assert any("/current-fund-rate" in s for s in en["receipt"]["sources"])
    zh = chat.answer(TID, "BTC 现在的资金费率和点差是多少")
    assert zh["intent"] == "market" and zh["lang"] == "zh" and zh["number_lock"] == "passed" and "多头支付" in zh["text"]
    vol = chat.answer(TID, "recent volatility on BTC")
    assert vol["number_lock"] == "passed" and "std dev" in vol["text"]
    assert any(e["tier"] == "changed an answer" for e in md.probe_status()["endpoints"])


def test_own_record_question_not_hijacked():
    assert not md.is_market_question("how much funding did I pay on BTC")
    assert not md.is_market_question("what is my biggest habit")


def test_status_strip_has_probe_tiers():
    md.configure(_client())
    md.get("open_interest", "ETH")
    status_api._CACHE.clear()
    rows = {r["id"]: r for r in status_api.sources()["sources"]}
    assert rows["mkt_open_interest"]["state"] == "live" and "answering" in rows["mkt_open_interest"]["detail"]
    assert rows["mkt_ticker"]["state"] == "off"


def test_funding_line_omitted_without_data_and_used_with_it():
    class T:  # trips with a funding field
        def __init__(self, s, f):
            self.symbol, self.funding = s, f
    class N:  # trips without one (every current RoundTrip)
        symbol = "BTCUSDT"
    assert md.funding_line([N()]) is None
    line = md.funding_line([T("BTCUSDT", -3.0), T("ETHUSDT", 1.5)])
    assert "paid 3.00" in line and "received 1.50" in line


def test_gate_check_carries_market_context():
    from app import service
    md.configure(_client())
    tid = service.TRADERS[0]["id"]
    out = service.gate_check("s1", tid, "buy 1000 BTC")
    assert out["market_context"]["available"] is True
