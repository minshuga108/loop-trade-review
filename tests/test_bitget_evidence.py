"""Bitget context adapter and /api/evidence, with mocked transports only (no network)."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import evidence_api
from engine import bitget_context as bc

DAY0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
MCP_503 = {"success": False, "status_code": 503, "data": "<html>503 Service Temporarily Unavailable</html>", "error": None}


def candles(n=60):
    rows, px = [], 100.0
    for i in range(n):
        px *= 1.01 if i % 3 else 0.985
        rows.append([str(DAY0 + i * 86_400_000), f"{px:.2f}", f"{px * 1.01:.2f}", f"{px * 0.99:.2f}", f"{px:.2f}", "1000", "100000", "100000"])
    return rows


def sse(obj):
    return "event: message\ndata: " + json.dumps(obj) + "\n\n"


def tool_reply(rid, payload, is_error=False):
    return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": is_error}}


def make_transport(*, mcp_payload=MCP_503, signal_payload=None, rest_ok=True, mcp_up=True, log=None):
    log = log if log is not None else []

    def handler(req: httpx.Request) -> httpx.Response:
        log.append((req.method, str(req.url)))
        assert req.method in ("GET", "POST")
        url = str(req.url)
        if "api.bitget.com" in url:
            assert req.method == "GET"            # public reads only
            if not rest_ok:
                return httpx.Response(503, text="down")
            if "/candles" in url:
                return httpx.Response(200, json={"code": "00000", "msg": "success", "data": candles()})
            if "history-fund-rate" in url:
                return httpx.Response(200, json={"code": "00000", "data": {"resultList": [
                    {"symbol": "NVDAUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(DAY0 + 10 * 86_400_000)},
                    {"symbol": "NVDAUSDT", "fundingRate": "0.0003", "fundingRateTimestamp": str(DAY0 + 10 * 86_400_000 + 8 * 3_600_000)}]}})
            return httpx.Response(404)
        body = json.loads(req.content or b"{}")
        if not mcp_up:                            # both MCP hosts down
            return httpx.Response(503, text="<html>503</html>")
        m, rid = body.get("method"), body.get("id")
        if m == "initialize":
            name = "bitget-mcp-server" if "agent.bitget.com" in url else "market-data-mcp"
            return httpx.Response(200, headers={"mcp-session-id": "s1", "content-type": "text/event-stream"},
                                  text=sse({"jsonrpc": "2.0", "id": rid, "result": {"serverInfo": {"name": name, "version": "x"}}}))
        if m == "notifications/initialized":
            return httpx.Response(202)
        if m == "tools/call":
            p = mcp_payload if "agent.bitget.com" in url else (signal_payload or {"alt_me_error": ""})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse(tool_reply(rid, p)))
        return httpx.Response(400)
    return httpx.MockTransport(handler), log


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    p = tmp_path / "calls.jsonl"
    monkeypatch.setattr(bc, "CALL_LOG", p)
    return p


def run_pass(**kw):
    t, log = make_transport(**kw)
    cache = bc.Cache()
    with httpx.Client(transport=t) as http:
        bc.refresh_once(http=http, watch=["NVDA"], cache=cache, sleep=lambda s: None)
    return cache, log


# --------------------------------------------------------------------------- classifier on real reply shapes


@pytest.mark.parametrize("payload,verdict", [
    (MCP_503, "error"),
    ({"error": ""}, "error"),
    ({"alt_me_error": ""}, "error"),
    ([{"feed": "coindesk", "error": "", "items": []}], "error"),
    ({"t2y": {"error": ""}, "t10y": {"error": ""}, "yield_curve_inverted": False}, "error"),
    ({"value": 41, "classification": "Fear"}, "answers"),
    ({"items": []}, "empty"),
])
def test_classifier_on_observed_shapes(payload, verdict):
    assert bc.classify_tool_result(200, tool_reply(1, payload))[0] == verdict


def test_classifier_iserror_and_http():
    assert bc.classify_tool_result(200, tool_reply(1, "Error executing tool crypto_market: ConnectTimeout('')", True))[0] == "error"
    assert bc.classify_tool_result(503, None)[0] == "error"


def test_parse_sse_and_json():
    assert bc.parse_mcp_body(sse({"a": 1})) == {"a": 1}
    assert bc.parse_mcp_body('{"b": 2}') == {"b": 2}
    assert bc.parse_mcp_body("") is None


# --------------------------------------------------------------------------- adapter


def test_mcp_down_falls_back_to_ta_skill_and_logs_every_call(tmp_log):
    cache, log = run_pass()
    assert cache.sources["bitget-mcp"].state == "down" and "503" in cache.sources["bitget-mcp"].detail
    assert cache.sources["signal-sentiment"].state == "down"
    assert cache.sources["signal-ta"].state == "answering"
    assert cache.sources["agenthub-funding"].state == "answering"
    day = datetime.fromtimestamp((DAY0 + 40 * 86_400_000) / 1000, timezone.utc).date().isoformat()
    ctx = bc.context_for("rNVDA", day, cache=cache)
    assert ctx["available"] and ctx["source"] == "signal-ta" and ctx["label"] == "context, not evidence"
    assert "RSI(14)" in ctx["text"] and ctx["fetched_at"] and ctx["state"] == "ok"
    rows = bc.read_call_log()
    assert len(rows) == len(log)                      # one log row per outbound request, none invented
    assert all(r["origin"] == "product" for r in rows)
    assert {r["source"] for r in rows} == {"bitget-signal", "agenthub", "bitget-mcp"}


def test_only_one_piece_and_mcp_earnings_wins_when_it_answers(tmp_log):
    day = datetime.fromtimestamp((DAY0 + 40 * 86_400_000) / 1000, timezone.utc).date()
    earn = {"success": True, "data": [{"symbol": "NVDA", "report_date": (day.replace(day=day.day)).isoformat()}]}
    cache, _ = run_pass(mcp_payload=earn)
    assert cache.sources["bitget-mcp"].state == "answering"
    ctx = bc.context_for("NVDAUSDT", day.isoformat(), cache=cache)
    assert ctx["source"] == "bitget-mcp" and "earnings" in ctx["text"] and ctx["value"]["days_from_trade"] == 0
    review = bc.attach({"trader": "A"}, "NVDA", day.isoformat(), cache=cache)
    assert list(k for k in review if k == "bitget_context") == ["bitget_context"] and review["trader"] == "A"


def test_funding_used_when_no_candle_for_that_day(tmp_log):
    cache, _ = run_pass()
    cache.rsi["NVDA"] = {}
    day = datetime.fromtimestamp((DAY0 + 10 * 86_400_000) / 1000, timezone.utc).date().isoformat()
    ctx = bc.context_for("NVDA", day, cache=cache)
    assert ctx["source"] == "agenthub-funding" and "2.00 bp" in ctx["text"]


def test_nothing_answers_says_so_with_time(tmp_log):
    cache, _ = run_pass(rest_ok=False, mcp_up=False)
    assert all(s.state == "down" for s in cache.sources.values())
    ctx = bc.context_for("NVDA", "2026-06-20", cache=cache)
    assert ctx["available"] is False and ctx["text"].startswith("No Bitget skill answered at 20")
    assert all(not r["ok"] for r in bc.read_call_log())


def test_not_asked_yet_and_no_match_states(tmp_log):
    assert bc.context_for("NVDA", "2026-06-20", cache=bc.Cache())["state"] == "not asked yet"
    cache, _ = run_pass()
    ctx = bc.context_for("NVDA", "2019-01-01", cache=cache)
    assert ctx["available"] is False and ctx["state"] == "none for this trade"


def test_stale_label(tmp_log):
    cache, _ = run_pass()
    day = datetime.fromtimestamp((DAY0 + 40 * 86_400_000) / 1000, timezone.utc).date().isoformat()
    ctx = bc.context_for("NVDA", day, cache=cache, now=time.time() + bc.STALE_S + 60)
    assert ctx["state"] == "stale"


def test_attach_never_raises():
    out = bc.attach({"x": 1}, object(), object(), cache=bc.Cache())
    assert out["x"] == 1 and out["bitget_context"]["available"] is False


@pytest.mark.parametrize("raw,base", [("xyz:NVDA", "NVDA"), ("RNVDAUSDT", "NVDA"), ("rTSLA", "TSLA"), ("NVDAUSDT", "NVDA"),
                                      ("BTC-PERP", "BTC"), ("RUNEUSDT", "RUNE"), ("<script>", None), (None, None)])
def test_base_of(raw, base):
    assert bc.base_of(raw) == base


# --------------------------------------------------------------------------- /api/evidence


@pytest.fixture
def client(tmp_path, tmp_log, monkeypatch):
    ev = tmp_path / "evidence"
    ev.mkdir()
    monkeypatch.setattr(evidence_api, "EVIDENCE", ev)
    app = FastAPI()
    app.include_router(evidence_api.router)
    return TestClient(app), ev


def test_evidence_without_files(client):
    c, _ = client
    d = c.get("/api/evidence").json()
    assert d["probe"] is None and d["probe_missing_reason"] == "no evidence file yet"
    assert d["headline"]["product_bitget_operations_called"] == 0


def test_evidence_counts_come_from_the_log(client):
    c, ev = client
    (ev / "bitget_tools_20260101T000000Z.json").write_text(json.dumps({"generated_at": "old", "calls": []}))
    (ev / "bitget_tools_20261005T221048Z.json").write_text(json.dumps({
        "generated_at": "2026-10-05T22:10:48+00:00", "rules": "read-only",
        "calls": [
            {"path": "bitget-mcp", "tool": "mcp", "operation": "initialize", "status": 200, "latency_ms": 300, "verdict": "answers"},
            {"path": "bitget-mcp", "tool": "do_query", "operation": "equity_calendar NVDA", "status": 200, "latency_ms": 200, "verdict": "error", "note": "503"},
            {"path": "bgc", "tool": "bgc", "operation": "market tickers RNVDAUSDT", "status": "exit 0", "latency_ms": 3000, "verdict": "answers"}],
        "agent_hub_surface": {"market": {"operations": 17, "public": 16, "writes": 0, "public_ops": ["getTickers"]},
                              "trade": {"operations": 25, "public": 0, "writes": 12, "public_ops": []}}}))
    run_pass()                                     # writes product rows into the temp log
    bc.log_call(source="bgc", operation="bgc:market tickers", ok=True, status="exit 0", latency_ms=1, origin="probe")
    d = c.get("/api/evidence").json()
    assert d["evidence_file"].endswith("20261005T221048Z.json")
    paths = {p["path"]: p for p in d["probe"]["paths"]}
    assert paths["bitget-mcp"]["verdict"] == "handshake only" and paths["bgc"]["verdict"] == "answers"
    assert d["probe"]["agent_hub_surface"]["public"] == 16 and d["probe"]["agent_hub_surface"]["operations"] == 42
    rows = bc.read_call_log()
    prod = [r for r in rows if r["origin"] == "product"]
    assert d["headline"]["product_calls"] == len(prod)
    hs = ("initialize", "tools/list", "discover")
    kinds = {(r["source"], evidence_api.op_kind(r["operation"])[0]) for r in prod if not any(h in r["operation"] for h in hs)}
    assert d["headline"]["product_bitget_operations_called"] == len(kinds) == 4
    assert d["headline"]["product_bitget_operations_answered"] == len(
        {(r["source"], evidence_api.op_kind(r["operation"])[0]) for r in prod
         if r["ok"] and not any(h in r["operation"] for h in hs)}) == 2
    ops = {o["operation"]: o for o in d["call_log"]["by_origin"]["product"]["operations"]}
    assert ops["market getFundingRateHistory"]["symbols"] == ["NVDAUSDT"]
    assert "do_query equity_calendar" in ops and ops["do_query equity_calendar"]["ok"] == 0
    assert d["call_log"]["by_origin"]["probe"]["calls"] == 1


def test_context_endpoint_reads_cache_only(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(bc, "CACHE", bc.Cache())

    def boom(*a, **k):
        raise AssertionError("network on the request path")
    monkeypatch.setattr(bc, "_rest", boom)
    monkeypatch.setattr(bc.McpClient, "_post", boom)
    monkeypatch.setattr(bc, "refresh_once", boom)
    r = c.get("/api/evidence/context", params={"symbol": "NVDA", "day": "2026-06-20"})
    assert r.status_code == 200 and r.json()["state"] == "not asked yet"
    assert c.get("/api/evidence/context", params={"symbol": "NVDA", "day": "bad"}).status_code == 422


def test_evidence_page_served(client):
    c, _ = client
    r = c.get("/evidence")
    assert r.status_code == 200 and "Bitget tool evidence" in r.text
