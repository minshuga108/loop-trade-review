"""Score app.router on all three question sets at once (dev, blind, independent).

Usage (from the repo root):
    python scripts/score_router_sets.py        # accuracy + confusion per set
    python scripts/score_router_sets.py -v     # also list every miss
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SETS = ("dev_questions", "blind_questions", "independent_blind")


def main(argv=None) -> int:
    from app import router

    argv = sys.argv[1:] if argv is None else argv
    verbose = "-v" in argv
    for name in SETS:
        rows = [json.loads(line) for line in open(ROOT / "eval" / f"{name}.jsonl", encoding="utf-8") if line.strip()]
        ok, conf, misses = 0, Counter(), []
        for r in rows:
            got, flags = router.route_ex(r["text"], r.get("previous_intent"))
            if got == r["intent"]:
                ok += 1
            else:
                conf[f"{r['intent']}->{got}"] += 1
                misses.append((r["intent"], got, r["text"], r.get("previous_intent"), flags))
        print(f"{name}: {ok}/{len(rows)} = {100 * ok / len(rows):.1f}%  confusion: {dict(conf.most_common())}")
        if verbose:
            for m in misses:
                print("   ", m)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
