"""Weekly review push to the chat apps traders already use: Telegram, Feishu, WeChat Work.

Delivery only: it sends the same number-locked summary the web report shows. Nothing
here reads an account, places an order or changes a rule. Channels switch on only when
their environment variables are present; with none set, send_weekly() is a dry run.

  Telegram:      TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Feishu:        FEISHU_WEBHOOK (custom bot URL), optional FEISHU_SECRET (signing)
  WeChat Work:   WECOM_WEBHOOK (group robot URL)
Secrets are read from the environment only and never logged or returned.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import httpx

MAX_LEN = {"telegram": 3800, "feishu": 3800, "wecom": 3800}


def summary_text(review: dict, report_md: str, link: str | None = None, lang: str = "en") -> str:
    """A short digest from the computed report: header, priority finding, court line, plan, and a link."""
    lines = [ln for ln in report_md.splitlines() if ln.strip()]
    keep: list[str] = []
    take = False
    for ln in lines:
        if ln.startswith("## "):
            take = ln[3:5] in ("1.", "2.", "4.", "5.", "6.")
            if take:
                keep.append(ln[3:].strip())
            continue
        if take:
            keep.append(ln.strip())
    head = lines[0].lstrip("# ").strip() if lines else "Loop weekly review"
    body = "\n".join(keep)
    tail = (f"\n{link}" if link else "") + ("\n只读，纸面交易，不会下单。" if lang == "zh" else "\nRead-only, paper only. Nothing here places an order.")
    return (head + "\n" + body + tail)[: MAX_LEN["telegram"]]


def configured() -> dict[str, bool]:
    e = os.environ.get
    return {"telegram": bool(e("TELEGRAM_BOT_TOKEN") and e("TELEGRAM_CHAT_ID")), "feishu": bool(e("FEISHU_WEBHOOK")), "wecom": bool(e("WECOM_WEBHOOK"))}


def _feishu_sign(secret: str, ts: str) -> str:
    key = f"{ts}\n{secret}".encode()
    return base64.b64encode(hmac.new(key, b"", digestmod=hashlib.sha256).digest()).decode()


def send_weekly(text: str, client: httpx.Client | None = None, dry_run: bool | None = None) -> dict:
    """Send `text` to every configured channel. Returns {channel: 'sent' | 'dry-run' | error string}."""
    cfg = configured()
    results: dict[str, str] = {}
    if dry_run is None:
        dry_run = not any(cfg.values())
    c = client or httpx.Client(timeout=10.0)
    e = os.environ.get
    try:
        if cfg["telegram"]:
            url = f"https://api.telegram.org/bot{e('TELEGRAM_BOT_TOKEN')}/sendMessage"
            results["telegram"] = _post(c, url, {"chat_id": e("TELEGRAM_CHAT_ID"), "text": text, "disable_web_page_preview": True}, dry_run)
        if cfg["feishu"]:
            body = {"msg_type": "text", "content": {"text": text}}
            if e("FEISHU_SECRET"):
                ts = str(int(time.time()))
                body.update({"timestamp": ts, "sign": _feishu_sign(e("FEISHU_SECRET"), ts)})
            results["feishu"] = _post(c, e("FEISHU_WEBHOOK"), body, dry_run)
        if cfg["wecom"]:
            results["wecom"] = _post(c, e("WECOM_WEBHOOK"), {"msgtype": "markdown", "markdown": {"content": text}}, dry_run)
    finally:
        if client is None:
            c.close()
    return results or {"none": "no channel configured (dry run)"}


def _post(c: httpx.Client, url: str, body: dict, dry_run: bool) -> str:
    if dry_run:
        return "dry-run"
    try:
        r = c.post(url, json=body)
        r.raise_for_status()
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if isinstance(data, dict) and data.get("code") not in (None, 0) and "errcode" not in data:
            return f"error: code {data.get('code')}"
        if isinstance(data, dict) and data.get("errcode") not in (None, 0):
            return f"error: errcode {data.get('errcode')}"
        return "sent"
    except Exception as ex:                       # never include the URL: it may hold a secret
        return f"error: {type(ex).__name__}"
