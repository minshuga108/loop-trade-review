import httpx
import pytest
from fastapi.testclient import TestClient

from app import costs
from app.main import app
from engine import market as mk
from tests.test_market_execution import _handler

c = TestClient(app)


@pytest.fixture()
def warm_cache():
    costs.CACHE.clear()
    with mk.Fetcher(httpx.Client(transport=httpx.MockTransport(_handler))) as f:
        n = costs.refresh_once(f)
    assert n >= 1
    yield
    costs.CACHE.clear()


def test_cache_empty_says_unavailable_and_never_invents_a_cost():
    costs.CACHE.clear()
    r = c.get("/api/cost", params={"symbol": "RNVDA", "size": 20000}).json()
    assert r["available"] is False and "cost_bps" not in r


def test_cost_line_reads_the_cache_and_resolves_symbols(warm_cache):
    r = c.get("/api/cost", params={"symbol": "rNVDA", "size": 5000}).json()
    assert r["available"] is True and r["report"]["provenance"] in ("REPLAY_NATIVE", "SIM_PAPER")
    assert r["fill_fraction"] is not None and r["report"]["caveats"]
    assert costs.resolve("NVDA") in ("NVDAUSDT", "RNVDAUSDT")


def test_gate_includes_the_check_line_and_stays_paper_only(warm_cache):
    H = {"X-Session": "pytest-cost"}
    g = c.post("/api/gate/F", json={"text": "Buy $20k RNVDA", "after_loss": False}, headers=H).json()
    assert g["paper_only"] is True and "check_line" in g and g["check_line"]["available"] is True


# ---- CRIT21: leverage tokens and traditional numerals in Rule Gate ----------------------------

def test_leverage_token_is_not_a_size_and_never_passes():
    from engine.gate import parse_order, check
    for t in ("yolo all in on BTC 100x", "long BTC 20 x", "BTC x50 long"):
        idea = parse_order(t)
        assert idea.notional is None, t
        res = check(idea, [], [], 1000.0, False, [])
        assert res.state == "COULD_NOT_CHECK"
    assert parse_order("buy $5k BTC 10x").notional == 5000
    assert parse_order("buy BTC 10x 3000 USDT").notional == 3000


def test_traditional_chinese_numerals():
    from engine.gate import parse_order
    assert parse_order("買 一萬 rTSLA").notional == 10_000
    assert parse_order("買 一萬 rTSLA").side == "buy"
    assert parse_order("买 三万五千 rTSLA").notional == 35_000
    assert parse_order("賣 十萬 BTC").notional == 100_000
