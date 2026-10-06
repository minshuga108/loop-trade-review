"""Judge cockpit, selftest, sources and cold-visit tooling. No network, no keys."""
import functools
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import costs, judge, router, selftest, service
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cold_visit  # noqa: E402
import prepare_samples  # noqa: E402

if not any(getattr(r, "path", None) == "/cockpit" for r in app.routes):
    app.include_router(judge.router)          # the owner adds this line to app/main.py
c = TestClient(app)


@pytest.fixture
def fast(monkeypatch):
    """Template path only, and the review cached per trader so 24 answers run in test time."""
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setattr(service, "review", functools.lru_cache(maxsize=8)(service.review))
    monkeypatch.setattr(selftest, "pick_trader", lambda: "F")
    with selftest._LOCK:
        selftest._STATE.update(state="idle", done=0, total=0, result=None, finished_ts=0.0, error=None)
    yield


def test_pages_load_without_login_and_never_show_addresses():
    for path in ("/cockpit", "/selftest"):
        r = c.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert "0x" not in r.text
        assert 'type="password"' not in r.text
        assert "prefers-color-scheme: dark" in r.text and 'data-theme="dark"' in r.text      # same tokens as index.html
        assert "width=device-width" in r.text and "overflow-x:hidden" in r.text
    ck = c.get("/cockpit").text
    for line in ("Feature depth", "Research quality", "LUI fluency", "Personalized thesis"):
        assert line in ck
    assert "/selftest" in ck and "/verify" in ck and "/api/sources" in ck and "/api/losses" in ck
    assert "中文" in ck


def test_sources_reports_endpoints_from_the_cache_only(monkeypatch):
    monkeypatch.setattr(costs, "CACHE", {})
    s = c.get("/api/sources").json()
    bp = s["bitget_public"]
    assert bp["endpoints_total"] == len(judge.ENDPOINTS) and bp["endpoints_reached"] == 0
    assert all(e["last_reached"] is None for e in bp["endpoints"])
    assert "off" in bp["refresher"]                                     # tests set LOOP_NO_REFRESH
    assert "0x" not in json.dumps(s)                                    # aliases only
    assert {d["provenance"] for d in s["data"]} == {"REAL_PLATFORM_PUBLIC", "SIM_PLANTED"}

    from engine.market import Category

    class I:
        category = Category.SPOT
    now = time.time()
    monkeypatch.setattr(costs, "CACHE", {"RNVDAUSDT": costs.Snap(I(), None, None, 0.001, "x", None, now - 30)})
    bp = c.get("/api/sources").json()["bitget_public"]
    reached = {e["path"]: e for e in bp["endpoints"]}
    assert reached["/api/v3/market/orderbook"]["reached"] and reached["/api/v3/market/orderbook"]["symbols"] == ["RNVDAUSDT"]
    assert reached["/api/v2/spot/public/symbols"]["reached"]
    assert not reached["/api/v3/reality/market/states"]["reached"]   # windows were None
    assert 25 <= reached["/api/v3/market/tickers"]["age_s"] <= 60
    assert bp["endpoints_reached"] == 4


def test_losses_says_the_uncomfortable_parts():
    t = c.get("/api/losses").text
    assert "1.25%" in t and "independent" in t and "73.0%" in t and "court_results.json" in t
    src = (ROOT / "eval" / "RESULTS.md").read_text(encoding="utf-8")
    for n in ("118/120", "98.3%"):                       # router figures exist in the results file
        assert n in t and n in src
    import json
    cells = json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))["cells"]
    worst = max(c_["accepted"] for c_ in cells if c_["scenario"] != "costly_leak")
    assert f"{worst:.0%}" in t                            # the worst false-admission cell is quoted, not hidden


def test_selftest_prompts_are_fixed_new_and_cover_the_hard_cases():
    ps = selftest.load_prompts()
    assert len(ps) == 24 and len({p["id"] for p in ps}) == 24
    assert all(p["gold"] in router.INTENTS for p in ps)
    assert {p["lang"] for p in ps} == {"en", "zh"}
    kinds = {k for p in ps for k in p["kind"]}
    assert {"typo", "follow-up", "injection", "order-request", "cut-size"} <= kinds
    ids = {p["id"] for p in ps}
    assert all(p["after"] in ids for p in ps if p.get("after"))
    reused = set()
    for f in ("blind_questions.jsonl", "dev_questions.jsonl"):
        for line in (ROOT / "eval" / f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                reused.add(json.loads(line)["text"].strip().lower())
    assert not [p["text"] for p in ps if p["text"].strip().lower() in reused]


def test_run_prompts_records_every_row_with_timings(fast):
    res = selftest.run_prompts("F")
    rows, s = res["rows"], res["summary"]
    assert len(rows) == 24 and s["n"] == 24
    assert s["errors"] == 0                                   # zero unhandled errors
    assert all(r["chat_ms"] >= 0 and r["router_ms"] >= 0 for r in rows)        # a refusal can round to 0.0 ms
    assert s["chat_ms"]["max"] > 0
    assert s["passed"] == sum(r["pass"] for r in rows) and s["misses"] == [r["id"] for r in rows if not r["pass"]]
    by_id = {r["id"]: r for r in rows}
    assert by_id["s03"]["previous_intent"] == by_id["s02"]["chat_intent"]        # follow-ups carry the real previous answer
    assert by_id["s24"]["chat_intent"] == "help" and "injection" in by_id["s24"]["router_flags"]
    assert all(r["number_lock"] in (None, "passed") or r["number_lock"].startswith("refused") for r in rows)


def test_selftest_endpoint_runs_and_includes_cold_visit(fast):
    st = c.post("/api/selftest/run?wait=true").json()
    assert st["state"] == "done" and st["done"] == st["total"] == 24
    cv = st["result"]["cold_visit"]
    by = {x["check"]: x for x in cv["checks"]}
    assert cv["status"] == 200 and cv["total_bytes"] > cv["html_bytes"]          # rulebook.js counted
    assert by["loads with no cookie, login or key"]["pass"] and by["/api/health says ok"]["pass"]
    assert by["first-screen weight, HTML plus same-origin JS and CSS"]["pass"]
    again = c.post("/api/selftest/run").json()                                     # inside the cooldown: reused, not rerun
    assert again["cached"] is True and again["result"]["finished_at"] == st["result"]["finished_at"]
    assert c.get("/api/selftest/latest").json()["state"] == "done"


def test_frozen_first_run_is_published_with_its_misses():
    f = c.get("/api/selftest/first-run").json()
    assert f["frozen"] is True and len(f["rows"]) == 24
    assert f["summary"]["misses"] == [r["id"] for r in f["rows"] if not r["pass"]]
    assert "not a blind score" in f["note"]


def test_cold_visit_http_measure_in_process():
    m = cold_visit.measure_http("http://testserver", client=TestClient(app))
    rows = {r["check"]: r for r in cold_visit.http_checks(m)}
    assert m["status"] == 200 and m["no_login"] and m["health_ok"]
    assert any(a["url"].endswith("/static/rulebook.js") for a in m["assets"])
    assert rows["every same-origin asset loads"]["pass"]
    assert rows["first-screen weight (HTML + same-origin JS/CSS)"]["pass"]


def test_cold_visit_budgets_fail_when_exceeded():
    m = {"ttfb_s": 2.0, "weight_bytes": 1_200_000, "status": 200, "no_login": False, "health_ok": False,
         "assets": [{"status": 404}]}
    assert not any(r["pass"] for r in cold_visit.http_checks(m))
    ok = dict(m, ttfb_s=0.2, weight_bytes=50_000, no_login=True, health_ok=True, assets=[{"status": 200}])
    assert all(r["pass"] for r in cold_visit.http_checks(ok))
    assert cold_visit.same_origin_assets('<script src="/a.js"></script><script src="https://cdn.x/b.js"></script>',
                                         "https://loop.test/") == ["https://loop.test/a.js"]


def test_anonymise_keeps_every_number_and_order(tmp_path):
    src = ("time_ms,coin,side,dir,px,sz,fee,closedPnl,startPosition,oid\n"
           "1000,ETH,B,Open Long,10,1,0.01,0,0,99\n"
           "1000,ETH,B,Open Long,10,1,0.01,0,1,987654\n"
           "2000,ETH,A,Close Long,12,2,0.01,4,2,1234\n"
           "3000,BTC,A,Open Short,100,1,0.1,0,0,5\n"
           "4000,BTC,B,Close Short,90,1,0.1,10,-1,77\n")
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text(src, encoding="utf-8")
    b.write_text(prepare_samples.anonymise(src), encoding="utf-8")
    assert prepare_samples.fingerprint(a) == prepare_samples.fingerprint(b)
    assert "987654" not in b.read_text(encoding="utf-8")
    assert [x[1] for x in prepare_samples.used_files()] == [t["file"] for t in service.TRADERS if t["file"]]
