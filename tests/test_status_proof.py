"""Source-status strip, record strip, /wrong, /proof, skills panel, proof baseline."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import status_api
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh():
    status_api._CACHE.clear()
    yield
    status_api._CACHE.clear()


def test_sources_strip_covers_every_source_without_secrets(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "sk-secret-value-123")
    d = client.get("/api/status/sources").json()
    ids = {s["id"] for s in d["sources"]}
    assert ids == {"book", "market", "uta", "csv", "mcp", "qwen", "chain"}
    assert all(s["state"] in ("live", "stale", "off", "broken") and s["checked_at"] for s in d["sources"])
    assert "sk-secret-value-123" not in json.dumps(d)
    assert next(s for s in d["sources"] if s["id"] == "qwen")["state"] == "live"
    assert next(s for s in d["sources"] if s["id"] == "mcp")["state"] == "live"


def test_qwen_off_without_key(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    assert next(s for s in client.get("/api/status/sources").json()["sources"] if s["id"] == "qwen")["state"] == "off"


def test_sources_are_cached_and_never_raise(monkeypatch):
    a = client.get("/api/status/sources").json()
    monkeypatch.setattr(status_api, "_qwen", lambda now: 1 / 0)      # a broken builder must not be called again within the TTL
    assert client.get("/api/status/sources").json()["generated_at"] == a["generated_at"]
    status_api._CACHE.clear()
    assert "error" in client.get("/api/status/sources").json()       # and a failing build returns a stub, not a 500


def test_record_strip_separates_user_from_other_traffic():
    d = client.get("/api/status/record").json()
    assert {"user_decisions", "not_user", "rules_armed", "rules_retired", "rules_rejected", "wrong_url"} <= set(d)
    assert d["wrong_url"] == "/wrong" and d["user_decisions"] <= d["decisions_total"]


def test_rule_states_replay():
    ev = lambda seq, **p: {"seq": seq, "kind": "rule_event", "payload": {"session": "s", "trader": "T", "rule_id": "R1", **p}}
    assert status_api._rule_states([ev(1, kind="verdict", state="ACCEPTED"), ev(2, kind="arm")]) == {"ARMED": 1}
    assert status_api._rule_states([ev(1, kind="verdict", state="ACCEPTED"), ev(2, kind="arm"), ev(3, kind="retire_proposed"),
                                    ev(4, kind="retire")]) == {"RETIRED": 1}
    assert status_api._rule_states([ev(1, kind="verdict", state="QUARANTINED")]) == {"QUARANTINED": 1}


def test_wrong_lists_misses_from_results_files():
    d = client.get("/api/status/wrong").json()
    suite = json.loads((ROOT / "suite_results.json").read_text(encoding="utf-8"))
    # every costly-leak cell appears with its not-accepted count, taken from the file
    leak = [s for s in suite["summaries"] if s["truth"] == "leak"]
    for s in leak:
        row = next(m for m in d["planted_misses"] if m["cell"] == s["cell"] and m["rule"] == "cap")
        assert row["k"] == s["rules"]["cap"]["accept"]["n"] - s["rules"]["cap"]["accept"]["k"]
    assert d["cohort_rejections"]["n_wallets"] == 60
    assert client.get("/wrong").status_code == 200


def test_proof_matches_court_results_and_labels_router_sets():
    d = client.get("/api/status/proof").json()
    court = json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))
    assert d["court"]["cells"] == court["cells"]
    assert d["proof_results_present"]
    labels = {s["set"]: s["label"] for s in d["router"]["sets"]}
    assert labels["blind_questions"] == "author-blind" and labels["independent_blind_2"] == "tuned-after-first-score"
    assert client.get("/proof").status_code == 200


def test_proof_baseline_is_computed_not_typed(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import proof_baseline as pb
    from engine import suite
    c = next(c for c in suite.cells() if c.name == "stationary 25% costly leak")
    null = next(c for c in suite.cells() if c.name == "stationary 25% null")
    leak_hits = sum(pb.naive_verdicts(suite.suite_trader(seed=s, **c.params))["p05"] for s in range(20))
    null_hits = sum(pb.naive_verdicts(suite.suite_trader(seed=s, **null.params))["p05"] for s in range(20))
    assert leak_hits > null_hits
    saved = json.loads((ROOT / "proof_results.json").read_text(encoding="utf-8"))["baseline"]["cells"]
    assert {r["cell"] for r in saved} >= {"stationary 25% null", "stationary 25% costly leak"}
    assert all(r["naive_p_below_0_05"]["n"] == r["sims"] for r in saved)


def test_skills_panel_from_call_log(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    monkeypatch.setattr("engine.bitget_context.CALL_LOG", log)
    from engine import bitget_context as bc
    bc.log_call(source="bitget-mcp", operation="market getTicker NVDAUSDT", ok=True, status="200", latency_ms=420, path=log)
    bc.log_call(source="bgc", operation="bgc:market tickers", ok=False, status="exit 1", latency_ms=90, path=log)
    d = client.get("/api/status/skills").json()
    by = {r["source"]: r for r in d["calls"]}
    assert by["bitget-mcp"]["freshness"] == "live" and by["bitget-mcp"]["last_latency_ms"] == 420
    assert by["bgc"]["freshness"] == "stale" and by["bgc"]["ok"] == 0
    t = d["dry_run_ticket"]
    assert t["example_payload"]["dry_run"] is True and t["example_payload"]["submitted"] is False


def test_pages_and_assets_served_with_csp_clean_scripts():
    for u in ("/static/strip.js", "/static/strip.css", "/static/pages.js", "/evidence", "/"):
        assert client.get(u).status_code == 200
    assert "/static/strip.js" in client.get("/").text
    for page in ("wrong", "proof"):
        body = (ROOT / "app" / "static" / f"{page}.html").read_text(encoding="utf-8")
        assert "onclick" not in body and body.count("<script>") == 1      # only the existing theme bootstrap block
