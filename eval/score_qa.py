"""Score the deterministic QA parser on eval/qa_questions.jsonl.

    python eval/score_qa.py dev        # the half the parser was built on
    python eval/score_qa.py heldout    # scored ONCE after building; result frozen in docs/QA.md

A row is exact when the parse kind matches and, for plan rows, the canonical compact plan
(defaults dropped) equals the expected one. Kind accuracy is reported too.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import qa  # noqa: E402

FILE = ROOT / "eval" / "qa_questions.jsonl"


def canon(p: dict) -> dict:
    return qa.QueryPlan.model_validate(p).compact()


def score(split: str) -> dict:
    rows = [json.loads(l) for l in FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r["split"] == split]
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses = []
    for r in rows:
        res = qa.parse(r["text"], r["previous"])
        exp = r["expected"]
        k_ok = res.kind == exp["kind"]
        good = k_ok and (exp["kind"] != "plan" or res.plan.compact() == canon(exp["plan"]))
        keys = ["all", f"lang={r['lang']}", f"kind={exp['kind']}"] + [f"tag={t}" for t in r.get("tags", []) if t in ("followup", "typo", "hinglish", "traditional")]
        for k in keys:
            groups[k][0] += good
            groups[k][1] += 1
        groups["kind_only"][0] += k_ok
        groups["kind_only"][1] += 1
        if not good:
            misses.append({"id": r["id"], "text": r["text"], "expected": exp, "got_kind": res.kind,
                           "got": res.plan.compact() if res.plan else res.reason})
    return {"split": split, "n": len(rows), "groups": dict(groups), "misses": misses}


def main(argv=None) -> int:
    split = (argv or sys.argv[1:] or ["dev"])[0]
    res = score(split)
    print(f"split={split} n={res['n']}")
    for k in sorted(res["groups"], key=lambda k: (k != "all", k)):
        ok, n = res["groups"][k]
        print(f"  {k:<18} {ok:>3}/{n:<3} {100 * ok / n:5.1f}%")
    for m in res["misses"]:
        print(f"MISS {m['id']} {m['text']!r}\n   expected {m['expected']}\n   got      {m['got_kind']} {m['got']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
