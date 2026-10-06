"""HTTP hardening: every route under malformed input, odd headers, traversal, HEAD/OPTIONS,
rate limits, security headers, and the rulebook / record hash chains under concurrent threads."""
from __future__ import annotations

import json
import re
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from app import judge, mcp_server, ratelimit, record_api, security, service
from app.main import app
from engine.court import Rule, Verdict
from engine.record import RecordLog
from engine.rulebook import Rulebook

c = TestClient(app, raise_server_exceptions=False)


def all_routes() -> list[tuple[str, str]]:
    out = set()
    for r in list(app.routes) + list(record_api.router.routes) + list(judge.router.routes) + list(mcp_server.router.routes):
        for m in getattr(r, "methods", None) or []:
            out.add((r.path, m))
    return sorted(out)


ODD_IDS = ["Z", "..", "..%2F..%2Fapp%2Fmain.py", "%2e%2e", "A%00", "%3Cscript%3E", "a" * 3000, "%E2%80%AE", "%F0%9F%98%80", "B%2F..%2FA"]
BODIES = [b"", b"{", b"null", b"[]", b"\"x\"", b"{\"trader\": 5, \"message\": []}", b"{\"text\": null}", b"{\"multiple\": \"NaN\"}",
          b"{\"multiple\": 1e309}", b"{\"multiple\": NaN}", b"{\"rule_id\": {\"$gt\": \"\"}}", b"\xff\xfe\x00", b"[" * 3000,
          b"{\"trader\": \"B\", \"message\": \"hi\", \"history\": [1, 2]}",
          b"{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/call\", \"params\": {\"name\": \"rule_gate\", \"arguments\": {\"trader\": \"B\", \"order_text\": \"buy 1e999\"}}}"]
HDRS = [{}, {"X-Session": "a\tb"}, {"Content-Type": "text/plain"}, {"Mcp-Session-Id": "x" * 500}, {"Origin": "https://evil.example"}]


def _fill(path: str, val: str) -> str:
    return re.sub(r"\{[^}]+\}", val, path)


def test_route_list_covers_every_router():
    paths = {p for p, _ in all_routes()}
    for must in ("/api/chat", "/api/gate/{tid}", "/api/record/verify", "/api/sources", "/mcp", "/record", "/cockpit"):
        assert must in paths


def test_mcp_deeply_nested_json_is_a_parse_error_not_500():
    r = c.post("/mcp", content=b"[" * 3000, headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700


def test_no_route_answers_500_to_malformed_input():
    bad = []
    for path, m in all_routes():
        if path == "/api/selftest/run":
            continue                                      # starts a background job; covered on its own below
        for oid in ODD_IDS:
            p = _fill(path, oid)
            for h in HDRS:
                if m in ("GET", "HEAD", "DELETE"):
                    r = c.request(m, p, headers=h)
                    if r.status_code >= 500:
                        bad.append((m, p[:60], h, r.status_code))
                else:
                    for b in BODIES:
                        r = c.request(m, p, content=b, headers={"Content-Type": "application/json", **h})
                        if r.status_code >= 500:
                            bad.append((m, p[:60], h, b[:30], r.status_code))
    assert not bad, bad[:10]


def test_validation_errors_with_inf_or_bad_bytes_are_422_not_500():
    """Regression: the 422 body echoed the input, and inf / undecodable bytes are not JSON -> 500."""
    r = c.post("/api/chat", content=b"{\"multiple\": 1e309}", headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    r = c.post("/api/chat", content=b"\xff\xfe\x00", headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422), r.text
    r = c.post("/api/rulebook/B/propose", json={"multiple": "abc"})
    assert r.status_code == 422 and "abc" not in r.text


def test_cost_query_edges():
    for q in ("size=nan", "size=inf", "size=-1", "size=1e309", "symbol=" + "A" * 5000, "side=hold"):
        r = c.get("/api/cost?symbol=RNVDA&" + q)
        assert r.status_code in (200, 422), (q, r.status_code)


def test_path_traversal_never_leaks_source():
    for p in ("/static/../app/main.py", "/static/..%2Fmain.py", "/static/%2e%2e/%2e%2e/app/main.py", "/static/..\\main.py",
              "/static/....//....//app/main.py", "/api/record/day/..%2F..%2Fetc", "/api/review/..%2F..%2Fapp%2Fmain.py"):
        r = c.get(p)
        assert r.status_code in (400, 404, 405, 422), (p, r.status_code)
        assert "FastAPI(" not in r.text and "import " not in r.text


def test_x_session_must_be_short_visible_ascii():
    assert c.get("/api/rulebook/F", headers={"X-Session": "x" * 10_000}).status_code == 400
    assert c.get("/api/rulebook/F", headers={"X-Session": "a\tb"}).status_code == 400
    assert c.get("/api/rulebook/F", headers={"X-Session": "é".encode("latin-1")}).status_code == 400
    assert c.get("/api/rulebook/F", headers={"X-Session": "s-ok_123"}).status_code == 200
    assert c.get("/api/rulebook/F").status_code == 200                    # no header: the default sandbox


def test_oversized_bodies_are_413_with_or_without_content_length():
    big = json.dumps({"trader": "B", "message": "x" * 200_000, "history": []}).encode()
    assert c.post("/api/chat", content=big, headers={"Content-Type": "application/json"}).status_code == 413

    def chunks():
        for _ in range(100):
            yield b"x" * 10_000
    r = c.post("/api/chat", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert c.post("/mcp", content=b"[" + b"1," * 40_000 + b"1]", headers={"Content-Type": "application/json"}).status_code == 413


def test_chat_history_is_capped():
    r = c.post("/api/chat", json={"trader": "B", "message": "habit", "history": [{"intent": "habit"}] * 51})
    assert r.status_code == 422
    assert c.post("/api/chat", json={"trader": "B", "message": "habit", "history": [{"intent": "habit"}] * 50}).status_code == 200


def test_head_answers_like_get_without_body_and_options_never_500():
    for p in ("/", "/api/health", "/api/traders", "/record", "/cockpit", "/static/rulebook.js"):
        g = c.get(p)
        h = c.head(p)
        assert h.status_code == g.status_code == 200 and h.content == b"", p
        assert c.options(p).status_code < 500


def test_security_headers_on_pages_apis_and_errors():
    for r in (c.get("/"), c.get("/api/review/B"), c.get("/api/review/NOPE"), c.get("/static/nope.js"), c.post("/mcp", content=b"{")):
        h = r.headers
        csp = h["content-security-policy"]
        assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
        assert "object-src 'none'" in csp and "frame-ancestors" in csp
        assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert h["x-frame-options"] == "SAMEORIGIN"


def test_csp_allows_exactly_the_shipped_inline_scripts():
    csp = c.get("/").headers["content-security-policy"]
    hashes = security.inline_script_hashes()
    assert len(hashes) == 4                               # index, cockpit, record, selftest
    for hh in hashes:
        assert hh in csp
    for p in security.STATIC.glob("*.html"):
        assert not re.search(r"\son[a-z]+\s*=", p.read_text(encoding="utf-8")), f"inline handler in {p.name} would be blocked"


def test_frame_policy_on_hugging_face(monkeypatch):
    monkeypatch.setenv("SPACE_ID", "someone/loop")
    fa, xfo = security.frame_ancestors()
    assert "https://huggingface.co" in fa and xfo is False


# ---- rate limiting ----------------------------------------------------------------------------
@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setenv("LOOP_RATELIMIT", "on")
    ratelimit.reset()
    for b in ratelimit.BUCKETS.values():            # frozen clock: no refill, so the test does not depend on machine speed
        monkeypatch.setattr(b, "clock", lambda: 0.0)
    yield
    ratelimit.reset()


def test_rate_limit_per_ip_returns_429_with_retry_after(limits_on):
    codes = [c.get("/api/traders").status_code for _ in range(int(ratelimit.LIMITS["ip"][0]) + 40)]
    assert codes[0] == 200 and 429 in codes
    r = c.get("/api/traders")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "content-security-policy" in r.headers
    assert c.get("/api/health").status_code == 200                       # health is exempt


def test_rate_limit_per_session(limits_on):
    burst = int(ratelimit.LIMITS["session"][0])
    codes = [c.get("/api/traders", headers={"X-Session": "one"}).status_code for _ in range(burst + 10)]
    assert codes[burst - 1] == 200 and codes[-1] == 429


def test_heavy_routes_have_their_own_tighter_bucket(limits_on):
    burst = int(ratelimit.LIMITS["heavy"][0])
    for i in range(burst):
        assert ratelimit.BUCKETS["heavy"].take("testclient") == 0.0
    r = c.get("/api/rulebook/F")
    assert r.status_code == 429
    assert c.get("/api/traders").status_code == 200                       # light routes still answer


def test_bucket_refills_and_is_lru_bounded():
    t = [0.0]
    b = ratelimit.Buckets(2, 1.0, max_keys=3, clock=lambda: t[0])
    assert b.take("k") == 0 and b.take("k") == 0 and b.take("k") > 0
    t[0] += 1.0
    assert b.take("k") == 0
    for i in range(10):
        b.take(f"x{i}")
    assert len(b._b) == 3


# ---- concurrency ---------------------------------------------------------------------------------
@pytest.fixture
def tiny_switch():
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)                           # force thread interleaving
    yield
    sys.setswitchinterval(old)


def test_rulebook_chain_and_ids_survive_threads(tiny_switch):
    """Regression: without the lock 8 threads produced duplicate rule ids and a forked hash chain every time."""
    v = Verdict(Rule(value=1.5), "ACCEPTED", "r", {"effect": 1}, {"effect": 1}, 0.01, 1, 0.05)
    for _ in range(5):
        rb = Rulebook()
        ts = [threading.Thread(target=lambda: [rb.record_verdict(v) for _ in range(100)]) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(rb.entries) == rb.proposed_count == 800 and rb.verify_chain()


def test_session_book_eviction_is_thread_safe(tiny_switch, monkeypatch):
    """Regression: concurrent evictions raised KeyError in move_to_end."""
    monkeypatch.setattr(service, "MAX_BOOKS", 5)
    errs = []

    def w(i):
        try:
            for j in range(2000):
                service.book(f"evict{(i * 7 + j) % 13}", "A")
        except Exception as e:                            # pragma: no cover - the failure being guarded
            errs.append(repr(e))
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs


def test_record_log_chain_survives_threads(tmp_path, tiny_switch):
    log = RecordLog(tmp_path / "r.jsonl")
    errs = []

    def w(i):
        try:
            for j in range(40):
                log.log_decision({"session": "s_x", "trader": "A", "state": "CHECKS_PASSED", "i": i, "j": j})
        except Exception as e:                            # pragma: no cover
            errs.append(repr(e))
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    v = log.verify()
    assert not errs and v["intact"] and v["entries"] == 320


def test_http_rulebook_and_record_under_concurrent_requests():
    errs = []

    def worker(i):
        for j in range(3):                             # 6 threads x 3 proposals, all in one session
            r1 = c.post("/api/rulebook/F/propose", json={"multiple": [1.0, 1.5, 2.0, 3.0][(i + j) % 4]}, headers={"X-Session": "conc"})
            r2 = c.post("/api/gate/F", json={"text": "buy 20k rNVDA"}, headers={"X-Session": "conc"})
            r3 = c.post("/api/chat", json={"trader": "F", "message": "Buy $20k rNVDA", "history": []}, headers={"X-Session": "conc"})
            errs.extend(x.status_code for x in (r1, r2, r3) if x.status_code != 200)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    b = c.get("/api/rulebook/F", headers={"X-Session": "conc"}).json()
    ids = [e["rule_id"] for e in b["entries"]]
    assert b["chain_ok"] and b["proposed"] == 18 and len(ids) == len(set(ids)) == 18
    assert c.get("/api/record/verify").json()["intact"]


def test_selftest_run_endpoint_does_not_500():
    r = c.post("/api/selftest/run?wait=false")
    assert r.status_code == 200 and r.json()["state"] in ("running", "done", "idle", "error")
