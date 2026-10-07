"""'Your trading thesis': page, JSON API, freeze (tagged rule_event in the hash-chained record) and forward/replay score.

Sandbox-safe: freezing writes one record entry and arms nothing. The replay score is deterministic, built from
the first 70% of the trader's own history and scored on the held-back 30%; it is labelled replay, never live.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from engine import thesis as T
from engine.record import utc_day

from . import record_api, service

router = APIRouter()
STATIC = Path(__file__).parent / "static"
TAG = "thesis"
REPLAY_HEAD = 0.7
_LOCK = threading.Lock()
_REPLAY: dict = {}


def _frozen(tid: str, sid: str) -> list[dict]:
    """This session's frozen theses for a trader, oldest first, read back from the public record."""
    log = record_api.get_log()
    sh = log.session_hash(sid)
    out = []
    for e in log.entries():
        p = e["payload"]
        if e["kind"] == "rule_event" and p.get("tag") == TAG and p.get("trader") == tid and p.get("session") == sh:
            out.append({"seq": e["seq"], "version": p["version"], "hash": p["thesis_hash"], "date": p["date"], "key": p["key"],
                        "prediction": p["prediction"], "entry_hash": e["hash"]})
    return out


def build(tid: str, sid: str = "default", day: str | None = None) -> dict:
    review = service.review(tid)                        # StopIteration for an unknown trader
    trips = service._load(tid)[3]
    facts = T.build_facts(review, trips)
    day = day or utc_day(int(time.time() * 1000))
    h = T.thesis_hash(facts, day)
    try:
        frozen = _frozen(tid, sid)
        rec_err = None
    except OSError as e:
        frozen, rec_err = [], f"record unavailable ({type(e).__name__})"
    key = T.key_of(facts)
    d = T.diff(frozen[0]["key"], key, len(frozen) + 1) if frozen else []
    return {"trader": tid, "label": review["trader"]["label"], "provenance": review["trader"]["provenance"], "date": day,
            "facts": facts, "text": T.render(facts), "hash": h, "key": key,
            "frozen": [{k: v for k, v in f.items() if k not in ("key", "prediction")} for f in frozen],
            "next_version": len(frozen) + 1, "diff": d, "record_error": rec_err, "read_only": True,
            "note": "Assembled only from engine facts; underpowered cases say so. It places no order and arms no rule."}


def freeze(tid: str, sid: str = "default") -> dict:
    t = build(tid, sid)
    trips = service._load(tid)[3]
    if t["frozen"] and t["frozen"][-1]["hash"] == t["hash"]:
        return {**t, "already_frozen": True, "frozen_now": None}
    ev = {"kind": "thesis_freeze", "rule_id": "thesis", "tag": TAG, "version": t["next_version"], "thesis_hash": t["hash"],
          "date": t["date"], "key": t["key"], "prediction": T.prediction_of(t["facts"], trips),
          "origin": record_api.classify_origin(sid, tid, tid in service._DYN), "paper_only": True}
    entry = record_api.log_rule_event(sid, tid, ev)
    if not entry or entry.get("error"):
        return {**t, "already_frozen": False, "frozen_now": None, "record_error": (entry or {}).get("error", "not recorded")}
    return {**build(tid, sid), "already_frozen": False, "frozen_now": {"seq": entry["seq"], "version": ev["version"], "hash": ev["thesis_hash"]}}


def _replay_prediction(tid: str):
    trips = sorted(service._load(tid)[3], key=lambda t: t.t_open_ms)
    cut = int(len(trips) * REPLAY_HEAD)
    head, tail = trips[:cut], trips[cut:]
    key = (tid, len(trips))
    with _LOCK:
        hit = _REPLAY.get(key)
        if hit is None:
            if len(head) < 10:
                hit = (None, None)
            else:
                rk = "R_" + tid
                meta = {"id": rk, "file": None, "role": "replay", "blurb": "replay head"}
                with service._RC_LOCK:
                    service._DYN[rk] = (meta, [], [], head)
                try:
                    rv = service._review_uncached(rk)
                finally:
                    with service._RC_LOCK:
                        service._DYN.pop(rk, None)
                facts = T.build_facts(rv, head)
                hit = (facts, T.prediction_of(facts, head))
            _REPLAY[key] = hit
    return hit, head, tail, trips


def score(tid: str, sid: str = "default", mode: str = "auto") -> dict:
    service.review(tid)
    trips = service._load(tid)[3]
    frozen = _frozen(tid, sid) if mode != "replay" else []
    if frozen and mode in ("auto", "forward"):
        f = frozen[-1]
        sc = T.score(f["prediction"], trips)
        if sc["n_new"] > 0 or mode == "forward":
            return {"trader": tid, "mode": "forward", "frozen_version": f["version"], "frozen_hash": f["hash"], "score": sc,
                    "summary": T.score_lines(sc, "forward"), "live": True}
    (facts, pred), head, tail, _ = _replay_prediction(tid)
    base = {"trader": tid, "mode": "replay", "live": False, "head_trips": len(head), "tail_trips": len(tail),
            "note": "Replay: the thesis is rebuilt from the first 70% of this trader's own history and scored on the held-back last 30%. Deterministic demo, not live."}
    if pred is None:
        sc = {"n_new": len(tail), "n_new_after_loss": 0, "n_touched": 0, "effect": 0, "size_ratio_new": None, "size_ratio_frozen": None,
              "testable": False, "habit": "NOT_TESTABLE", "rule": "NOT_TESTABLE"}
    else:
        sc = T.score(pred, trips)
    return {**base, "score": sc, "summary": T.score_lines(sc, "replay"), "prediction": pred,
            "head_thesis": None if facts is None else T.render(facts)}


# ---- routes ------------------------------------------------------------------------------------
def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except StopIteration:
        raise HTTPException(404, "unknown trader") from None
    except service.DataMissing as e:
        raise HTTPException(503, str(e)) from None


@router.get("/thesis/{tid}", include_in_schema=False)
def thesis_page(tid: str):
    return FileResponse(STATIC / "thesis.html")


@router.get("/api/thesis/{tid}")
def api_thesis(tid: str, x_session: str = Header(default="default")):
    return _call(build, tid, x_session)


@router.post("/api/thesis/{tid}/freeze")
def api_freeze(tid: str, x_session: str = Header(default="default")):
    return _call(freeze, tid, x_session)


@router.get("/api/thesis/{tid}/score")
def api_score(tid: str, mode: str = "auto", x_session: str = Header(default="default")):
    if mode not in ("auto", "replay", "forward"):
        raise HTTPException(400, "mode must be auto, replay or forward")
    return _call(score, tid, x_session, mode)
