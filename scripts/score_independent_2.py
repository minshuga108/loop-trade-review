"""Score app.router on the independent blind set (eval/independent_blind_2.jsonl).

The set was written by a second author before reading app/router.py, so this
is a fairer estimate than eval/blind_questions.jsonl. Run once, record the
numbers in eval/INDEPENDENT_RESULTS.md, do not tune on it.

Usage (from the repo root):
    python scripts/score_independent.py            # human-readable report
    python scripts/score_independent.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SET = ROOT / "eval" / "independent_blind_2.jsonl"
INTENTS = ["habit", "rule", "court", "report", "source", "gate", "checklist", "help"]


def load(path: Path = SET) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def wilson(ok: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = ok / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def is_adversarial(r: dict) -> bool:
    return "adversarial" in r.get("note", "") and r["intent"] == "help"


def is_ambiguous(r: dict) -> bool:
    return "ambiguous" in r.get("note", "")


def evaluate(rows: list[dict]) -> dict:
    from app import router

    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses: list[dict] = []
    confusion: Counter = Counter()
    for r in rows:
        got, flags = router.route_ex(r["text"], r.get("previous_intent"))
        ok = got == r["intent"]
        keys = ["all", f"lang={r['lang']}", f"intent={r['intent']}"]
        if r.get("needs_context"):
            keys.append("needs_context")
        if is_adversarial(r):
            keys.append("adversarial")
        if is_ambiguous(r):
            keys.append("ambiguous")
        else:
            keys.append("unambiguous")
        for k in keys:
            groups[k][0] += ok
            groups[k][1] += 1
        if not ok:
            confusion[(r["intent"], got)] += 1
            misses.append({"gold": r["intent"], "got": got, "text": r["text"],
                           "lang": r["lang"], "previous_intent": r.get("previous_intent"),
                           "flags": flags, "note": r.get("note", "")})
    return {"groups": dict(groups), "misses": misses,
            "confusion": {f"{g}->{p}": c for (g, p), c in confusion.most_common()}}


def fmt_row(name: str, ok: int, n: int) -> str:
    lo, hi = wilson(ok, n)
    return f"  {name:<18} {ok:>3}/{n:<3} {100 * ok / n:5.1f}%   95% CI [{100 * lo:5.1f}, {100 * hi:5.1f}]"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = load()
    res = evaluate(rows)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0

    g = res["groups"]
    print(f"independent blind set  n={len(rows)}")
    print("overall")
    print(fmt_row("all", *g["all"]))
    print("per language")
    for k in ("lang=en", "lang=zh"):
        print(fmt_row(k, *g[k]))
    print("per intent")
    for i in INTENTS:
        k = f"intent={i}"
        if k in g:
            print(fmt_row(i, *g[k]))
    print("slices")
    for k in ("needs_context", "adversarial", "ambiguous", "unambiguous"):
        if k in g:
            print(fmt_row(k, *g[k]))
    print("confusion (gold->got: count)")
    for k, c in res["confusion"].items():
        print(f"  {k:<22} {c}")
    print("misses")
    for m in res["misses"]:
        ctx = f"  [prev={m['previous_intent']}]" if m["previous_intent"] else ""
        fl = f"  flags={m['flags']}" if m["flags"] else ""
        print(f"  {m['gold']:>9} -> {m['got']:<9} {m['text']}{ctx}{fl}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
