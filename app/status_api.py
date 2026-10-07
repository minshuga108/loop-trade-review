"""Source-status strip, public record strip, /wrong, /proof and the Skills panel.

Wire-up (one line in app/main.py):   from .status_api import router as status_router; app.include_router(status_router)

Rules this file keeps:
  - nothing here calls the network: every state is read from caches, local files or an in-process self-check;
  - every answer is cached server-side for a short time, so the strip never slows a page;
  - no key, token or header is ever returned (Qwen is reported as on/off only);
  - every number comes from a results file or the call log, never typed by hand.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from engine import bitget_context as bc

router = APIRouter()
STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[1]

_CACHE: dict[str, tuple[float, object]] = {}
_LOCK = threading.Lock()


def cached(key: str, ttl: float, fn):
    """Server-side TTL cache: a failing builder returns the last good value (or an error stub), never raises."""
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    try:
        val = fn()
    except Exception as e:                              # a status strip must never take a page down
        val = hit[1] if hit else {"error": f"{type(e).__name__}"}
    with _LOCK:
        _CACHE[key] = (now, val)
    return val


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def _read_json(name: str):
    try:
        return json.loads((ROOT / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- (a) sources
def _src(sid: str, name: str, state: str, detail: str, checked: float | None) -> dict:
    return {"id": sid, "name": name, "state": state, "detail": detail, "checked_at": _iso(checked)}


def _book(now: float) -> dict:
    from . import costs
    snaps = list(costs.CACHE.values())
    if not snaps:
        why = "refresher disabled (LOOP_NO_REFRESH)" if os.environ.get("LOOP_NO_REFRESH") else "no book fetched yet"
        return _src("book", "Bitget order-book cache", "off", why, now)
    newest = max(s.fetched_at for s in snaps)
    age = now - newest
    return _src("book", "Bitget order-book cache", "live" if age <= costs.STALE_S else "stale",
                f"{len(snaps)} symbols, newest {round(age)} s old (stale after {costs.STALE_S} s)", newest)


def _market(now: float) -> dict:
    st = bc.status()
    lp = bc.CACHE.last_pass
    answering = [s for s in st["sources"] if s["state"] == "answering"]
    if lp is None:
        return _src("market", "Bitget public market calls", "off", f"refresher {st['refresher']}; no pass yet", now)
    age = now - lp
    state = "live" if answering and age <= bc.STALE_S else "stale"
    return _src("market", "Bitget public market calls", state,
                f"{len(answering)} of {len(st['sources'])} tool paths answering, last pass {round(age)} s ago", lp)


def _market_public(now: float) -> list[dict]:
    from . import market_data as md
    out = []
    for e in md.probe_status()["endpoints"]:
        state = "live" if e["tier"] in ("answering", "changed an answer") else "off"
        detail = (f"{e['tier']}: {e['attempted']} tried, {e['reachable']} reached, {e['answering']} answered, {e['changed_answer']} changed an answer; "
                  f"{md.PROVENANCE}; GET {e['path']}")
        out.append(_src("mkt_" + e["id"], "Bitget public " + e["name"].lower(), state, detail, now))
    return out


def _importers(now: float) -> list[dict]:
    from adapters import bitget_uta
    from . import importer
    out = []
    try:
        rows = bitget_uta.parse_fills({"code": "00000", "data": {"list": None}}, "selfcheck")
        out.append(_src("uta", "UTA importer (Bitget API fills)", "live", f"self-check parsed an empty page ({len(rows)} fills); offline parser", now))
    except Exception as e:
        out.append(_src("uta", "UTA importer (Bitget API fills)", "off", f"self-check failed: {type(e).__name__}", now))
    try:
        k = importer.detect("Date,Order ID,Direction,Futures,Filled\n")
        out.append(_src("csv", "CSV importer (Bitget export, Hyperliquid fills)", "live", f"self-check recognised layout {k}; in memory, nothing stored", now))
    except Exception as e:
        out.append(_src("csv", "CSV importer (Bitget export, Hyperliquid fills)", "off", f"self-check failed: {type(e).__name__}", now))
    return out


def _mcp(now: float) -> dict:
    from . import mcp_server
    try:
        res, _ = mcp_server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "status-check")
        n = len(res["result"]["tools"])
        return _src("mcp", "Loop MCP server (read-only)", "live" if n else "off", f"{n} tools listed by an in-process tools/list", now)
    except Exception as e:
        return _src("mcp", "Loop MCP server (read-only)", "off", f"tools/list failed: {type(e).__name__}", now)


def _qwen(now: float) -> dict:
    from . import llm
    if not llm.enabled():
        return _src("qwen", "Qwen intent helper", "off", "no key set; the template path answers", now)
    return _src("qwen", "Qwen intent helper", "live", f"on (key configured, not pinged here); daily cap {llm.DAILY_CAP} calls", now)


def _chain(now: float) -> dict:
    from . import record_api
    v = record_api.get_log().verify()
    if v.get("intact"):
        return _src("chain", "Hash chain verify", "live", f"{v['entries']} entries, every link and hash checks out", now)
    return _src("chain", "Hash chain verify", "broken", f"first bad entry {v.get('first_bad_seq')}: {v.get('reason')}", now)


def sources() -> dict:
    def build():
        now = time.time()
        rows = [_book(now), _market(now), *_market_public(now), *_importers(now), _mcp(now), _qwen(now), _chain(now)]
        return {"generated_at": _iso(now), "cache_ttl_s": 30, "sources": rows,
                "note": "Read from caches and in-process self-checks. No network call is made when this loads."}
    return cached("sources", 30, build)


# ---------------------------------------------------------------- (b) record strip
def _rule_states(entries: list[dict]) -> dict:
    """Latest state per (session, trader, rule): the record's own rule_event stream, replayed."""
    st: dict[tuple, str] = {}
    for e in entries:
        if e["kind"] != "rule_event":
            continue
        p = e["payload"]
        k = (p.get("session"), p.get("trader"), p.get("rule_id"))
        kind = p.get("kind")
        if kind == "verdict":
            st[k] = p.get("state", "?")
        elif kind == "arm" or kind == "keep":
            st[k] = "ARMED"
        elif kind == "retire_proposed":
            st[k] = "PENDING_RETIREMENT"
        elif kind == "retire":
            st[k] = "RETIRED"
    out: dict[str, int] = {}
    for v in st.values():
        out[v] = out.get(v, 0) + 1
    return out


def record_strip() -> dict:
    def build():
        from engine.record import read_entries_safe
        from . import record_api
        log = record_api.get_log()
        c = log.counter()
        es, _bad = read_entries_safe(log.path)
        rs = _rule_states(es)
        by = c.get("by_origin", {})
        user = by.get("user", 0)
        other = {k: v for k, v in by.items() if k != "user"}
        return {"generated_at": _iso(time.time()), "decisions_total": c["decisions_logged"], "user_decisions": user,
                "not_user": other, "outcomes_resolved": c["outcomes_resolved"], "pending": c["pending"],
                "rules_armed": rs.get("ARMED", 0) + rs.get("PENDING_RETIREMENT", 0), "rules_retired": rs.get("RETIRED", 0),
                "rules_rejected": rs.get("QUARANTINED", 0), "rules_underpowered": rs.get("UNDERPOWERED", 0),
                "days_running": c["days_running"], "head": c["head"], "wrong_url": "/wrong",
                "note": "User = a history the visitor imported themselves. Sandbox, judge and test traffic is counted apart and "
                        "is not the record. Rule events carry no origin tag, so rule counts include all sessions."}
    return cached("record", 20, build)


# ---------------------------------------------------------------- (c) /wrong
def wrong() -> dict:
    def build():
        from engine.record import read_entries_safe
        from . import record_api
        es, _ = read_entries_safe(record_api.get_log().path)
        events = []
        for e in es:
            p = e["payload"]
            if e["kind"] != "rule_event":
                continue
            if (p.get("kind") == "verdict" and p.get("state") in ("QUARANTINED", "UNDERPOWERED")) or p.get("kind") in ("retire_proposed", "retire"):
                events.append({"seq": e["seq"], "at": _iso(e["ts_ms"] / 1000), "trader": p.get("trader"), "rule_id": p.get("rule_id"),
                               "event": {"QUARANTINED": "rejected by the court", "UNDERPOWERED": "not enough trades to judge"}.get(p.get("state"), p.get("kind")),
                               "reason": p.get("reason", "")})
        suite = _read_json("suite_results.json") or {"summaries": []}
        planted = []
        for s in suite["summaries"]:
            if s["scenario"] == "LOOKAHEAD":
                for key, r in s["rules"].items():
                    if key != "honest_cap" and r["accepted"]["k"] > 0:
                        planted.append({"cell": s["cell"], "what": f"look-ahead rule '{key}' was accepted", **_r(r["accepted"])})
                continue
            for rule, r in s["rules"].items():
                if s["truth"] == "null" and r["accept"]["k"] > 0:
                    planted.append({"cell": s["cell"], "rule": rule, "what": "wrong acceptance: nothing was there", **_r(r["accept"])})
                elif s["truth"] == "leak":
                    miss = r["accept"]["n"] - r["accept"]["k"]
                    planted.append({"cell": s["cell"], "rule": rule, "what": "real leak not accepted (missed or underpowered)",
                                    "k": miss, "n": r["accept"]["n"], "rate": miss / r["accept"]["n"], "underpowered": r["under"]["rate"]})
                elif s["truth"] == "decay" and r["retire"]["n"] - r["retire"]["k"] > 0:
                    planted.append({"cell": s["cell"], "rule": rule, "what": "faded leak not retired by the decay check",
                                    "k": r["retire"]["n"] - r["retire"]["k"], "n": r["retire"]["n"], "rate": 1 - r["retire"]["rate"]})
        court = _read_json("court_results.json") or {"cells": []}
        bar = court.get("threshold_per_rule")
        above = [{"cell": f"{c['scenario']} at {c['trips']} trips", "rate": c["accepted"], "ci": c["accepted_ci"], "bar": bar}
                 for c in court["cells"] if c["scenario"] != "costly_leak" and bar is not None and c["accepted"] > bar]
        cohort = _read_json("cohort_results.json") or {}
        cc = cohort.get("court", {})
        proof = _read_json("proof_results.json") or {"router": {"sets": []}}
        return {"generated_at": _iso(time.time()), "record_events": events, "planted_misses": planted, "court_above_bar": above,
                "cohort_rejections": {"per_rule": cc.get("per_rule"), "trials": cc.get("cohort_trials"), "alpha_per_rule": cc.get("alpha_per_rule"),
                                      "wallets_with_any_accepted": cc.get("wallets_with_any_accepted"), "n_wallets": cohort.get("n_wallets")} if cc else None,
                "router": [{"set": s["set"], "label": s["label"], "why": s["why"], "n": s["n"], "correct_now": s["correct_now"],
                            "first_score": s.get("first_score"), "misses": s["misses"]} for s in proof["router"]["sets"]],
                "sources": ["court_results.json", "suite_results.json", "cohort_results.json", "proof_results.json", "the public record log"]}
    return cached("wrong", 60, build)


def _r(d: dict) -> dict:
    return {"k": d["k"], "n": d["n"], "rate": d["rate"], "ci": [d["lo"], d["hi"]]}


# ---------------------------------------------------------------- (d) /proof
def proof() -> dict:
    def build():
        court = _read_json("court_results.json") or {"cells": []}
        cohort = _read_json("cohort_results.json") or {}
        pr = _read_json("proof_results.json")
        cc = cohort.get("court", {})
        return {"generated_at": _iso(time.time()),
                "court": {"sims_per_cell": court.get("sims_per_cell"), "threshold_per_rule": court.get("threshold_per_rule"),
                          "cells": court["cells"], "file": "court_results.json"},
                "cohort": {"n_wallets": cohort.get("n_wallets"), "provenance": cohort.get("provenance"), "court": cc,
                           "file": "cohort_results.json"} if cohort else None,
                "router": (pr or {}).get("router"), "baseline": (pr or {}).get("baseline"),
                "proof_results_present": pr is not None}
    return cached("proof", 60, build)


# ---------------------------------------------------------------- (e) skills panel
STALE_CALL_S = 3 * 3600


def skills() -> dict:
    def build():
        rows = bc.read_call_log()
        now = time.time()
        by: dict[tuple, list[dict]] = {}
        for r in rows:
            by.setdefault((r.get("source"), r.get("origin"), r.get("operation")), []).append(r)
        out = []
        for (src, origin, op), rs in by.items():
            last = rs[-1]
            try:
                age = now - datetime.fromisoformat(last["at"]).timestamp()
            except (KeyError, ValueError):
                age = None
            lat = [x["latency_ms"] for x in rs if isinstance(x.get("latency_ms"), int)]
            out.append({"source": src, "origin": origin, "operation": op, "calls": len(rs), "ok": sum(bool(x.get("ok")) for x in rs),
                        "last_status": last.get("status"), "last_ok": bool(last.get("ok")), "last_at": last.get("at"),
                        "last_latency_ms": last.get("latency_ms"), "median_latency_ms": sorted(lat)[len(lat) // 2] if lat else None,
                        "freshness": "live" if (last.get("ok") and age is not None and age <= STALE_CALL_S) else "stale"})
        out.sort(key=lambda r: (str(r["origin"]), str(r["source"]), str(r["operation"])))
        return {"generated_at": _iso(now), "calls": out, "log_rows": len(rows), "stale_after_s": STALE_CALL_S,
                "dry_run_ticket": DRY_RUN_TICKET, "public_market_probes": _public_probes(),
                "note": "Read from the existing call log. 'live' = the last call answered within 3 hours; 'stale' = older or failed. "
                        "Nothing here was fetched when you opened the page."}
    return cached("skills", 30, build)


def _public_probes() -> dict:
    from . import market_data as md
    return md.probe_status()


DRY_RUN_TICKET = {
    "what": "The Rule Gate's order-ticket preview is a dry-run payload only. It reads an idea such as 'buy 5000 RNVDA', checks it "
            "against your armed rules and a cached book cost line, and returns a verdict. Loop has no order path and holds no trading key.",
    "example_payload": {"dry_run": True, "submitted": False, "paper_only": True,
                        "idea": {"side": "buy", "symbol": "RNVDAUSDT", "notional": 5000.0},
                        "state": "CLEAR | BLOCKED_BY_YOUR_RULES", "broken_rules": [], "check_line": "cost from the cached public book"},
    "not_included": ["no signature", "no API key", "no order endpoint call", "no demo-order proof (that needs the owner's Agent Hub key)"],
}


# ---------------------------------------------------------------- routes
@router.get("/api/status/sources")
def api_sources():
    return sources()


@router.get("/api/status/record")
def api_record():
    return record_strip()


@router.get("/api/status/wrong")
def api_wrong():
    return wrong()


@router.get("/api/status/proof")
def api_proof():
    return proof()


@router.get("/api/status/skills")
def api_skills():
    return skills()


@router.get("/wrong", include_in_schema=False)
def wrong_page():
    return FileResponse(STATIC / "wrong.html")


@router.get("/proof", include_in_schema=False)
def proof_page():
    return FileResponse(STATIC / "proof.html")
