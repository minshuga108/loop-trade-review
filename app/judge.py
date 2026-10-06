"""Judge-facing routes: the cockpit, the selftest page and the source report.

The owner wires this in with `app.include_router(judge.router)` in app/main.py.
Everything here is read-only and needs no key. Every number a page shows comes
from these endpoints (computed when asked) or from a results file it names.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from engine.market import Category

from . import costs, llm, selftest, service

router = APIRouter()
STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[1]
LOSSES = ROOT / "LOSSES.md"

# The public Bitget endpoints the book refresher calls (app/costs.py -> engine/market.py Fetcher).
# A snapshot only lands in the cache when instrument, book and ticker all answered, so a cached
# snapshot proves those three were reached at its fetch time. Fees and session windows are optional.
ENDPOINTS = [
    {"path": "/api/v3/market/instruments", "what": "min order, tick and step, futures fee rates", "reached_if": "snapshot"},
    {"path": "/api/v3/market/orderbook", "what": "depth levels for the cost walk", "reached_if": "snapshot"},
    {"path": "/api/v3/market/tickers", "what": "last price, best bid and ask", "reached_if": "snapshot"},
    {"path": "/api/v2/spot/public/symbols", "what": "spot taker fee for rTokens", "reached_if": "spot_fee"},
    {"path": "/api/v3/reality/market/states", "what": "US session windows for rTokens", "reached_if": "windows"},
]


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def sources() -> dict:
    now = time.time()
    snaps = dict(costs.CACHE)
    eps = []
    for e in ENDPOINTS:
        if e["reached_if"] == "snapshot":
            hits = {s: v.fetched_at for s, v in snaps.items()}
        elif e["reached_if"] == "spot_fee":
            hits = {s: v.fetched_at for s, v in snaps.items() if v.fee is not None and getattr(v.instr, "category", None) is Category.SPOT}
        else:
            hits = {s: v.fetched_at for s, v in snaps.items() if v.windows is not None}
        last = max(hits.values()) if hits else None
        eps.append({"path": e["path"], "what": e["what"], "reached": bool(hits), "last_reached": _iso(last),
                    "age_s": round(now - last) if last else None, "symbols": sorted(hits)})
    refresher = "off (LOOP_NO_REFRESH is set)" if os.environ.get("LOOP_NO_REFRESH") else (
        "on, every %d s" % costs.REFRESH_S if costs._started else "not started")
    wallets = [t for t in service.TRADERS if t["file"]]
    present = [t["id"] for t in wallets if (service.SHIPPED / f"wallet_{t['id']}.csv").exists() or (service.SAMPLES / t["file"]).exists()]
    return {
        "now": _iso(now),
        "bitget_public": {
            "host": "api.bitget.com (public market data, no key, GET only)",
            "refresher": refresher,
            "watchlist": [s for s, _ in costs.WATCH],
            "symbols_cached": len(snaps),
            "stale_after_s": costs.STALE_S,
            "endpoints": eps,
            "endpoints_reached": sum(e["reached"] for e in eps),
            "endpoints_total": len(eps),
            "note": "Read from the refresher's cache. A failed call leaves no snapshot, so 'not reached' can mean failed or not tried yet.",
        },
        "data": [
            {"name": "Public Hyperliquid wallets, hand-picked, illustrative (aliases only, addresses withheld)",
             "provenance": "REAL_PLATFORM_PUBLIC", "shipped": len(present), "expected": len(wallets), "aliases": present},
            {"name": "Simulated trader with a planted costly habit", "provenance": "SIM_PLANTED", "shipped": 1, "expected": 1, "aliases": ["F"]},
        ],
        "tools": [
            {"name": "Intent router (deterministic, English and Chinese)", "status": "on"},
            {"name": "Number-lock on every chat answer", "status": "on"},
            {"name": "Rule court (held-out test, every proposal counted)", "status": "on"},
            {"name": "Language model", "status": llm.label()},
        ],
        "video_url": os.environ.get("LOOP_VIDEO_URL") or None,
    }


@router.get("/cockpit", include_in_schema=False)
def cockpit():
    return FileResponse(STATIC / "cockpit.html")


@router.get("/selftest", include_in_schema=False)
def selftest_page():
    return FileResponse(STATIC / "selftest.html")


@router.get("/api/sources")
def api_sources():
    return sources()


@router.get("/api/losses", response_class=PlainTextResponse)
def api_losses():
    return LOSSES.read_text(encoding="utf-8") if LOSSES.exists() else "LOSSES.md is missing from this build."


@router.post("/api/selftest/run")
def api_selftest_run(request: Request, wait: bool = Query(False)):
    return selftest.start(request.app, wait=wait)


@router.get("/api/selftest/latest")
def api_selftest_latest():
    return selftest.snapshot()


@router.get("/api/selftest/first-run")
def api_selftest_first_run():
    fr = selftest.first_run()
    return fr if fr is not None else {"missing": True}
