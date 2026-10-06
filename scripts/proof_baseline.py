"""Write proof_results.json for the /proof and /wrong pages.

Two real computations, nothing typed by hand:

1. BASELINE. The same planted traders the court suite uses (engine.suite.suite_trader, same seeds as
   scripts/run_suite.py: 10_000 * cell_index + sim), judged by a NAIVE in-sample rule check with no
   held-out data and no correction for the number of rules tried:
     - "saves money": the after-loss size cap would have saved dollars in-sample (always judged on all trades);
     - "p < 0.05": after-loss trades have a lower mean return per dollar than other trades, one-sided
       Welch t-test at 0.05 on the whole history.
   The court's own numbers for the same cells are read from suite_results.json (not re-run here). No other
   product's method is named or run.
2. ROUTER SETS. app.router.route_ex is scored on every question set in eval/ right now, and every miss kept.
   Each set is labelled blind or tuned: a set stops being blind the moment the router was changed using it.

    python scripts/proof_baseline.py            # ~1 minute, writes proof_results.json
    python scripts/proof_baseline.py --sims 50  # quicker
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import suite  # noqa: E402
from engine.detectors import after_loss_labels  # noqa: E402

OUT = ROOT / "proof_results.json"
ALPHA = 0.05

# first-scoring numbers are frozen in eval/*.md and quoted here with their file, because the sets were tuned after
FROZEN_FIRST = {
    "independent_blind": {"k": 146, "n": 200, "file": "eval/INDEPENDENT_RESULTS.md", "note": "first score, before any fix"},
    "independent_blind_2": {"k": 165, "n": 200, "file": "eval/INDEPENDENT_2_RESULTS.md", "note": "first score, before any fix"},
}
SETS = [
    ("dev_questions", "tuned", "Development set: the router was written against it."),
    ("blind_questions", "author-blind", "Written by the router's own author: shares its vocabulary, so it flatters it."),
    ("independent_blind", "tuned-after-first-score", "A different author. Blind on its first scoring only; the router was then fixed using its misses."),
    ("independent_blind_2", "tuned-after-first-score", "A second different author. Blind on its first scoring only; targeted Chinese patterns were added afterwards."),
]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def naive_verdicts(trips) -> dict:
    """Both naive judgements on the WHOLE history (no held-out split, no trial count)."""
    s = sorted(trips, key=lambda t: t.t_open_ms)
    lab = after_loss_labels(s)
    ret = np.array([t.net_pnl / t.opened_notional for t in s])
    notional = np.array([t.opened_notional for t in s])
    net = np.array([t.net_pnl for t in s])
    after = lab == 1
    if after.sum() < 3 or (~after).sum() < 3:
        return {"saves": False, "p05": False}
    med = float(np.median(notional))
    cap = np.where(after & (notional > 1.5 * med), 1.5 * med / notional, 1.0)
    saved = float(np.sum(net * (1 - cap)) * -1.0)          # dollars saved = losses avoided - gains given up
    t = stats.ttest_ind(ret[after], ret[~after], equal_var=False, alternative="less")
    return {"saves": saved > 0, "p05": bool(t.pvalue < ALPHA)}


def run_baseline(sims: int) -> list[dict]:
    cs = suite.cells()
    court = {s["cell"]: s for s in json.loads((ROOT / "suite_results.json").read_text(encoding="utf-8"))["summaries"]}
    rows = []
    for ci, c in enumerate(cs):
        if c.scenario != "STATIONARY":
            continue
        k_saves = k_p = 0
        for s in range(sims):
            v = naive_verdicts(suite.suite_trader(seed=10_000 * ci + s, **c.params))
            k_saves += v["saves"]
            k_p += v["p05"]
        cs_ = court.get(c.name)
        cap = cs_["rules"]["cap"]["accept"] if cs_ else None
        rows.append({
            "cell": c.name, "truth": c.truth, "sims": sims,
            "naive_saves_money": {"k": k_saves, "n": sims, "rate": k_saves / sims, "ci": wilson(k_saves, sims)},
            "naive_p_below_0_05": {"k": k_p, "n": sims, "rate": k_p / sims, "ci": wilson(k_p, sims)},
            "court_cap_accepts": ({"k": cap["k"], "n": cap["n"], "rate": cap["rate"], "ci": [cap["lo"], cap["hi"]]} if cap else None),
        })
        print(f"{c.name}: naive saves {k_saves}/{sims}, naive p<.05 {k_p}/{sims}, court {cap and cap['k']}/{cap and cap['n']}", flush=True)
    return rows


def run_router() -> list[dict]:
    from app import router
    out = []
    for name, label, why in SETS:
        rows = [json.loads(x) for x in (ROOT / "eval" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        misses, ok = [], 0
        for r in rows:
            got, _flags = router.route_ex(r["text"], r.get("previous_intent"))
            if got == r["intent"]:
                ok += 1
            else:
                misses.append({"text": r["text"], "gold": r["intent"], "got": got, "lang": r.get("lang")})
        d = {"set": name, "label": label, "why": why, "n": len(rows), "correct_now": ok, "ci_now": wilson(ok, len(rows)), "misses": misses}
        if name in FROZEN_FIRST:
            f = FROZEN_FIRST[name]
            d["first_score"] = {**f, "ci": wilson(f["k"], f["n"])}
        out.append(d)
        print(f"{name}: {ok}/{len(rows)} now", flush=True)
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sims = int(argv[argv.index("--sims") + 1]) if "--sims" in argv else 100
    t0 = time.time()
    doc = {
        "baseline": {
            "what": "Planted traders from engine/suite.py (stationary cells, 500 trips, same seeds as scripts/run_suite.py). "
                    "Naive checks use the whole history with no held-out data and no trial correction. Court numbers are copied "
                    "from suite_results.json (cap rule, walk-forward court, threshold 0.05/4 per rule).",
            "naive_rules": {"saves_money": "the after-loss cap would have saved dollars in-sample",
                            "p_below_0_05": "after-loss trades earn less per dollar than the rest, one-sided Welch t-test p < 0.05"},
            "cells": run_baseline(sims),
        },
        "router": {"sets": run_router()},
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print("wrote", OUT.name, f"in {doc['runtime_s']}s")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
