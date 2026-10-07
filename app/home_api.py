"""First-screen helpers: server-rendered verdict banner and 'drop your fills' tile, sample CSV, chat feedback into the public record.

Wire-up (app/main.py): include `home_api.router`, and let "/" return `home_api.index_response()`.
Nothing here computes a statistic: the banner sentence is built from the cached review (engine state).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import chat, record_api, service, validation_note

router = APIRouter()
STATIC = Path(__file__).parent / "static"
SAMPLE = Path(__file__).resolve().parents[1] / "deploy_data" / "real_bitget" / "doge_trades_analysis.csv"
DEFAULT_TRADER = "B"                     # the wallet home.js opens first
ACCEPT_PATH = [("F", "planted trader F (simulated)", "模拟交易者 F"), ("D", "wallet D (real public data)", "钱包 D（真实公开数据）")]
VOTES = ("up", "down")


def banner_html(tid: str = DEFAULT_TRADER) -> str:
    """Banner markup for one trader. Both languages are in the page; CSS shows the one that matches <html lang>."""
    rv = service._REVIEW_CACHE.get(tid)          # never block the first byte on a cold computation
    if rv is not None:
        b = chat.verdict_banner(tid, rv)
        en, zh = b["en"], b["zh"]
    else:
        en = "Loop tests a habit on your own fills, then tests the rule for it on trades it never saw; the verdict appears here as soon as the review is computed."
        zh = "Loop 先在你自己的成交记录里检验一个习惯，再用没见过的交易检验针对它的规则；复盘算完后，结论会出现在这里。"
    vn = ""
    try:
        n = validation_note.note_for(tid, rv["headline"]["priced"].get("all_history_effect")) if rv is not None else None
        if n:
            vn = (f'<p class="vb-warn" id="vbwarn"><span data-l="en">{html.escape(n["en"])} <a href="{n["doc_url"]}">{n["doc"]}</a> · <a href="{n["proof_url"]}">proof</a></span>'
                  f'<span data-l="zh">{html.escape(n["zh"])} <a href="{n["doc_url"]}">{n["doc"]}</a> · <a href="{n["proof_url"]}">证明</a></span></p>')
    except Exception:
        vn = ""
    paths = "".join(f'<button type="button" class="vb-pick" data-pick="{i}"><span data-l="en">See an accepted rule: {html.escape(e)}</span><span data-l="zh">看一条通过的规则：{html.escape(z)}</span></button>'
                    for i, e, z in ACCEPT_PATH)
    return (f'<section class="vbanner" id="vbanner" aria-label="Verdict"><p class="vb-line" id="vbline"><span data-l="en">{html.escape(en)}</span><span data-l="zh">{html.escape(zh)}</span></p>{vn}'
            f'<p class="vb-path" id="vbpath">{paths}</p></section>')


def dropzone_html() -> str:
    return ('<section class="dropzone" id="dropzone" aria-labelledby="dz-h">'
            '<div class="dz-main"><h2 id="dz-h"><span data-l="en">Paste or drop your fills</span><span data-l="zh">粘贴或拖入你的成交记录</span></h2>'
            '<p><span data-l="en">Drop a Bitget or Hyperliquid CSV anywhere on this card. You get your habit, your rule and your gate in about 20 seconds. It is read in memory and not stored.</span>'
            '<span data-l="zh">把 Bitget 或 Hyperliquid 的 CSV 拖到这张卡片上，约 20 秒后得到你的习惯、你的规则和你的闸门。只在内存中读取，不会保存。</span></p></div>'
            '<div class="dz-actions"><label class="btn primary dz-file"><span data-l="en">Choose a CSV</span><span data-l="zh">选择 CSV</span>'
            '<input type="file" id="dzfile" accept=".csv,text/csv,text/plain" hidden></label>'
            '<button type="button" class="btn" id="dzsample"><span data-l="en">Try the 20-second sample</span><span data-l="zh">试试 20 秒示例</span></button>'
            '<span class="tag" id="dzmsg" role="status" aria-live="polite"></span></div></section>')


def index_html() -> str:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    marker = '<div class="picker" id="picker">'
    if marker not in page:
        return page
    try:
        block = dropzone_html() + banner_html()
    except Exception:                              # the banner is an addition: never let it take the page down
        block = dropzone_html()
    return page.replace(marker, block + marker, 1)


def index_response() -> HTMLResponse:
    return HTMLResponse(index_html())


@router.get("/api/banner/{tid}")
def banner(tid: str):
    try:
        return chat.verdict_banner(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@router.get("/api/sample-fills")
def sample_fills():
    if not SAMPLE.exists():
        raise HTTPException(404, "sample not shipped")
    return PlainTextResponse(SAMPLE.read_text(encoding="utf-8"), media_type="text/csv; charset=utf-8")


class FeedbackIn(BaseModel):
    trader: str = Field(max_length=40)
    intent: str = Field(default="", max_length=24)
    vote: str


@router.post("/api/feedback")
def feedback(body: FeedbackIn, x_session: str = Header(default="default")):
    """A thumb on one chat answer, written to the public record as a tagged rule_event (tag 'feedback'). No question text is stored."""
    if body.vote not in VOTES:
        raise HTTPException(400, "vote must be up or down")
    if not re.fullmatch(r"[a-z_]{0,24}", body.intent):
        raise HTTPException(400, "bad intent")
    if not any(t["id"] == body.trader for t in service.TRADERS) and body.trader not in service._DYN:
        raise HTTPException(404, "unknown trader")
    entry = record_api.log_rule_event(x_session, body.trader, {
        "event": "chat_feedback", "tag": "feedback", "vote": body.vote, "intent": body.intent or None,
        "origin": record_api.classify_origin(x_session, body.trader, body.trader in service._DYN), "paper_only": True})
    if not entry or entry.get("error"):
        raise HTTPException(503, "feedback could not be written to the public record: " + str((entry or {}).get("error", "unknown")))
    return {"ok": True, "seq": entry["seq"], "tag": "feedback", "vote": body.vote}
