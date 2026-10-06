"""MCP server for Loop: read-only, paper-only review tools over the Streamable HTTP transport.

Wire-up (owner, in app/main.py):   from .mcp_server import router as mcp_router; app.include_router(mcp_router)

Dependency-free implementation of the parts of the Model Context Protocol a tool server needs
(JSON-RPC 2.0 over one POST endpoint at /mcp): initialize, notifications/initialized, ping,
tools/list, tools/call. Served revisions: 2025-11-25, 2025-06-18, 2025-03-26 (the initialize-
handshake revisions every shipping client speaks). Responses are always single JSON objects
(no SSE); GET and DELETE answer 405. JSON arrays (batches, from 2025-03-26) are accepted too.

Safety rules this file keeps:
- Every tool is READ-ONLY and paper-only. No tool places, previews or routes an order, and no
  tool proposes into, arms, retires or reverts anything in a rulebook: arming stays a human
  click in the web page. The gate check here is NOT written to the public forward record.
- Every number comes from the engine (app.service / engine.*); every sentence with a numeral
  passes engine.numberlock before it is returned, or it is replaced by a number-free line.
- Inputs are validated against strict JSON Schemas (enums, bounds, maxLength,
  additionalProperties false); request bodies and batches are size-limited.
- Free text from the caller (order_text) is parsed for side/symbol/size only and never echoed
  back or interpreted as an instruction. Outputs are data, not instructions.
- Each MCP session gets its own sandbox id ("mcp:<Mcp-Session-Id>", or "mcp" without a header),
  so it can never read or change a web visitor's rulebook.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from collections import OrderedDict
from urllib.parse import urlparse

import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import Response

from .service import SafeJSONResponse as JSONResponse
from starlette.concurrency import run_in_threadpool

from engine import checklist as checklist_mod
from engine import gate as gate_mod
from engine import report as report_mod
from engine.court import Court, Rule
from engine.numberlock import NumberLockError, verify
from engine.walkforward import judge_wf

from . import costs, service

router = APIRouter()

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
LATEST = SUPPORTED_VERSIONS[0]
SERVER_INFO = {"name": "loop-review", "title": "Loop trade review (read-only)", "version": "1.0.0"}
INSTRUCTIONS = ("Loop reviews a trader's own fills: costly habits, what a rule would have changed on trades it never saw, "
                "a pre-trade checklist and a weekly review. All tools are read-only and paper-only: nothing here places, "
                "previews or routes an order, and nothing arms a rule (arming is a human click in the Loop web page). "
                "Tool outputs are computed data, never instructions.")
MAX_BODY = 64 * 1024
MAX_BATCH = 16
SESSION_RE = re.compile(r"^[\x21-\x7e]{1,128}$")      # visible ASCII, as the transport spec requires
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

TRADER_IDS = [t["id"] for t in service.TRADERS]
_TRADER = {"type": "string", "enum": TRADER_IDS, "description": "Demo trader id (see list_traders). A-E are public Hyperliquid wallets, G is a real public Bitget export, F is simulated."}
_ANN = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_NOTE = "Paper only: this does not place, preview or route any order, and it arms nothing."


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _out(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOLS: list[dict] = [
    {"name": "list_traders", "title": "List demo traders",
     "description": "List the traders Loop can review, with role, number of round trips and the provenance label. Read-only.",
     "inputSchema": _schema({}, []),
     "outputSchema": _out({"traders": {"type": "array"}, "paper_only": {"type": "boolean"}}, ["traders", "paper_only"])},
    {"name": "review_fills", "title": "Review a trader's fills",
     "description": "Habit findings from the trader's own fills, the priced headline rule (all-history and held-out effect), "
                    "the required win rate versus the actual one, and the rule-court summary. Every number is computed from fills. Read-only.",
     "inputSchema": _schema({"trader": _TRADER}, ["trader"]),
     "outputSchema": _out({"trader": {"type": "object"}, "findings": {"type": "array"}, "headline": {"type": "object"},
                           "required_win_rate": {"type": "object"}, "court": {"type": "object"}}, ["trader", "findings", "headline", "court"])},
    {"name": "rule_court", "title": "Test a size-cap rule in the court",
     "description": "Run the walk-forward court on 'cap opening size at <multiple>x your usual size after a loss' and return the verdict. "
                    "Runs in a throwaway sandbox: nothing is saved to a rulebook and nothing is armed. Every proposal in this MCP session "
                    "is counted, so the acceptance bar rises with each rule tried. Read-only.",
     "inputSchema": _schema({"trader": _TRADER, "multiple": {"type": "number", "minimum": 0.5, "maximum": 10,
                                                             "description": "Cap as a multiple of the usual opening size (0.5 to 10)."}},
                            ["trader", "multiple"]),
     "outputSchema": _out({"status": {"type": "string"}, "trials": {"type": "integer"}, "saved": {"type": "boolean"},
                           "armed": {"type": "boolean"}}, ["status", "trials", "saved", "armed"])},
    {"name": "rule_gate", "title": "Check an order idea against your rules",
     "description": "Check an order IDEA (e.g. 'buy $20k rNVDA') against the trader's armed rules, flagged habits and checklist. "
                    "Returns the gate state, reasons, checklist and the cost check line. It never places, previews or routes an order, "
                    "and the text is only parsed for side, symbol and size. Read-only.",
     "inputSchema": _schema({"trader": _TRADER,
                             "order_text": {"type": "string", "minLength": 1, "maxLength": 300, "description": "The order idea in plain words."},
                             "last_trade_was_loss": {"type": "boolean", "description": "Override; default is the trader's actual last trade."}},
                            ["trader", "order_text"]),
     "outputSchema": _out({"state": {"type": "string"}, "reasons": {"type": "array"}, "checklist": {"type": "array"},
                           "paper_only": {"type": "boolean"}}, ["state", "reasons", "checklist", "paper_only"])},
    {"name": "weekly_report", "title": "Weekly review (fupan)",
     "description": "The weekly review in the fupan template as markdown, English or Chinese; every number is number-locked. Read-only.",
     "inputSchema": _schema({"trader": _TRADER, "lang": {"type": "string", "enum": ["en", "zh"], "default": "en"}}, ["trader"]),
     "outputSchema": _out({"markdown": {"type": "string"}, "lang": {"type": "string"}, "facts": {"type": "object"}}, ["markdown", "lang"])},
    {"name": "checklist", "title": "Pre-trade checklist",
     "description": "The trader's pre-trade checklist (from habits that pass the test and from armed rules), each item with its measured effect. Read-only.",
     "inputSchema": _schema({"trader": _TRADER}, ["trader"]),
     "outputSchema": _out({"checklist": {"type": "array"}, "paper_only": {"type": "boolean"}}, ["checklist", "paper_only"])},
]
for _t in TOOLS:
    _t["annotations"] = {"title": _t["title"], **_ANN}
_BY_NAME = {t["name"]: t for t in TOOLS}


class ToolError(Exception):
    """A tool-level failure the model can read (isError: true), not a protocol error."""


class RpcError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


# ---- strict JSON Schema validation (the subset our schemas use) --------------------------------
def validate(schema: dict, value, path: str = "arguments") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected an object"]
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k}: required")
        if schema.get("additionalProperties") is False:
            errs += [f"{path}.{k}: unknown property" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errs += validate(props[k], v, f"{path}.{k}")
        return errs
    if t == "string":
        if not isinstance(value, str):
            return [f"{path}: expected a string"]
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return [f"{path}: expected a finite number"]
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above {schema['maximum']}")
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path}: expected an integer"]
    elif t == "boolean":
        if not isinstance(value, bool):
            return [f"{path}: expected a boolean"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: must be one of {schema['enum']}")
    return errs


# ---- number-lock for every sentence we write --------------------------------------------------
def _locked(text: str, facts: list[float], fallback: str) -> tuple[str, str]:
    try:
        verify(text, [float(f) for f in facts if f is not None], allow=tuple(float(i) for i in range(0, 11)))
        return text, "passed"
    except NumberLockError as e:
        return fallback, f"refused: {e}"


def _num(x):
    return None if x is None or (isinstance(x, float) and x != x) else x


# ---- tools -------------------------------------------------------------------------------------
def t_list_traders(args: dict, sid: str) -> tuple[dict, str]:
    rows = service.traders()
    text = f"{len(rows)} traders: " + ", ".join(f"{r['id']} ({r['role']}, {r['n_trips']} trips)" for r in rows) + "."
    text, lock = _locked(text, [len(rows)] + [r["n_trips"] for r in rows], "Traders listed in the structured result.")
    return {"traders": rows, "paper_only": True, "number_lock": lock}, text


def t_review_fills(args: dict, sid: str) -> tuple[dict, str]:
    tid = args["trader"]
    rv = service.review(tid)
    f = report_mod.facts_of(rv)
    wr, pr, c, s = rv["winrate"], rv["headline"]["priced"], rv["court"], rv["summary"]
    req = {**wr, "breakeven_pct": round(100 * wr["breakeven"], 1), "actual_pct": round(100 * wr["actual"], 1)}
    facts = list(f.values()) + [req["breakeven_pct"], req["actual_pct"], pr["held_out_effect"], pr["all_history_effect"]]
    fl = rv["headline"]["finding"]
    text = (f"Trader {tid}: {s['n_trips']} round trips, net {s['net_pnl']:,.2f} after fees. "
            + (f"Top finding: {fl['detector']} (status {fl['status']}). " if fl else "No habit passes the test. ")
            + f"Priced rule '{pr['rule']}': all-history effect {pr['all_history_effect']:,.2f}, held-out effect "
              f"{pr['held_out_effect']:,.2f} ({pr['status']}). Required win rate {req['breakeven_pct']}% vs actual "
              f"{req['actual_pct']}% ({wr['status']}). Court: {c['proposed']} proposed, {c['tested']} tested, {c['accepted']} accepted.")
    text, lock = _locked(text, facts, f"Review for trader {tid} is in the structured result.")
    out = {"trader": rv["trader"], "summary": s, "findings": rv["findings"],
           "headline": {"finding": fl, "underpowered": rv["headline"]["underpowered"], "priced": pr},
           "required_win_rate": req, "fee_drag": rv["fee_drag"],
           "court": {"proposed": c["proposed"], "tested": c["tested"], "accepted": c["accepted"], "verdicts": c["verdicts"]},
           "number_source": rv["number_source"], "paper_only": True, "number_lock": lock}
    return out, text


_TRIED: "OrderedDict[tuple[str, str], list[float]]" = OrderedDict()
_TRIED_LOCK = threading.Lock()
MAX_TRIED_KEYS, MAX_TRIED_PER_KEY = 500, 100


def t_rule_court(args: dict, sid: str) -> tuple[dict, str]:
    tid, mult = args["trader"], round(float(args["multiple"]), 4)
    _, _, _, trips = service._load(tid)
    with _TRIED_LOCK:
        tried = _TRIED.setdefault((sid, tid), [])
        _TRIED.move_to_end((sid, tid))
        while len(_TRIED) > MAX_TRIED_KEYS:
            _TRIED.popitem(last=False)
        if len(tried) >= MAX_TRIED_PER_KEY:
            raise ToolError(f"This session already tried {MAX_TRIED_PER_KEY} rules on this trader; start a new session.")
        tried.append(mult)
        prior = list(tried)
    court = Court(n_perm=1500)                      # a throwaway court: never saved, never armed
    for m in prior:                                 # every proposal in this session raises the bar
        court.propose(Rule(value=m))
    v = judge_wf(court, trips, Rule(value=mult))
    out = {"rule": f"cap opening size at {mult}x your usual size after a loss", "multiple": mult, "status": v.status,
           "reason": v.reason, "held_out_effect": round(v.test["effect"], 2), "affected": v.test["n_affected"],
           "test_trips": v.test["n_trips"], "learning_effect": round(v.train["effect"], 2),
           "p": None if v.p != v.p else round(v.p, 4), "threshold": round(v.alpha_used, 4), "trials": v.trials,
           "saved": False, "armed": False, "paper_only": True,
           "note": "Throwaway sandbox: this verdict is not saved to any rulebook and nothing is armed. "
                   "To arm an accepted rule, the owner clicks Arm in the Loop web page."}
    facts = [mult, out["held_out_effect"], out["affected"], out["test_trips"], out["p"], out["threshold"], v.trials]
    text = (f"Court verdict for '{out['rule']}' on trader {tid}: {v.status}. Held-out effect {out['held_out_effect']:,.2f}, "
            f"touching {out['affected']} of {out['test_trips']} unseen trades; trial {v.trials} in this session, "
            f"threshold {out['threshold']}. Not saved, not armed.")
    text, lock = _locked(text, facts, f"Court verdict for trader {tid}: {v.status}. Not saved, not armed.")
    out["number_lock"] = lock
    return out, text


def t_rule_gate(args: dict, sid: str) -> tuple[dict, str]:
    """The web gate's engine calls (parse, checklist, cost line, check), minus its public-record write."""
    tid, text_in = args["trader"], args["order_text"]
    _, _, _, trips = service._load(tid)
    rb = service.book(sid, tid)
    rv = service.review(tid)
    ts = sorted(trips, key=lambda t: t.t_close_ms)
    after_loss = args.get("last_trade_was_loss")
    last_loss = bool(ts[-1].net_pnl < 0) if after_loss is None else after_loss
    items = checklist_mod.generate(rv["findings"], rb.active_rules())
    flagged = [f["detector"] for f in rv["findings"] if f["status"] == "FLAGGED"]
    idea = gate_mod.parse_order(text_in)
    med = service._median_notional(trips)
    cl = costs.cost_line(idea.symbol, idea.notional, idea.side)
    res = gate_mod.check(idea, rb.active_rules(), items, med, last_loss, flagged,
                         cost_line=cl if cl.get("available") and not cl.get("stale") else None)
    caps = [round(r.value * med, 0) for _, r in rb.active_rules()]
    check_line = {k: v for k, v in cl.items() if k != "report"}          # keep the summary, not the full book dump
    facts = [x for x in (idea.notional, cl.get("cost_bps"), cl.get("cache_age_s")) if x is not None] + caps
    reasons = []
    for r in res.reasons:                                                  # engine sentences, still number-locked
        reasons.append(_locked(r, facts, "A reason was withheld because a number in it could not be backed.")[0])
    out = {"idea": {"side": idea.side, "symbol": idea.symbol, "notional": idea.notional}, "state": res.state,
           "reasons": reasons, "checklist": res.checklist, "broken_rules": res.broken_rules, "evidence": res.evidence_items,
           "last_trade_was_loss": last_loss, "armed_caps": caps, "check_line": check_line, "paper_only": True,
           "recorded": False,
           "note": "This checks an idea against the trader's own rules. It does not place, preview or route any order; "
                   "MCP checks are not written to the public record. Rules are armed only by a human click in the web page."}
    size = f"{idea.notional:,.0f}" if idea.notional else "no size read"
    line = (f"Gate: {res.state} for {idea.side or '?'} {idea.symbol or '?'} ({size}); last trade was "
            f"{'a loss' if last_loss else 'not a loss'}; {len(res.checklist)} checklist item(s). Paper only.")
    line, lock = _locked(line, facts + [len(res.checklist)], f"Gate: {res.state}. Paper only.")
    out["number_lock"] = lock
    return out, line


def t_weekly_report(args: dict, sid: str) -> tuple[dict, str]:
    tid, lang = args["trader"], args.get("lang", "en")
    rv = service.review(tid)
    r = report_mod.build(rv, report_mod.previous_snapshot(tid), lang)   # build() number-locks the markdown itself
    out = {"markdown": r["markdown"], "lang": lang, "facts": r["facts"], "number_lock": "passed", "saved": False, "paper_only": True}
    return out, r["markdown"]


def t_checklist(args: dict, sid: str) -> tuple[dict, str]:
    tid = args["trader"]
    b = service.rulebook_view(sid, tid)
    items = b["checklist"]
    text = (f"{len(items)} checklist item(s) for trader {tid}: " + " / ".join(i["text"] for i in items)) if items else \
        f"No checklist items for trader {tid} yet: they come from habits that pass the test and from rules the owner arms."
    text, lock = _locked(text, [len(items)], f"Checklist for trader {tid} is in the structured result.")
    armed = [e for e in b.get("entries", []) if e.get("state") in ("ARMED", "PENDING_RETIREMENT")]
    return {"trader": tid, "checklist": items, "armed_rules": len(armed), "paper_only": True, "number_lock": lock,
            "note": "This MCP session has its own sandbox rulebook; rules are armed only by a human click in the web page."}, text


HANDLERS = {"list_traders": t_list_traders, "review_fills": t_review_fills, "rule_court": t_rule_court,
            "rule_gate": t_rule_gate, "weekly_report": t_weekly_report, "checklist": t_checklist}
assert set(HANDLERS) == set(_BY_NAME)


def _jsonable(o):
    """Plain JSON only (numpy scalars, NaN -> null)."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def call_tool(name, args, sid: str) -> dict:
    if not isinstance(name, str) or name not in HANDLERS:
        raise RpcError(INVALID_PARAMS, f"Unknown tool: {str(name)[:64]}")
    args = {} if args is None else args
    errs = validate(_BY_NAME[name]["inputSchema"], args)
    if errs:
        raise RpcError(INVALID_PARAMS, "Invalid arguments", {"errors": errs[:10]})
    try:
        structured, text = HANDLERS[name](args, sid)
    except (ToolError, service.DataMissing) as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except StopIteration:
        raise RpcError(INVALID_PARAMS, "Unknown trader")
    structured = _jsonable(structured)
    return {"content": [{"type": "text", "text": text},
                        {"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
            "structuredContent": structured, "isError": False}


# ---- JSON-RPC dispatch ---------------------------------------------------------------------------
def _err(id_, code, message, data=None) -> dict:
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": e}


def handle_message(msg, sid: str, in_batch: bool = False) -> tuple[dict | None, bool]:
    """Returns (response or None for notifications/responses, was_initialize)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _err(None, INVALID_REQUEST, "Invalid Request"), False
    if "method" not in msg:
        if "id" in msg and ("result" in msg or "error" in msg):
            return None, False                       # a client response: accepted, nothing to answer
        return _err(msg.get("id"), INVALID_REQUEST, "Invalid Request"), False
    method, has_id, id_ = msg.get("method"), "id" in msg, msg.get("id")
    if not isinstance(method, str):
        return _err(id_ if has_id else None, INVALID_REQUEST, "Invalid Request"), False
    if has_id and (id_ is None or isinstance(id_, bool) or not isinstance(id_, (str, int))):
        return _err(None, INVALID_REQUEST, "Invalid Request: id must be a string or integer"), False
    params = msg.get("params", {})
    if params is not None and not isinstance(params, dict):
        return (_err(id_, INVALID_PARAMS, "params must be an object") if has_id else None), False
    params = params or {}
    if not has_id:                                   # notifications (initialized, cancelled, ...): never answered
        return None, False
    try:
        if method == "initialize":
            if in_batch:
                raise RpcError(INVALID_REQUEST, "initialize must not be part of a batch")
            asked = params.get("protocolVersion")
            ver = asked if asked in SUPPORTED_VERSIONS else LATEST
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}}, True
        if method == "ping":
            return {"jsonrpc": "2.0", "id": id_, "result": {}}, False
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}}, False
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": id_, "result": call_tool(params.get("name"), params.get("arguments"), sid)}, False
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method[:64]}")
    except RpcError as e:
        return _err(id_, e.code, e.message, e.data), False
    except Exception as e:                          # never leak a traceback
        return _err(id_, INTERNAL_ERROR, "Internal error", {"type": type(e).__name__}), False


def session_sid(header: str | None) -> str:
    return f"mcp:{header}" if header and SESSION_RE.match(header) else "mcp"


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True                                  # non-browser clients send none
    host = (urlparse(origin).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return True
    own = (request.headers.get("host") or "").split(":")[0].lower()
    if host and host == own:
        return True
    extra = {h.strip().lower() for h in os.environ.get("LOOP_MCP_ORIGINS", "").split(",") if h.strip()}
    return host in extra or origin.lower() in extra


@router.post("/mcp")
async def mcp_post(request: Request):
    if not _origin_ok(request):
        return JSONResponse(_err(None, INVALID_REQUEST, "Forbidden origin"), status_code=403)
    pv = request.headers.get("mcp-protocol-version")
    if pv is not None and pv not in SUPPORTED_VERSIONS:
        return JSONResponse(_err(None, INVALID_REQUEST, "Unsupported protocol version", {"supported": list(SUPPORTED_VERSIONS)}),
                            status_code=400)
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return JSONResponse(_err(None, INVALID_REQUEST, f"Body larger than {MAX_BODY} bytes"), status_code=413)
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):   # "[[[[..." nested 3000 deep used to be a 500
        return JSONResponse(_err(None, PARSE_ERROR, "Parse error"), status_code=400)
    header_sid = request.headers.get("mcp-session-id")
    sid = session_sid(header_sid)
    if isinstance(body, list):
        if not body:
            return JSONResponse(_err(None, INVALID_REQUEST, "Empty batch"), status_code=400)
        if len(body) > MAX_BATCH:
            return JSONResponse(_err(None, INVALID_REQUEST, f"Batch larger than {MAX_BATCH}"), status_code=413)
        out = []
        for m in body:
            r, _ = await run_in_threadpool(handle_message, m, sid, True)
            if r is not None:
                out.append(r)
        return JSONResponse(out) if out else Response(status_code=202)
    resp, was_init = await run_in_threadpool(handle_message, body, sid)
    if resp is None:
        return Response(status_code=202)
    headers = {}
    if was_init and "result" in resp:
        headers["Mcp-Session-Id"] = uuid.uuid4().hex          # a fresh sandbox per handshake
    status = 400 if resp.get("error", {}).get("code") in (PARSE_ERROR, INVALID_REQUEST) and resp.get("id") is None else 200
    return JSONResponse(resp, status_code=status, headers=headers)


@router.get("/mcp")
@router.delete("/mcp")
def mcp_not_allowed():
    return Response(status_code=405, headers={"Allow": "POST"})
