"""Bitget tool evidence: which Bitget AI tools answered, and how many Bitget operations the product called.

Wire in with:  from .evidence_api import router as evidence_router; app.include_router(evidence_router)

Everything is derived at request time from files on disk:
  - evidence/bitget_tools_<UTC>.json, written by scripts/probe_bitget_tools.py (newest one wins)
  - the call log engine/bitget_context.CALL_LOG (JSONL, one row per outbound call)
  - the in-memory cache of engine/bitget_context (never fetched on the request path)
No number on /evidence is typed by hand.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from engine import bitget_context as bc

router = APIRouter()
STATIC = Path(__file__).parent / "static"
EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"
_NAME = re.compile(r"^bitget_tools_\d{8}T\d{6}Z\.json$")

PATH_LABEL = {
    "bgc": "Agent Hub CLI bgc (@bitget-ai/bitget-agent-cli 3.0.0)",
    "bitget-mcp": "bitget-mcp-server, agent.bitget.com/mcp",
    "bitget-signal": "bitget-signal research skills (npm @bitget-ai/bitget-signal 1.2.0)",
}


def latest_evidence(folder: Path | None = None) -> tuple[Path | None, dict | None]:
    d = folder or EVIDENCE
    files = sorted(p for p in d.glob("bitget_tools_*.json") if _NAME.match(p.name)) if d.exists() else []
    if not files:
        return None, None
    try:
        return files[-1], json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return files[-1], None


def summarize_probe(doc: dict) -> dict:
    """Per tool path: which operations answered and which did not, with the probe's own verdicts."""
    paths: dict[str, dict] = {}
    for r in doc.get("calls", []):
        p = paths.setdefault(r["path"], {"path": r["path"], "label": PATH_LABEL.get(r["path"], r["path"]),
                                         "answered": [], "not_answered": [], "calls": 0})
        p["calls"] += 1
        item = {"operation": f'{r["tool"]}: {r["operation"]}', "status": r.get("status"), "latency_ms": r.get("latency_ms"),
                "verdict": r.get("verdict"), "note": r.get("note", "")}
        (p["answered"] if r.get("verdict") == "answers" else p["not_answered"]).append(item)
    for p in paths.values():
        # a path "answers" only if a DATA call answered, not just the handshake or the tool list
        data_ok = [a for a in p["answered"] if not re.search(r"initialize|tools/list|discover|guide", a["operation"])]
        p["data_calls_answered"] = len(data_ok)
        p["verdict"] = "answers" if data_ok else ("handshake only" if p["answered"] else "no answer")
    surface = doc.get("agent_hub_surface") or {}
    return {
        "generated_at": doc.get("generated_at"),
        "rules": doc.get("rules"),
        "paths": list(paths.values()),
        "agent_hub_surface": {
            "operations": sum(v.get("operations", 0) for v in surface.values()),
            "public": sum(v.get("public", 0) for v in surface.values()),
            "by_domain": {k: {kk: vv for kk, vv in v.items() if kk != "public_ops"} for k, v in surface.items()},
            "public_ops": sorted({op for v in surface.values() for op in v.get("public_ops", [])}),
        } if surface else None,
    }


_SYM = re.compile(r"^[A-Z0-9]{2,}$")
_HANDSHAKE = re.compile(r"initialize|tools/list|discover")


def op_kind(operation: str) -> tuple[str, list[str]]:
    """'market getFundingRateHistory NVDAUSDT' -> ('market getFundingRateHistory', ['NVDAUSDT']).
    An operation is counted once however many symbols it was called for."""
    toks = str(operation or "").split()
    syms = [t for t in toks if _SYM.match(t)]
    return " ".join(t for t in toks if not _SYM.match(t)) or str(operation), syms


def count_calls(rows: list[dict]) -> dict:
    """Counts from the call log only. 'product' rows come from the running adapter, 'probe' rows from the script."""
    out: dict[str, dict] = {}
    for origin in sorted({r.get("origin", "?") for r in rows}):
        ops: dict[tuple, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "symbols": set(), "last_at": None, "last_status": None})
        for r in rows:
            if r.get("origin", "?") != origin:
                continue
            kind, syms = op_kind(r.get("operation", ""))
            o = ops[(r.get("source"), kind)]
            o["calls"] += 1
            o["ok"] += bool(r.get("ok"))
            o["symbols"].update(syms)
            o["last_at"], o["last_status"] = r.get("at"), r.get("status")
        table = [{"source": s, "operation": op, **{**v, "symbols": sorted(v["symbols"])}}
                 for (s, op), v in sorted(ops.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))]
        for t in table:
            t["handshake"] = bool(_HANDSHAKE.search(t["operation"]))
        data_ops = [t for t in table if not t["handshake"]]
        out[origin] = {
            "calls": sum(t["calls"] for t in table),
            "calls_ok": sum(t["ok"] for t in table),
            # handshakes (initialize, tools/list, discover) are listed but never counted as operations
            "distinct_operations": len(data_ops),
            "distinct_operations_answered": sum(t["ok"] > 0 for t in data_ops),
            "operations": table,
        }
    return out


def evidence() -> dict:
    f, doc = latest_evidence()
    rows = bc.read_call_log()
    counts = count_calls(rows)
    prod = counts.get("product", {})
    return {
        "evidence_file": f"evidence/{f.name}" if f else None,
        "probe": summarize_probe(doc) if doc else None,
        "probe_missing_reason": None if doc else ("no evidence file yet" if f is None else "evidence file unreadable"),
        "call_log": {"path": str(bc.CALL_LOG.name), "rows": len(rows), "by_origin": counts},
        "headline": {
            "product_bitget_operations_called": prod.get("distinct_operations", 0),
            "product_bitget_operations_answered": prod.get("distinct_operations_answered", 0),
            "product_calls": prod.get("calls", 0),
            "note": "Generated from the call log at request time. 'product' = calls made by engine/bitget_context.py; "
                    "'probe' = calls made by scripts/probe_bitget_tools.py.",
        },
        "context_adapter": bc.status(),
    }


@router.get("/api/evidence")
def api_evidence():
    return evidence()


@router.get("/api/evidence/context")
def api_evidence_context(symbol: str = Query(..., max_length=32), day: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """The one context line a review would carry for (symbol, trade day). Cache only, never fetches."""
    return bc.context_for(symbol, day)


@router.get("/evidence", include_in_schema=False)
def evidence_page():
    return FileResponse(STATIC / "evidence.html")
