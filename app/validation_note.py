"""Honest note when the independent checks in validation_results.json disagree with a court acceptance.

Everything is read from the file when asked (cached by mtime); with no entry for a trader this returns None and
the page shows nothing. The all-history effect, when given, comes from the live review, not from this file.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "validation_results.json"
PROOF_LINK = "/proof"
DOC = "VALIDATION.md"
PBO_MAX = 0.5          # probability of backtest overfitting above this: not confirmed
DSR_MIN = 0.95         # deflated Sharpe below this: not confirmed
ROOT = FILE.parent
_cache: dict = {"mt": None, "d": None}


def load() -> dict | None:
    try:
        mt = FILE.stat().st_mtime
        if _cache["mt"] != mt:
            _cache.update(mt=mt, d=json.loads(FILE.read_text(encoding="utf-8")))
        return _cache["d"]
    except (OSError, ValueError):
        return None


def note_for(tid: str, all_history_effect: float | None = None) -> dict | None:
    d = load()
    try:
        r = d["pbo"]["real"][tid]
        accepted, pbo, dsr = r["court_accepted"], r["pbo"], r["dsr"]
    except (TypeError, KeyError):
        return None
    if not accepted or pbo is None:
        return None
    weak_dsr = dsr is None or dsr != dsr or dsr < DSR_MIN
    if not (pbo > PBO_MAX or weak_dsr):
        return None
    neg = all_history_effect is not None and all_history_effect < 0
    dsr_s = "n/a" if dsr is None or dsr != dsr else f"{dsr:.2f}"
    en = (f"Independent checks do NOT confirm this acceptance: the court accepted {accepted} rule(s) on unseen trades, "
          + ("but priced on the whole history the rule is negative, " if neg else "but ")
          + f"the probability of backtest overfitting is {pbo:.2f} and the deflated Sharpe is {dsr_s}. Treat it as unproven.")
    zh = (f"独立检验没有证实这次通过：法庭在没见过的交易上通过了 {accepted} 条规则，"
          + ("但按全部历史计价，这条规则是负的，" if neg else "但")
          + f"回测过拟合概率为 {pbo:.2f}，去膨胀夏普为 {dsr_s}。请视为尚未证实。")
    return {"trader": tid, "en": en, "zh": zh, "pbo": pbo, "dsr": None if dsr_s == "n/a" else dsr, "court_accepted": accepted,
            "negative_all_history": neg, "doc": DOC, "doc_url": "/validation", "proof_url": PROOF_LINK}


def router():
    from fastapi import APIRouter
    from fastapi.responses import PlainTextResponse
    r = APIRouter()

    @r.get("/validation")
    def validation_doc():
        p = ROOT / DOC
        return PlainTextResponse(p.read_text(encoding="utf-8") if p.exists() else "VALIDATION.md is not in this build.",
                                 media_type="text/markdown; charset=utf-8")

    @r.get("/api/validation-note/{tid}")
    def api_note(tid: str):
        return {"trader": tid, "note": note_for(tid)}
    return r
