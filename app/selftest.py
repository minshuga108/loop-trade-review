"""Selftest: 24 fixed review sentences run against the in-process chat and router.

The sentences and their gold intents live in eval/selftest_prompts.jsonl and were
committed before the first run. The first run is frozen in
eval/selftest_first_run.json (scripts/selftest_freeze.py writes it once and never
overwrites it), so its misses stay visible after any later fix.

Nothing here calls the network: chat.answer runs on the template path unless
QWEN_API_KEY is set on the server, and the cold-visit check fetches '/' in-process.
"""
from __future__ import annotations

import json
import re
import secrets
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import chat, llm, router, service

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "eval" / "selftest_prompts.jsonl"
FIRST_RUN = ROOT / "eval" / "selftest_first_run.json"

BUDGET_RESPONSE_MS = 1500          # first byte budget for the deployed URL (in-process this is the full response)
BUDGET_BYTES = 1_000_000           # first-screen weight: HTML plus the same-origin scripts and styles it loads
COOLDOWN_S = 60                    # a finished run is reused for this long instead of starting another


def load_prompts() -> list[dict]:
    with open(PROMPTS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def pick_trader() -> str:
    """Wallet B when its sample file is shipped, else the simulated trader F (always present)."""
    b = next(t for t in service.TRADERS if t["id"] == "B")
    return "B" if (service.SAMPLES / b["file"]).exists() else "F"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def run_prompts(tid: str | None = None, progress: Callable[[int, int], None] | None = None) -> dict:
    prompts = load_prompts()
    tid = tid or pick_trader()
    sid = "selftest-" + secrets.token_hex(4)            # its own sandbox, never a visitor's
    got: dict[str, str | None] = {}
    rows = []
    for i, p in enumerate(prompts):
        hist = [{"intent": got[p["after"]]}] if p.get("after") and got.get(p["after"]) else []
        prev = hist[-1]["intent"] if hist else None
        t0 = time.perf_counter()
        r_intent, r_flags = router.route_ex(p["text"], prev)
        router_ms = (time.perf_counter() - t0) * 1000
        err, a = None, None
        t0 = time.perf_counter()
        try:
            a = chat.answer(tid, p["text"], hist, sid)
        except Exception as e:                            # an unhandled error is a failure, shown as such
            err = f"{type(e).__name__}: {e}"[:200]
        chat_ms = (time.perf_counter() - t0) * 1000
        c_intent = a["intent"] if a else None
        got[p["id"]] = c_intent
        preview = ""
        if a:
            preview = (a.get("text") or a.get("markdown") or "")[:180]
        rows.append({
            "id": p["id"], "lang": p["lang"], "kind": p["kind"], "text": p["text"], "after": p.get("after"),
            "previous_intent": prev, "gold": p["gold"], "router_intent": r_intent, "router_flags": r_flags,
            "chat_intent": c_intent, "pass": err is None and c_intent == p["gold"], "error": err,
            "number_lock": a.get("number_lock") if a else None, "router_ms": round(router_ms, 2),
            "chat_ms": round(chat_ms, 1), "answer_preview": preview,
        })
        if progress:
            progress(i + 1, len(prompts))
    return {"trader": tid, "llm": llm.label(), "finished_at": _now(), "rows": rows, "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    def slice_(pred):
        sub = [r for r in rows if pred(r)]
        return {"n": len(sub), "passed": sum(r["pass"] for r in sub)}
    kinds = sorted({k for r in rows for k in r["kind"]})
    chat_ms = [r["chat_ms"] for r in rows]
    return {
        "n": len(rows), "passed": sum(r["pass"] for r in rows),
        "router_agrees_with_gold": sum(r["router_intent"] == r["gold"] for r in rows),
        "errors": sum(r["error"] is not None for r in rows),
        "number_lock_refusals": sum(bool(r["number_lock"]) and r["number_lock"] != "passed" for r in rows),
        "by_lang": {lg: slice_(lambda r, lg=lg: r["lang"] == lg) for lg in sorted({r["lang"] for r in rows})},
        "by_kind": {k: slice_(lambda r, k=k: k in r["kind"]) for k in kinds},
        "misses": [r["id"] for r in rows if not r["pass"]],
        "chat_ms": {"p50": _pct(chat_ms, 0.5), "p95": _pct(chat_ms, 0.95), "max": round(max(chat_ms), 1) if chat_ms else None},
        "router_ms": {"p50": _pct([r["router_ms"] for r in rows], 0.5)},
    }


_ASSET_RX = re.compile(r"""<(?:script[^>]+src|link[^>]+href)\s*=\s*["']([^"']+)["']""", re.I)


def same_origin_assets(html: str) -> list[str]:
    out = []
    for u in _ASSET_RX.findall(html):
        if u.startswith("/") and not u.startswith("//") and u not in out:
            out.append(u)
    return out


def cold_visit_inprocess(app) -> dict:
    """Fetch '/' like a first visit (fresh client, no cookies), in-process: no network is involved.

    In-process the whole response is buffered, so the time is the full server response, an upper
    bound on first byte without network latency. The deployed check is scripts/cold_visit.py.
    """
    from fastapi.testclient import TestClient

    c = TestClient(app)
    t0 = time.perf_counter()
    r = c.get("/")
    ms = (time.perf_counter() - t0) * 1000
    html_bytes = len(r.content)
    assets = []
    for u in same_origin_assets(r.text):
        a = c.get(u)
        assets.append({"path": u, "status": a.status_code, "bytes": len(a.content)})
    total = html_bytes + sum(a["bytes"] for a in assets)
    h = c.get("/api/health")
    health_ok = h.status_code == 200 and h.json().get("ok") is True
    no_login = r.status_code == 200 and not r.history and 'type="password"' not in r.text.lower()
    checks = [
        {"check": "server response time for '/' (in-process)", "value_ms": round(ms, 1), "budget_ms": BUDGET_RESPONSE_MS, "pass": ms <= BUDGET_RESPONSE_MS},
        {"check": "first-screen weight, HTML plus same-origin JS and CSS", "value_bytes": total, "budget_bytes": BUDGET_BYTES, "pass": total <= BUDGET_BYTES},
        {"check": "loads with no cookie, login or key", "pass": no_login},
        {"check": "/api/health says ok", "pass": health_ok},
    ]
    return {"status": r.status_code, "html_bytes": html_bytes, "assets": assets, "total_bytes": total,
            "response_ms": round(ms, 1), "checks": checks, "pass": all(x["pass"] for x in checks),
            "note": "In-process: no network, so this is the server's own time. Run scripts/cold_visit.py against the deployed URL for the real first byte."}


# ---------------------------------------------------------------- background run state
_LOCK = threading.Lock()
_STATE: dict = {"state": "idle", "done": 0, "total": 0, "started_at": None, "result": None, "finished_ts": 0.0, "error": None}


def snapshot(cached: bool = False) -> dict:
    with _LOCK:
        s = dict(_STATE)
    s.pop("finished_ts", None)
    s["cached"] = cached
    return s


def _job(app, tid: str | None) -> None:
    def prog(done, total):
        with _LOCK:
            _STATE["done"], _STATE["total"] = done, total
    try:
        res = run_prompts(tid, prog)
        res["cold_visit"] = cold_visit_inprocess(app)
        with _LOCK:
            _STATE.update(state="done", result=res, finished_ts=time.time(), error=None)
    except Exception as e:
        with _LOCK:
            _STATE.update(state="error", error=f"{type(e).__name__}: {e}"[:300], finished_ts=time.time())


def start(app, wait: bool = False, tid: str | None = None) -> dict:
    """Start a run unless one is running or one finished in the last COOLDOWN_S seconds."""
    with _LOCK:
        if _STATE["state"] == "running":
            busy = True
        else:
            busy = False
            if _STATE["state"] == "done" and time.time() - _STATE["finished_ts"] < COOLDOWN_S:
                fresh = True
            else:
                fresh = False
                _STATE.update(state="running", done=0, total=len(load_prompts()), started_at=_now(), error=None)
    if busy:
        return snapshot()
    if fresh:
        return snapshot(cached=True)
    if wait:
        _job(app, tid)
    else:
        threading.Thread(target=_job, args=(app, tid), daemon=True, name="selftest").start()
    return snapshot()


def first_run() -> dict | None:
    if not FIRST_RUN.exists():
        return None
    return json.loads(FIRST_RUN.read_text(encoding="utf-8"))
