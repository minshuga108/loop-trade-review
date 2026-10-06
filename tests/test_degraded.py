"""Degraded mode: Bitget down, empty or stale or broken book cache, a missing or unreadable history
file, a corrupt or unwritable record. Every page and API must still answer, with an honest message."""
from __future__ import annotations

import dataclasses
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import costs, service
from app.main import app
from engine import market
from tests.test_market_execution import _handler

c = TestClient(app, raise_server_exceptions=False)


# ---- Bitget public API ------------------------------------------------------------------------
class Boom:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        def fail(*a, **k):
            raise ConnectionError("api.bitget.com unreachable")
        return fail

    def close(self):
        pass


@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(costs, "CACHE", {})
    yield costs.CACHE


def test_refresher_survives_every_call_failing(no_cache, monkeypatch):
    assert costs.refresh_once(Boom()) == 0 and costs.CACHE == {}
    monkeypatch.setattr(costs, "Fetcher", lambda *a, **k: (_ for _ in ()).throw(OSError("no network")))
    with pytest.raises(OSError):
        costs.refresh_once()                       # the loop in start_refresher catches this one


def test_refresher_loop_keeps_running_when_refresh_raises(monkeypatch):
    calls, done = [], threading.Event()

    def bad():
        calls.append(1)
        if len(calls) >= 3:
            done.set()
            raise SystemExit                       # not an Exception: ends the test's thread, never reaches the network
        raise RuntimeError("boom")
    monkeypatch.setattr(costs, "refresh_once", bad)
    monkeypatch.setattr(costs, "REFRESH_S", 0.01)
    monkeypatch.setattr(costs, "_started", False)
    monkeypatch.delenv("LOOP_NO_REFRESH", raising=False)
    costs.start_refresher()
    assert done.wait(5) and len(calls) == 3         # it raised twice and kept going


def test_empty_cache_everything_still_answers(no_cache):
    r = c.get("/api/cost?symbol=RNVDA&size=5000")
    assert r.status_code == 200 and r.json()["available"] is False and "no recent book" in r.json()["reason"]
    g = c.post("/api/gate/F", json={"text": "Buy $20k rNVDA"})
    assert g.status_code == 200 and g.json()["check_line"]["available"] is False
    a = c.post("/api/chat", json={"trader": "F", "message": "Buy $20k rNVDA", "history": []}).json()
    assert "No recent book" in a["text"]
    s = c.get("/api/sources").json()["bitget_public"]
    assert s["endpoints_reached"] == 0 and s["symbols_cached"] == 0


def _snap(age_s: float, broken: bool = False):
    """A real snapshot from the recorded fixtures (no network), aged or broken on purpose."""
    with market.Fetcher(httpx.Client(transport=httpx.MockTransport(_handler))) as f:
        costs.refresh_once(f)
    s = costs.CACHE["RNVDAUSDT"]
    return dataclasses.replace(s, fetched_at=time.time() - age_s, book=None if broken else s.book)


def test_stale_cache_is_labelled_and_not_called_live(no_cache):
    no_cache["RNVDAUSDT"] = _snap(age_s=costs.STALE_S + 600)
    cl = costs.cost_line("rNVDA", 20_000, "buy")
    assert cl["available"] and cl["stale"]
    g = c.post("/api/gate/F", json={"text": "Buy $20k rNVDA"}).json()
    assert "execution cost above limit" not in g["evidence"]          # the gate never uses a stale book
    a = c.post("/api/chat", json={"trader": "F", "message": "Buy $20k rNVDA", "history": []}).json()
    assert "live book" not in a["text"] and "stale" in a["text"] and a["number_lock"] == "passed"


def test_broken_snapshot_does_not_break_the_gate(no_cache):
    no_cache["RNVDAUSDT"] = _snap(age_s=5, broken=True)
    cl = costs.cost_line("rNVDA", 20_000, "buy")
    assert cl["available"] is False and "could not" in cl["reason"]
    assert c.post("/api/gate/F", json={"text": "Buy $20k rNVDA"}).status_code == 200
    assert c.get("/api/cost?symbol=RNVDA&size=5000").status_code == 200


# ---- history files ------------------------------------------------------------------------------
@pytest.fixture
def missing_b(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "SAMPLES", tmp_path)          # no CSV is there
    monkeypatch.setattr(service, "SHIPPED", tmp_path)
    service._load.cache_clear()
    service._REVIEW_CACHE.pop("B", None)
    service._toggle_cached.cache_clear()
    yield
    service._load.cache_clear()
    service._toggle_cached.cache_clear()


def test_missing_history_file_degrades_to_an_honest_message(missing_b):
    t = c.get("/api/traders")
    assert t.status_code == 200
    rows = {x["id"]: x for x in t.json()}
    assert rows["B"]["available"] is False and "not in this build" in rows["B"]["note"]
    assert rows["F"]["available"] is True and rows["F"]["n_trips"] > 0       # the simulated trader needs no file
    for method, path, body in (("GET", "/api/review/B", None), ("GET", "/api/toggle/B", None), ("GET", "/api/rulebook/B", None),
                               ("GET", "/api/report/B", None), ("POST", "/api/gate/B", {"text": "buy 20k rNVDA"}),
                               ("POST", "/api/chat", {"trader": "B", "message": "habit", "history": []}),
                               ("POST", "/api/rulebook/B/propose", {"multiple": 1.5})):
        r = c.request(method, path, json=body)
        assert r.status_code == 503, (path, r.status_code, r.text[:200])
        assert "not in this build" in r.json()["detail"]
    assert c.get("/").status_code == 200 and c.get("/cockpit").status_code == 200
    s = c.get("/api/sources").json()
    assert s["data"][0]["shipped"] == 0
    m = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "review_fills", "arguments": {"trader": "B"}}}).json()
    assert m["result"]["isError"] is True and "not in this build" in m["result"]["content"][0]["text"]


def test_unreadable_history_file_is_reported_not_500(monkeypatch, tmp_path):
    (tmp_path / "wallet_B.csv").write_text("time_ms,coin\n1,BTC\n", encoding="utf-8")
    monkeypatch.setattr(service, "SAMPLES", tmp_path)
    monkeypatch.setattr(service, "SHIPPED", tmp_path)
    service._load.cache_clear()
    service._REVIEW_CACHE.pop("B", None)
    try:
        r = c.get("/api/review/B")
        assert r.status_code == 503 and "could not be read" in r.json()["detail"]
    finally:
        service._load.cache_clear()


# ---- the public record ---------------------------------------------------------------------------
@pytest.fixture
def corrupt_record(monkeypatch, tmp_path):
    p = tmp_path / "record.jsonl"
    monkeypatch.setenv("LOOP_RECORD_PATH", str(p))
    c.post("/api/gate/F", json={"text": "Buy $20k rNVDA"}, headers={"X-Session": "rec"})
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{this is not json\n")
    yield p


def test_corrupt_record_pages_and_apis_answer_honestly(corrupt_record):
    v = c.get("/api/record/verify").json()
    assert v["intact"] is False and v["first_bad_seq"] == 2
    e = c.get("/api/record/entries")
    assert e.status_code == 200 and any(x.get("corrupt") for x in e.json()["entries"])
    k = c.get("/api/record/counter")
    assert k.status_code == 200 and k.json()["corrupt_lines"] == 1 and k.json()["decisions_logged"] == 1
    assert c.get("/api/record/day/2026-01-01").status_code == 200
    assert c.get("/record").status_code == 200
    g = c.post("/api/gate/F", json={"text": "Buy $20k rNVDA"})          # the gate still answers
    assert g.status_code == 200 and g.json()["record_seq"] is None and "record" in g.json()["record_error"]


def test_unwritable_record_location_degrades(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("LOOP_RECORD_PATH", str(blocker / "sub" / "record.jsonl"))   # parent is a file
    for p in ("/api/record/entries", "/api/record/verify", "/api/record/counter", "/api/record/day/2026-01-01"):
        r = c.get(p)
        assert r.status_code == 503 and "record is unavailable" in r.json()["detail"], p
    g = c.post("/api/gate/F", json={"text": "Buy $20k rNVDA"})
    assert g.status_code == 200 and g.json()["record_seq"] is None and g.json()["record_error"]
