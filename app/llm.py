"""Optional Qwen helper (OpenAI-compatible endpoint). Off unless a key is present.

The model only maps an unclear sentence to one of a fixed set of intents. It
never writes numbers into answers and never decides anything. The key is read
from the environment (QWEN_API_KEY) and is never logged or returned.
"""
from __future__ import annotations

import json
import os
import threading
import time

import httpx

INTENTS = ("habit", "rule", "court", "report", "source", "gate", "checklist", "help")
DEFAULT_BASE = "https://hackathon.bitgetops.com/v1"
DEFAULT_MODEL = "qwen3.8-max"


# Spend guard: the key has a small credit balance, so a public site must never be able to drain it.
DAILY_CAP = int(os.environ.get("LLM_DAILY_CAP", "400"))       # model calls per UTC day, all visitors
SESSION_CAP = int(os.environ.get("LLM_SESSION_CAP", "20"))    # model calls per visitor session per day
_lock = threading.Lock()
_day = ""
_total = 0
_per: dict[str, int] = {}


def budget_ok(sid: str = "default") -> bool:
    """True and counts the call if both caps have room; False means use the template path instead."""
    global _day, _total, _per
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _lock:
        if today != _day:
            _day, _total, _per = today, 0, {}
        if _total >= DAILY_CAP or _per.get(sid, 0) >= SESSION_CAP:
            return False
        _total += 1
        _per[sid] = _per.get(sid, 0) + 1
        return True


def enabled() -> bool:
    return bool(os.environ.get("QWEN_API_KEY"))


def label() -> str:
    return f"Qwen ({os.environ.get('QWEN_MODEL', DEFAULT_MODEL)}) reads unclear questions" if enabled() else "off (template path)"


def parse_intent(text: str, client: httpx.Client | None = None, timeout: float = 15.0, sid: str = "default") -> str | None:
    """Return one intent from INTENTS or None (any failure falls back to the template path)."""
    if not enabled() or not budget_ok(sid):
        return None
    base = os.environ.get("QWEN_BASE_URL", DEFAULT_BASE).rstrip("/")
    body = {
        "model": os.environ.get("QWEN_MODEL", DEFAULT_MODEL),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Classify the user's message about a trader's own trade review into exactly one intent. "
                                           f"Allowed: {', '.join(INTENTS)}. Reply with JSON only: {{\"intent\": \"<one allowed value>\"}}."},
            {"role": "user", "content": text[:500]},
        ],
    }
    try:
        c = client or httpx.Client(timeout=timeout)
        r = c.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {os.environ['QWEN_API_KEY']}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        intent = json.loads(content).get("intent")
        return intent if intent in INTENTS else None
    except Exception:
        return None
