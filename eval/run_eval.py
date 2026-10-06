"""Score an intent router on a question set.

Usage (from the repo root):
    python eval/run_eval.py                       # new router, dev set
    python eval/run_eval.py --set blind           # new router, blind set
    python eval/run_eval.py --router chat         # old keyword router in app/chat.py

The blind set is held out: it was written before either router was read and is
scored once, never tuned on. See eval/RESULTS.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SETS = {"dev": ROOT / "eval" / "dev_questions.jsonl", "blind": ROOT / "eval" / "blind_questions.jsonl"}


def load(name: str) -> list[dict]:
    with open(SETS[name], encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def get_router(name: str):
    if name == "chat":
        from app import chat
        return lambda text, prev: chat.route(text)          # old router has no context
    from app import router
    return lambda text, prev: router.route(text, previous_intent=prev)


def evaluate(rows: list[dict], fn) -> dict:
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses = []
    for r in rows:
        got = fn(r["text"], r.get("previous_intent"))
        ok = got == r["intent"]
        keys = ["all", f"lang={r['lang']}", f"intent={r['intent']}",
                f"needs_context={bool(r.get('needs_context'))}"]
        if r.get("adversarial"):
            keys.append("adversarial")
        if r.get("mixed") or r.get("hinglish"):
            keys.append("mixed/hinglish")
        for k in keys:
            groups[k][0] += ok
            groups[k][1] += 1
        if not ok:
            misses.append((r["intent"], got, r["text"], r.get("previous_intent")))
    return {"groups": dict(groups), "misses": misses}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="dev")
    ap.add_argument("--router", choices=["router", "chat"], default="router")
    a = ap.parse_args(argv)
    rows = load(a.set)
    res = evaluate(rows, get_router(a.router))
    print(f"router={a.router} set={a.set} n={len(rows)}")
    order = sorted(res["groups"], key=lambda k: (k != "all", k.split("=")[0], k))
    for k in order:
        ok, n = res["groups"][k]
        print(f"  {k:<28} {ok:>3}/{n:<3} {100 * ok / n:5.1f}%")
    print("confusions (gold -> got):")
    for gold, got, text, prev in sorted(res["misses"]):
        ctx = f"  [prev={prev}]" if prev else ""
        print(f"  {gold:>9} -> {got:<9} {text}{ctx}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
