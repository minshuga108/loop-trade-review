"""Data questions over a trader's own record: the QUERY layer behind the chat.

answer_qa(trader_id, message, sid, previous_plan=None) returns a dict in the same shape as
app.chat.answer's output plus {"plan": ..., "card": ..., "computed": ...}, or None when the
message is not a data question (the caller then falls back to app.chat).

Decision path, in order:
  1. deterministic parser (engine.qa.parse): plan / unsupported / clarify / none
  2. if none and a Qwen key is present, the optional planner may translate the sentence into
     a QueryPlan JSON. It is validated against the closed schema; an invalid plan is REFUSED
     (shown as a refusal, never executed). The model never sees numbers and never decides.
  3. execute + render; every numeral in the headline passes engine.numberlock.

Paper / read-only: nothing here places orders or touches the market.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable

import httpx

from engine import qa

from . import llm, service

DEFAULT_BASE = "https://hackathon.bitgetops.com/v1"
DEFAULT_MODEL = "qwen3.8-max"
NOT_DATA = "not_a_data_question"
QWEN_TIMEOUT_S = float(os.environ.get("LOOP_QWEN_TIMEOUT_S", "1.5"))      # a slow model never holds the answer: past this the deterministic path answers
_TL = threading.local()


def timed_out() -> bool:
    """True when the last model call on this thread hit the deadline (the caller then skips any second model call)."""
    return bool(getattr(_TL, "timed_out", False))


def with_deadline(fn, seconds: float = QWEN_TIMEOUT_S):
    """Run fn() with a hard wall-clock deadline. On timeout or error returns None and sets timed_out(); the stray call finishes in the background."""
    _TL.timed_out = False
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except FutureTimeout:
        _TL.timed_out = True
        return None
    except Exception:
        return None
    finally:
        ex.shutdown(wait=False)

PLANNER_SYSTEM = (
    "You translate a trader's question about their OWN trade record into one JSON QueryPlan. "
    "You never compute numbers and never answer the question. Reply with JSON only.\n"
    f"Allowed metrics: {', '.join(qa.METRICS)}.\n"
    f"Allowed group_by: {', '.join(qa.GROUP_BYS)} or null. Allowed compare: {', '.join(qa.COMPARES)}.\n"
    f"period.kind: {', '.join(qa.PERIODS)} (last_n needs n). filters: symbol (ticker), side (buy|sell), weekdays (0=Mon..6=Sun), "
    "outcome (win|loss), after_loss (bool). top_n: 1..20 or null. exclude_best: bool.\n"
    "If the question is not about the trader's own record (advice, market news, greetings, rules, habits), reply "
    '{"not_a_data_question": true}. If a previous plan is given and the question is a follow-up, return the previous plan with the change applied.\n'
    "Schema: " + json.dumps(qa.QueryPlan.model_json_schema(), separators=(",", ":"))
)


def planner_enabled() -> bool:
    return bool(os.environ.get("QWEN_API_KEY"))


def planner_label() -> str:
    return (f"Qwen ({os.environ.get('QWEN_MODEL', DEFAULT_MODEL)}) may translate an unclear question into a QueryPlan; it writes no numbers"
            if planner_enabled() else "off (deterministic parser)")


def qwen_plan(text: str, previous_plan: dict | None = None, client: httpx.Client | None = None, timeout: float = QWEN_TIMEOUT_S, sid: str = "default"):
    """Raw planner output (a dict) or None on any failure. Validation happens in answer_qa, never here.
    Counts against the shared spend caps (app.llm.budget_ok); over budget means None, i.e. the deterministic path."""
    if not planner_enabled() or not llm.budget_ok(sid):
        return None
    base = os.environ.get("QWEN_BASE_URL", DEFAULT_BASE).rstrip("/")
    user = text[:500] if not previous_plan else f"previous plan: {json.dumps(previous_plan)}\nquestion: {text[:500]}"
    body = {"model": os.environ.get("QWEN_MODEL", DEFAULT_MODEL), "temperature": 0,
            "messages": [{"role": "system", "content": PLANNER_SYSTEM}, {"role": "user", "content": user}]}
    try:
        c = client or httpx.Client(timeout=timeout)
        r = c.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {os.environ['QWEN_API_KEY']}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        out = json.loads(content)
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _base(lang: str, tid: str, meta, fills) -> dict:
    return {"intent": "qa", "lang": lang, "kind": "text", "trader": tid, "provenance": service._prov(meta, fills), "label": service._label(meta),
            "paper_only": True, "llm": planner_label()}


# Negation, 'weekdays', verb phrasings and unsupported windows are now handled inside engine.qa.parse (kind 'unparsed').
# The same guards (qa.unparseable / qa.rewrite_plan) are applied to a model-picked plan below.


def _cannot(lang: str, tid: str, reason: str, meta, fills, steps) -> dict:
    zh = lang == "zh"
    can = [c[2 if zh else 1] for c in qa.CHIP_POOL[:3]]
    msg = (qa.UNPARSED_ZH if zh else qa.UNPARSED_EN)[reason]
    text = msg + " " + ("我没有计算任何东西。我能回答的例如：" + "；".join(can) + "。" if zh else "I computed nothing. Three things I can answer: " + "; ".join(can) + ".")
    return {**_base(lang, tid, meta, fills), "text": text, "facts": [], "number_lock": "passed", "interpreted": "无法解析" if zh else "could not parse",
            "next": can, "chips": can, "plan": None, "card": {"type": "unsupported", "reason": reason, "cannot": msg, "can": can},
            "computed": {"n": 0, "window": None, "method": None, "caveats": []}, "steps": steps, "flags": [f"unparsed:{reason}"]}


def answer_qa(trader_id: str, message: str, sid: str = "default", previous_plan: dict | None = None,
              planner: Callable[[str, dict | None], object] | None = None, now_ms: int | None = None, allow_llm: bool = True) -> dict | None:
    """One data question -> number-locked answer dict, or None when the message is not a data question."""
    t0 = time.perf_counter()
    _TL.timed_out = False
    lang = qa.detect_lang(message)
    prev = qa.validate_plan(previous_plan) if previous_plan else None
    pr = qa.parse(message, prev)
    steps = [{"name": "read question (deterministic parser)", "ms": round((time.perf_counter() - t0) * 1000, 2)}]
    llm_note = planner_label()
    if pr.kind == "unparsed":                   # the schema cannot express it: say so, compute nothing, never guess a number
        meta, fills, orders, trips = service._load(trader_id)
        return _cannot(lang, trader_id, pr.reason, meta, fills, steps + [{"name": "guard: question outside the closed schema", "ms": 0.1}])
    low = pr.kind == "none" or (pr.kind == "clarify" and pr.reason == "which_metric")      # low parse confidence
    if low:
        use = None if not allow_llm else (planner if planner is not None else ((lambda m, p: qwen_plan(m, p, sid=sid)) if planner_enabled() else None))
        if use is None:
            if pr.kind == "none":
                return None
        else:
            t1 = time.perf_counter()
            pc = prev.compact() if prev else None
            raw = with_deadline(lambda: use(message, pc), QWEN_TIMEOUT_S + 0.3)
            if timed_out():
                steps.append({"name": f"Qwen planner timed out after {QWEN_TIMEOUT_S:g} s: deterministic answer used", "ms": round((time.perf_counter() - t1) * 1000, 1)})
                llm_note = f"Qwen was slow (over {QWEN_TIMEOUT_S:g} s), so the deterministic parser answered"
            else:
                steps.append({"name": "Qwen planner (schema-validated)", "ms": round((time.perf_counter() - t1) * 1000, 1)})
            if pr.kind == "none" and (raw is None or (isinstance(raw, dict) and raw.get(NOT_DATA))):
                return None
            if raw is not None and not (isinstance(raw, dict) and raw.get(NOT_DATA)):
                plan = qa.validate_plan(raw)
                if plan is not None:            # the same negation / window guards apply to a model-picked plan
                    d = plan.compact()
                    t = qa.normalise(message)
                    why = qa.unparseable(t) or qa.rewrite_plan(t, d)
                    if why:
                        meta, fills, orders, trips = service._load(trader_id)
                        return _cannot(lang, trader_id, why, meta, fills, steps)
                    plan = qa.validate_plan(d)
                if plan is None and pr.kind == "none":     # refused: outside the closed schema; nothing is executed
                    meta, fills, orders, trips = service._load(trader_id)
                    zh = lang == "zh"
                    text = ("模型给出的查询计划不在允许的范围内，已拒绝执行。我能回答的例如：净盈亏、胜率、手续费。" if zh else
                            "The planner's plan was outside the allowed schema, so I refused it and computed nothing. I can answer: net P&L, win rate, fees.")
                    chips = [c[2 if zh else 1] for c in qa.CHIP_POOL[:3]]
                    return {**_base(lang, trader_id, meta, fills), "text": text, "facts": [], "number_lock": "passed", "llm": "Qwen plan refused (invalid schema)",
                            "interpreted": ("计划被拒绝" if zh else "plan refused"), "next": chips, "chips": chips,
                            "plan": None, "card": {"type": "refused", "reason": "invalid_plan"}, "computed": None, "steps": steps, "flags": ["plan_refused"]}
                if plan is not None:
                    pr = qa.ParseResult(kind="plan", plan=plan, lang=lang, followup=prev is not None)
                    llm_note = "Qwen translated the question into a QueryPlan (validated against the closed schema); every number is computed here"
    meta, fills, orders, trips = service._load(trader_id)
    base = {**_base(lang, trader_id, meta, fills), "llm": llm_note}
    if pr.kind == "unsupported":
        out = qa.render_unsupported(pr.reason, lang)
        return {**base, **out, "chips": out["next"], "plan": None, "steps": steps, "flags": [f"unsupported:{pr.reason}"]}
    if pr.kind == "clarify":
        out = qa.render_clarify(pr, lang)
        return {**base, **out, "chips": out["next"], "plan": None, "steps": steps, "flags": ["clarify"]}
    t2 = time.perf_counter()
    res = qa.execute(pr.plan, trips, fills, now_ms=now_ms)
    steps.append({"name": f"loaded {len(trips)} round trips, computed {pr.plan.metric} on {res.n}", "ms": round((time.perf_counter() - t2) * 1000, 1)})
    out = qa.render(res, lang)
    steps.append({"name": f"number-lock: every number backed ({out['number_lock'].split(':')[0]})", "ms": 0.1})
    return {**base, **out, "chips": out["next"], "plan": pr.plan.compact(), "followup": pr.followup, "steps": steps,
            "flags": (["followup"] if pr.followup else []) + [f"caveat:{c}" for c in res.caveats]}
