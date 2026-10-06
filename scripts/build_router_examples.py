"""Build app/router_examples.json, the training data of the router's char n-gram fallback.

Only the two sets the router author may study are used: eval/dev_questions.jsonl and
eval/independent_blind.jsonl (a dev set since Router v2). eval/blind_questions.jsonl
is deliberately excluded. Follow-up lines (needs_context) are skipped: they only make
sense with a previous intent.

Also prints a leave-one-out check of the fallback on the training lines whose keyword
score is below the floor (the only lines where the fallback can act).

Usage (from the repo root):
    python scripts/build_router_examples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCES = ("dev_questions.jsonl", "independent_blind.jsonl")
OUT = ROOT / "app" / "router_examples.json"


def main() -> int:
    rows = []
    for name in SOURCES:
        with open(ROOT / "eval" / name, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    if not r.get("needs_context"):
                        rows.append([r["text"], r["intent"]])
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} examples to {OUT.relative_to(ROOT)}")

    from app import router
    below = [(t, g) for t, g in rows if max(router.scores(t).values()) < router.FLOOR
             and not router.safety_flags(router.normalise(t))]
    ok = fired = 0
    for i, (t, g) in enumerate(below):
        others = [r for r in rows if r[0] != t]
        acc = {}
        for text, intent in others:
            acc.setdefault(intent, router.Counter()).update(router._unit(router._ngrams(router.normalise(text))))
        router._CENTROIDS = {k: router._unit(v) for k, v in acc.items()}
        p = router.centroid_pick(t)
        got = p if p and p != "help" else "help"
        fired += got != "help"
        ok += got == g
    router._CENTROIDS = None
    print(f"leave-one-out on {len(below)} below-floor training lines: {ok} correct, fallback fired {fired} times")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
