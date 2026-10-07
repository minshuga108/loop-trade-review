"""Review cards API: trade replay, trend and drift, ledger drift, structural gap, rule decay,
intent sandbox, report export (signed) and share card. Read-only over the demo histories;
the only state is the per-session sandboxes (rulebook from service.py, intent book here).

Hook (app/main.py, right after the other include_router lines, BEFORE the /api/report/{tid} route
so /api/report/{tid}.md and .html are matched here first):
    from .cards_api import router as cards_router; app.include_router(cards_router)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from engine import decay as decay_mod
from engine import intent as intent_mod
from engine import ledger_drift, ledger_walk, replay, report as report_mod, report_html, sharecard, signing, trend as trend_mod
from engine.court import Rule, _baseline, _effect
from engine.detectors import after_loss_labels
from engine.structural_gap import EXIT_GRACE_MS, GAP_TOLERANCE, StopPlan, tag_stop_exits

from . import record_api, service

router = APIRouter()
SANDBOX = intent_mod.Sandbox()
CCXT = Path("bitget_samples") / "ccxt_mit" / "ccxt_bitget_uta_real_responses.json"


def _clean(x):
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _load(tid: str):
    try:
        return service._load(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


# ------------------------------------------------------------------ 1. trade replay (R3)
@router.get("/api/trips/{tid}")
def trips(tid: str, finding: str | None = Query(None, pattern="^(size_after_loss|hold_asymmetry|overtrading_clusters|revenge_reentry)$"),
          limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    meta, fills, orders, ts = _load(tid)
    rows = replay.trip_rows(ts)
    if finding:
        tag = replay.FINDING_TAGS[finding]
        rows = [r for r in rows if tag in r["tags"]]
    total = len(rows)
    rows = sorted(rows, key=lambda r: r["net_pnl"])[offset:offset + limit] if finding else rows[offset:offset + limit]
    return {"trader": tid, "finding": finding, "tag": replay.FINDING_TAGS.get(finding) if finding else None, "total": total,
            "offset": offset, "rows": rows, "has_fills": bool(fills), "provenance": service._prov(meta, fills),
            "order": "worst net result first" if finding else "by open time",
            "note": "Trips are flat-to-flat round trips rebuilt from fills; a trip cut by the start of the history is skipped, never guessed."}


@router.get("/api/trip/{tid}/{index}")
def trip(tid: str, index: int):
    meta, fills, orders, ts = _load(tid)
    try:
        return _clean(replay.trip_detail(ts, fills, index, journal=meta.get("role") == "real_journal"))
    except IndexError:
        raise HTTPException(404, "no trip with that index")


# ------------------------------------------------------------------ 2. trend and drift (R11)
@router.get("/api/trend/{tid}")
def trend(tid: str, habit: str = Query("size_after_loss", pattern="^(size_after_loss|hold_asymmetry)$")):
    meta, fills, orders, ts = _load(tid)
    tr = trend_mod.trend(ts, habit)
    out = tr.model_dump()
    out["provenance"] = service._prov(meta, fills)
    return _clean(out)


# ------------------------------------------------------------------ 3a. ledger drift
def _ccxt_path() -> Path | None:
    for p in Path(__file__).resolve().parents:
        cand = p / "data" / CCXT
        if cand.exists():
            return cand
    return None


def _ccxt_rows(prefix: str) -> list[dict]:
    p = _ccxt_path()
    if p is None:
        return []
    items = json.loads(p.read_text(encoding="utf-8"))["items"]
    return [r for i in items if str(i.get("endpoint", "")).startswith(prefix) and i.get("httpResponse")
            for r in (i["httpResponse"]["data"]["list"] or [])]


def ledger_demo() -> list[dict]:
    out = []
    for prefix, name in (("GET /api/v3/account/financial-records", "Futures account: one funding settlement"),
                         ("GET /api/v3/account/funding-financial-records", "Funding wallet: deposit, transfer, withdrawal")):
        rows = _ccxt_rows(prefix)
        if not rows:
            continue
        w = ledger_walk.walk(rows)
        # no fills exist for these windows in the sample, so trading contributes zero; stated, not assumed silently
        rec = ledger_drift.reconcile(rows, trade_pnl=0.0, trade_fees=0.0, balance_change=w["end"] - w["start"],
                                     start_equity=w["start"])
        out.append({"name": name, "endpoint": prefix.replace("GET ", ""), "n_rows": len(rows), "walk": w,
                    "reconciliation": rec.model_dump(),
                    "inputs": "balance change from the rows' own running balance (start inferred from the first row); "
                              "trade pnl and fees = 0 because the sample holds no fills for this window"})
    return out


@router.get("/api/ledger-drift/{tid}")
def ledger_card(tid: str):
    meta, fills, orders, ts = _load(tid)
    return _clean({
        "wallet": {"status": "NO_RECORDS", "trader": tid,
                   "detail": "This wallet has fills but no balance snapshots or financial-records rows (funding, transfers, "
                             "fees outside trades), so its balance cannot be reconciled. Nothing is estimated in their place."},
        "demo": ledger_demo(),
        "demo_label": "REAL rows: captured Bitget API responses from the ccxt test suite (MIT). Not this wallet; tiny on purpose.",
        "method": "explained = trade pnl - trade fees + funding + liquidation fees + transfers + rebates; "
                  "residual = balance change - explained, reported and never assigned to any category",
    })


# ------------------------------------------------------------------ 3b. structural gap sandbox
class GapIn(BaseModel):
    side: str = Field(pattern="^(long|short)$")
    stop: float = Field(gt=0)
    prints: list[tuple[float, float]] = Field(min_length=1, max_length=200)   # (minute, price) you typed
    exit_minute: float = Field(ge=0, le=100_000)
    exit_price: float = Field(gt=0)


@router.post("/api/structural-gap/sandbox")
def gap_sandbox(body: GapIn):
    series = sorted((int(round(m * 60_000)), float(p)) for m, p in body.prints)
    if any(p <= 0 for _, p in series):
        raise HTTPException(400, "prices must be positive")
    plan = StopPlan(trip_id="sandbox", stop=body.stop, side=body.side, t_open_ms=0,
                    t_exit_ms=int(round(body.exit_minute * 60_000)), exit_price=body.exit_price)
    tag = tag_stop_exits([plan], series)[0]
    why = {
        "NOT_TRIGGERED": "No price you typed reached the stop before the exit, so this is not a stop-out and does not enter the score.",
        "HONOURED": "Price reached the stop with a print near the level and the exit came within the grace period: honoured.",
        "BEHAVIOURAL_BREACH": "Price reached the stop and the position was still open after the grace period: a behavioural breach.",
        "STRUCTURAL_GAP": "The first print past the stop was already beyond it by more than the gap tolerance, and the exit was prompt: "
                          "the market jumped the stop. It still costs money and stays in cost numbers, but it is left out of the behaviour score.",
    }[tag.tag]
    return _clean({"label": "SANDBOX: every number here is one you typed. No trader data is used.", "provenance": "SIM_PAPER",
                   "tag": tag.model_dump(), "why": why, "gap_tolerance": GAP_TOLERANCE, "exit_grace_s": EXIT_GRACE_MS // 1000})


# ------------------------------------------------------------------ 4. rule decay
REPLAY_FRAC = 0.6   # the same 60/40 cut as Court.train_frac; stated in every answer


def _decay_view(rule: Rule, ts) -> dict:
    ts = sorted(ts, key=lambda t: t.t_open_ms)
    cut = int(len(ts) * REPLAY_FRAC)
    pre, post = ts[:cut], ts[cut:]
    base = _baseline(pre)
    check = decay_mod.cap_decay_check(post, rule, base)
    lab = after_loss_labels(post)
    cum, pts = 0.0, []
    for i, t in enumerate(post):
        if lab[i] >= 0:
            cum += _effect(np.array([t.first_order_notional]), np.array([t.net_pnl]), np.array([lab[i] == 1]), rule.value * base)
        pts.append([t.t_close_ms, round(cum, 2)])
    thirds = np.linspace(0, len(post), 4).astype(int)
    parts = []
    for k in range(3):
        seg = post[thirds[k]:thirds[k + 1]]
        if seg:
            c = decay_mod.cap_decay_check(seg, rule, base, n_perm=400)
            parts.append({"part": k + 1, "first_ms": seg[0].t_open_ms, "last_ms": seg[-1].t_open_ms, **c})
    return {"since_arming": {"status": "UNDERPOWERED", "n_trips": 0,
                             "detail": "No trades have happened since you armed this rule (the demo history is fixed), so the real decay check has nothing to judge yet."},
            "replay": {"label": "REPLAY: treats the last 40% of the history as if it came after arming. Those trades were also part of the "
                                "court's evidence, so this shows how the check works; it is not an independent test.",
                       "cut_ms": ts[cut].t_open_ms if cut < len(ts) else None, "baseline": base, "cap": rule.value * base,
                       "check": check, "curve": pts, "parts": parts,
                       "rule": f"retire if effect <= 0 or p > {decay_mod.RETIRE_P}; underpowered below {decay_mod.MIN_TRIPS} trips "
                               f"or {decay_mod.MIN_AFFECTED_CAP} affected"}}


@router.get("/api/decay/{tid}")
def decay_list(tid: str, x_session: str = Header(default="default")):
    meta, fills, orders, ts = _load(tid)
    rb = service.book(x_session, tid)
    out = []
    for rid, e in rb.entries.items():
        if e.state in ("ARMED", "PENDING_RETIREMENT"):
            out.append({"rule_id": rid, "state": e.state, "rule": e.current["rule"], **_decay_view(Rule(**e.current["rule"]), ts)})
    return _clean({"rules": out, "note": "Only armed rules are checked. Loop may PROPOSE retirement; only you can confirm it."})


@router.post("/api/decay/{tid}/{rule_id}/check")
def decay_check(tid: str, rule_id: str, x_session: str = Header(default="default")):
    meta, fills, orders, ts = _load(tid)
    rb = service.book(x_session, tid)
    e = rb.entries.get(rule_id)
    if e is None or e.state not in ("ARMED", "PENDING_RETIREMENT"):
        raise HTTPException(409, "only an armed rule can be checked for decay")
    v = _decay_view(Rule(**e.current["rule"]), ts)
    c = v["replay"]["check"]
    proposed = False
    if c["status"] == "RETIRE" and e.state == "ARMED":
        rb.propose_retirement(rule_id, f"replayed decay check on the last 40% of the history (overlaps the court's evidence): "
                                       f"effect {c['effect']:.2f}, p={c['p']:.3f}; retire if effect <= 0 or p > {decay_mod.RETIRE_P}")
        record_api.log_rule_event(x_session, tid, rb.log[-1])
        proposed = True
    return _clean({"rule_id": rule_id, "proposed_retirement": proposed, "state": rb.entries[rule_id].state, **v,
                   "book": service.rulebook_view(x_session, tid)})


# ------------------------------------------------------------------ 5. intent sandbox (R10)
@router.post("/api/intent/stamp")
def intent_stamp(body: intent_mod.StampIn, x_session: str = Header(default="default")):
    try:
        e = SANDBOX.get(x_session).stamp(body)
    except intent_mod.IntentError as ex:
        raise HTTPException(400, str(ex))
    return {"stamped": e, "view": SANDBOX.get(x_session).view()}


@router.post("/api/intent/resolve")
def intent_resolve(body: intent_mod.ResolveIn, x_session: str = Header(default="default")):
    try:
        e = SANDBOX.get(x_session).resolve(body)
    except intent_mod.IntentError as ex:
        raise HTTPException(409, str(ex))
    return {"outcome": e, "view": SANDBOX.get(x_session).view()}


@router.get("/api/intent")
def intent_view(x_session: str = Header(default="default")):
    return SANDBOX.get(x_session).view()


@router.get("/api/intent/metrics/{tid}")
def intent_metrics(tid: str):
    meta, fills, orders, ts = _load(tid)
    return {"trader": tid, "status": "REFUSED", "provenance": service._prov(meta, fills), "reason": intent_mod.REFUSAL,
            "stamped_trades": 0, "trades": len(ts)}


# ------------------------------------------------------------------ 6. report export (R12)
def _report(tid: str, lang: str) -> tuple[dict, dict]:
    try:
        rv = service.review(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")
    return rv, report_mod.build(rv, report_mod.previous_snapshot(tid), lang)


def _meta(rv: dict) -> list[str]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return [f"Exported {now} by Loop. Provenance: {rv['trader']['provenance']}.",
            "Every number is computed from fills and number-locked; none is typed by hand.",
            "Signature: HMAC-SHA256 with this server's key (a signature, not zero-knowledge). Check it at /api/report/verify."]


@router.get("/api/report/{tid}.md")
def report_md(tid: str, lang: str = Query("en", pattern="^(en|zh)$")):
    rv, out = _report(tid, lang)
    text = out["markdown"] + "\n\n---\n" + "\n".join(f"_{x}_" for x in _meta(rv))
    signed, info = signing.sign(text)
    return PlainTextResponse(signed, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="loop-review-{tid}.md"',
                                      "X-Loop-Signed": "yes" if info["signed"] else "no"})


@router.get("/api/report/{tid}.html")
def report_page(tid: str, lang: str = Query("en", pattern="^(en|zh)$"), download: bool = False):
    rv, out = _report(tid, lang)
    page = report_html.render(out["markdown"], f"Loop review: wallet {tid}", _meta(rv))
    signed, info = signing.sign(page)
    hdr = {"X-Loop-Signed": "yes" if info["signed"] else "no",
           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}
    if download:
        hdr["Content-Disposition"] = f'attachment; filename="loop-review-{tid}.html"'
    return Response(signed, media_type="text/html; charset=utf-8", headers=hdr)


class VerifyIn(BaseModel):
    text: str = Field(max_length=2_000_000)


@router.post("/api/report/verify")
def report_verify(body: VerifyIn):
    return signing.verify(body.text)


# ------------------------------------------------------------------ 7. share card (M23)
@router.get("/api/share/{tid}.svg")
def share(tid: str, request: Request):
    try:
        rv = service.review(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")
    return Response(sharecard.svg(rv, str(request.url).split("?")[0]), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300"})
