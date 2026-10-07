"""Daily frozen-prediction board: hash-chained, append-only runs, read-only page and API.

Live files (data/runs/runs.jsonl, scores.jsonl) are ephemeral on a free Render disk, so the shipped seed files in
deploy_data/ are merged underneath them. The chain is: entry.prev == hash of the previous entry; the live file continues
the seed (live entries already in the seed are skipped by hash). Nothing here writes; scripts/freeze_daily.py and
scripts/score_runs.py append. A break in the chain is reported, never hidden or repaired.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / "static"
GENESIS = "0" * 64
COMPONENTS = ("rule", "reproduce", "cost")
DAY_S = 86400

router = APIRouter()


def live_dir() -> Path:
    return Path(os.environ.get("LOOP_RUNS_DIR") or ROOT / "data" / "runs")


def seed_dir() -> Path:
    return Path(os.environ.get("LOOP_RUNS_SEED_DIR") or ROOT / "deploy_data")


def entry_hash(e: dict) -> str:
    body = {k: v for k, v in e.items() if k not in ("hash", "source", "chain_ok")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _read(p: Path) -> list[dict]:
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({"_bad": line[:80]})
    except OSError:
        pass
    return out


def load_chain() -> dict:
    """Seed then live, deduplicated by hash, verified link by link. Entries after a break are still listed, flagged."""
    seen, merged = set(), []
    for src, p in (("seed", seed_dir() / "runs_seed.jsonl"), ("live", live_dir() / "runs.jsonl")):
        for e in _read(p):
            h = e.get("hash")
            if "_bad" in e or not h or h in seen:
                continue
            seen.add(h)
            merged.append({**e, "source": src})
    prev, broken_at = GENESIS, None
    for i, e in enumerate(merged, 1):
        ok = e.get("prev") == prev and entry_hash(e) == e["hash"] and e.get("seq") == i
        e["chain_ok"] = bool(ok and broken_at is None)
        if not ok and broken_at is None:
            broken_at = e.get("seq", i)
        prev = e["hash"]
    return {"entries": merged, "tip": merged[-1]["hash"] if merged else GENESIS, "ok": broken_at is None, "broken_at": broken_at}


def load_scores() -> dict:
    """{(run_hash, component): first final record}. A final score is never replaced."""
    out = {}
    for p in (seed_dir() / "runs_scores_seed.jsonl", live_dir() / "scores.jsonl"):
        for s in _read(p):
            k = (s.get("run_hash"), s.get("component"))
            if s.get("state") in ("scored", "missed") and k not in out:
                out[k] = s
    return out


def entry_state(comps: dict) -> str:
    st = [c["state"] for c in comps.values()]
    return "missed" if "missed" in st else "scored" if "scored" in st else "pending"


def view(now: float | None = None) -> dict:
    now = now or time.time()
    ch = load_chain()
    scores = load_scores()
    rows = []
    for e in ch["entries"]:
        comps = {}
        for c in COMPONENTS:
            s = scores.get((e["hash"], c))
            comps[c] = ({"state": s["state"], "basis": s.get("basis"), "detail": s.get("detail"), "scored_at": s.get("scored_at")} if s
                        else {"state": "pending", "basis": None,
                              "detail": "not scored yet" if now - e["ts"] < DAY_S else "outcome not yet knowable", "scored_at": None})
        rows.append({**{k: e.get(k) for k in ("seq", "ts", "day", "trader", "prev", "hash", "source", "chain_ok", "predictions")},
                     "state": entry_state(comps), "components": comps, "age_h": round((now - e["ts"]) / 3600, 1)})
    counts = {s: sum(r["state"] == s for r in rows) for s in ("pending", "scored", "missed")}
    return {"entries": rows[::-1], "n": len(rows), "counts": counts, "chain_ok": ch["ok"], "broken_at": ch["broken_at"], "tip": ch["tip"],
            "read_only": True,
            "labels": {"rule": "live data: trades opened after the freeze", "reproduce": "replay: engine recomputed on the frozen day",
                       "cost": "live data: Bitget order book now"},
            "note": "Append-only and hash-chained. Misses stay visible. Pending means the outcome is not yet knowable; nothing is filled in."}


@router.get("/api/runs")
def api_runs():
    return view()


@router.get("/runs", include_in_schema=False)
def runs_page():
    return FileResponse(STATIC / "runs.html")
