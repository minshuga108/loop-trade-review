"""Public forward record: page + JSON endpoints + the hooks service.py calls.

Wire-up (owner, in app/main.py):   from .record_api import router as record_router; app.include_router(record_router)
Hooks (owner, in app/service.py):
    gate_check(...)  -> after building `out`:   record_api.log_gate_decision(sid, tid, out)
    propose_rule / transition -> after the change: record_api.log_rule_event(sid, tid, rb.log[-1])
Logging must never break the product, so the hooks swallow and report errors.
"""
from __future__ import annotations

import functools
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as FPath
from fastapi.responses import FileResponse

from engine import anchor
from engine.record import RecordLog, default_path, utc_day

router = APIRouter()
STATIC = Path(__file__).parent / "static"
_LOGS: dict[str, RecordLog] = {}
_LOCK = threading.Lock()


def get_log() -> RecordLog:
    """One RecordLog per path (LOOP_RECORD_PATH is read at call time so tests can point elsewhere)."""
    p = str(default_path())
    with _LOCK:
        if p not in _LOGS:
            _LOGS[p] = RecordLog(p)
        return _LOGS[p]


_TEST_PREFIXES = ("test", "pytest", "selftest", "probe", "qa", "load", "stress", "ci")
_JUDGE_PREFIXES = ("judge", "demo", "review")


def classify_origin(sid: str, tid: str, is_import: bool = False) -> str:
    """Who made this decision: test / judge traffic by session name, user = a wallet the visitor imported
    themselves, sandbox = a click on a shipped demo wallet. Only "user" counts as the record."""
    s = (sid or "").lower()
    if s.startswith(_TEST_PREFIXES):
        return "test"
    if s.startswith(_JUDGE_PREFIXES):
        return "judge"
    return "user" if is_import else "sandbox"


def log_gate_decision(sid: str, tid: str, result: dict, rule_versions: dict | None = None, origin: str | None = None) -> dict | None:
    """Write a Rule Gate decision the moment it is made, before any outcome exists."""
    try:
        log = get_log()
        idea = result.get("idea") or {}
        return log.log_decision({
            "session": log.session_hash(sid), "trader": tid,
            "idea": {"side": idea.get("side"), "symbol": idea.get("symbol"), "notional": idea.get("notional")},
            "state": result.get("state"), "broken_rules": result.get("broken_rules", []),
            "evidence": result.get("evidence", []), "last_trade_was_loss": result.get("last_trade_was_loss"),
            "rule_versions": rule_versions or {}, "scenario": result.get("scenario") or [], "paper_only": True, "origin": origin or classify_origin(sid, tid),
        })
    except Exception as e:                       # never let the record break the gate
        return {"error": f"{type(e).__name__}: {e}"}


def log_rule_event(sid: str, tid: str, event: dict) -> dict | None:
    """Write a rulebook state change (pass a Rulebook.log entry). Its own chain hash is kept as a cross-link."""
    try:
        log = get_log()
        keep = {k: v for k, v in event.items() if k not in ("at_ms",)}
        keep["rulebook_hash"] = keep.pop("hash", None)
        keep["rulebook_prev"] = keep.pop("prev", None)
        return log.log_rule_event({"session": log.session_hash(sid), "trader": tid, **keep})
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def log_outcome(decision_seq: int, outcome: dict) -> dict:
    """Resolve a decision later. Raises RecordError if it is unknown or already resolved."""
    return get_log().log_outcome(decision_seq, outcome)


# ---- routes ----------------------------------------------------------------------------------
@router.get("/record")
def record_page():
    return FileResponse(STATIC / "record.html")


def _guard(fn):
    """A record that cannot be opened (read-only disk, a path that is a file) answers 503 with the reason, not 500."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except OSError as e:
            raise HTTPException(503, f"The public record is unavailable on this server ({type(e).__name__}). "
                                     "The review, chat and gate still work; decisions are not being recorded.") from None
    return wrapper


@router.get("/api/record/entries")
@_guard
def entries(limit: int = Query(20, ge=1, le=200)):
    return {"entries": get_log().tail(limit)}


@router.get("/api/record/verify")
@_guard
def verify():
    return get_log().verify()


@router.get("/api/record/counter")
@_guard
def counter_():
    log = get_log()
    c = log.counter()
    rec = anchor.latest_receipt()
    a = None
    if rec:
        v = anchor.verify_anchor(rec["root"], rec)
        today_root = log.day_root(rec["day"])["root"] if rec.get("day") else None
        a = {"day": rec.get("day"), "root": rec["root"], "receipt_ok": v["ok"], "matches_log": today_root == rec["root"],
             "bitcoin_blocks": [b["height"] for b in v["bitcoin"]], "pending_calendars": len(v["pending"]), "proves": v["proves"]}
    return {**c, "today": utc_day(log.clock()), "last_anchor": a}


@router.get("/api/record/day/{day}")
@_guard
def day(day: str = FPath(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    return get_log().day_root(day)
