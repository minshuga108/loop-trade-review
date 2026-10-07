"""Hostile-generator robustness suite: Loop's own false-flag rates under stresses it was not tuned for.

Run: python scripts/robustness_suite.py [sims_per_cell] [trips]
Planted traders only (SIM_PLANTED), built on engine.planted.planted_trader as the skeleton (times, holds, fees), then
rewritten with a stress. In every stress the trader has NO size-up-after-loss habit, so every flag and every accepted
rule is a wrong one. Writes robustness_results.json (all numbers and the rendered table come from this script).
Detectors: the four-test Holm family the app uses (size_after_loss, hold_asymmetry, overtrading_clusters,
revenge_reentry). Court: judge_wf on the 1.5x cap rule with a 4-proposal ledger, as in measure_court.py.
No other tool's code or numbers are run or quoted.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import detectors, detectors2  # noqa: E402
from engine.court import Court, Rule  # noqa: E402
from engine.planted import planted_trader  # noqa: E402
from engine.stats import holm  # noqa: E402
from engine.walkforward import judge_wf  # noqa: E402



def _arg(i: int, default: int) -> int:
    try:
        return int(sys.argv[i])
    except (IndexError, ValueError):       # also when imported under pytest
        return default


SIMS, N = _arg(1, 200), _arg(2, 300)
NOMINAL = 0.05
FAMILY = ("size_after_loss", "hold_asymmetry", "overtrading_clusters", "revenge_reentry")
STRESSES = ("baseline_null", "size_drift", "regime_shift", "autocorrelated_losses", "fat_tails", "all_four")
LABEL = {"baseline_null": "none (reference)", "size_drift": "persistent size drift (about 4.5x over the history)",
         "regime_shift": "regime shift at the midpoint (3x size, 3x volatility)", "autocorrelated_losses": "autocorrelated returns (AR(1), rho 0.6)",
         "fat_tails": "fat tails (Student t, 2 degrees of freedom)", "all_four": "all four together"}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def hostile_trader(stress: str, n: int, seed: int):
    """planted_trader (no size habit) as the skeleton, then rewrite sizes and returns under the stress."""
    base = planted_trader(n=n, size_mult=1.0, tilt=0.0, seed=seed)
    if stress == "baseline_null":
        return base
    g = np.random.default_rng(seed + 5_000_003)
    drift = stress in ("size_drift", "all_four")
    regime = stress in ("regime_shift", "all_four")
    ar = stress in ("autocorrelated_losses", "all_four")
    fat = stress in ("fat_tails", "all_four")
    sigma, mu, rho = 0.02, 0.0005, 0.6
    eps = g.standard_t(2, n) * (sigma / np.sqrt(2.0)) if fat else g.normal(0, sigma, n)   # t(2) rescaled to a comparable typical size
    out, prev = [], 0.0
    for i, t in enumerate(base):
        notional = t.first_order_notional
        sg = 1.0
        if drift:
            notional *= float(np.exp(1.5 * i / n))
        if regime and i >= n // 2:
            notional *= 3.0
            sg = 3.0
        r = mu + sg * eps[i]
        if ar:
            r = mu + rho * prev + np.sqrt(1 - rho ** 2) * sg * eps[i]
            prev = r - mu
        net = notional * float(r) - notional * 0.0005 * 2
        out.append(t.model_copy(update={"first_order_notional": notional, "opened_notional": notional, "net_pnl": net}))
    return out


def one_cell(stress: str) -> dict:
    raw = {d: 0 for d in FAMILY}
    adj = {d: 0 for d in FAMILY}
    any_adj = acc = under_court = 0
    for s in range(SIMS):
        trips = hostile_trader(stress, N, seed=424_242 + 17 * s)
        fs = detectors.run_all(trips, n_perm=300, seed=s) + detectors2.run_all(trips, n_perm=300, seed=s)
        ps = [1.0 if f.p != f.p else f.p for f in fs]
        ad = holm(ps)
        hit = False
        for f, a in zip(fs, ad):
            if f.status == "FLAGGED":
                raw[f.detector] += 1
                if a is not None and a < 0.05:
                    adj[f.detector] += 1
                    hit = True
        any_adj += hit
        c = Court(n_perm=300, seed=s)
        for m in (1.0, 1.5, 2.0, 3.0):
            c.propose(Rule(value=m))
        v = judge_wf(c, trips, Rule(value=1.5))
        acc += v.status == "ACCEPTED"
        under_court += v.status == "UNDERPOWERED"
    cell = {"stress": stress, "label": LABEL[stress], "sims": SIMS, "trips": N,
            "detectors": {d: {"flagged_raw": raw[d] / SIMS, "flagged_raw_ci": wilson(raw[d], SIMS),
                              "flagged_after_holm": adj[d] / SIMS, "flagged_after_holm_ci": wilson(adj[d], SIMS)} for d in FAMILY},
            "any_detector_after_holm": any_adj / SIMS, "any_detector_after_holm_ci": wilson(any_adj, SIMS),
            "court_wrong_acceptance": acc / SIMS, "court_wrong_acceptance_ci": wilson(acc, SIMS), "court_underpowered": under_court / SIMS}
    print(stress, f"any-after-Holm {cell['any_detector_after_holm']:.3f} court {cell['court_wrong_acceptance']:.3f}", flush=True)
    return cell


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def rendered(cells: list[dict]) -> tuple[str, list[str]]:
    rows = ["| Stress (truth: no size-up habit) | size after loss | hold asymmetry | overtrading | revenge re-entry | any, after Holm | court wrongly accepts |",
            "|---|---|---|---|---|---|---|"]
    fails = []

    def cf(ci, v):
        return f"{pct(v)} [{pct(ci[0])}, {pct(ci[1])}]"
    for c in cells:
        d = c["detectors"]
        rows.append(f"| {c['label']} | " + " | ".join(cf(d[k]["flagged_after_holm_ci"], d[k]["flagged_after_holm"]) for k in FAMILY) + " | "
                    + cf(c["any_detector_after_holm_ci"], c["any_detector_after_holm"]) + " | " + cf(c["court_wrong_acceptance_ci"], c["court_wrong_acceptance"]) + " |")
        for k in FAMILY:
            if d[k]["flagged_after_holm_ci"][0] > NOMINAL:
                fails.append(f"{k} under {c['stress'].replace('_', ' ')} ({pct(d[k]['flagged_after_holm'])})")
        if c["any_detector_after_holm_ci"][0] > NOMINAL:
            fails.append(f"family-wise flag under {c['stress'].replace('_', ' ')} ({pct(c['any_detector_after_holm'])})")
        if c["court_wrong_acceptance_ci"][0] > NOMINAL:
            fails.append(f"court under {c['stress'].replace('_', ' ')} ({pct(c['court_wrong_acceptance'])})")
    return "\n".join(rows), fails


def power_under_dependence(sims: int = 100, n: int = 600, rho: float = 0.6, tilt: float = -0.006) -> dict:
    """Does the dependence guard cost power? A REAL costly leak (3x size after a loss, worse returns after a loss) on top of AR(1) returns."""
    acc = det = 0
    for s in range(sims):
        base = planted_trader(n=n, size_mult=1.0, tilt=0.0, seed=777_000 + s)       # same sizes and times as the habit trader, before the habit
        g = np.random.default_rng(777_000 + s + 5_000_003)
        prev, loss_prev, out = 0.0, False, []
        for t in base:
            notional = t.first_order_notional * (3.0 if loss_prev else 1.0)          # the habit is aligned with the REAL loss sequence
            r = 0.0005 + rho * prev + np.sqrt(1 - rho ** 2) * g.normal(0, 0.02) + (tilt if loss_prev else 0.0)
            prev = r - 0.0005 - (tilt if loss_prev else 0.0)
            net = notional * float(r) - notional * 0.001
            loss_prev = net < 0
            out.append(t.model_copy(update={"first_order_notional": notional, "opened_notional": notional, "net_pnl": net}))
        c = Court(n_perm=300, seed=s)
        for m in (1.0, 1.5, 2.0, 3.0):
            c.propose(Rule(value=m))
        v = judge_wf(c, out, Rule(value=1.5))
        acc += v.status == "ACCEPTED"
        det += any("serial dependence" in x for x in v.notes)
    return {"sims": sims, "trips": n, "accepted": acc / sims, "accepted_ci": wilson(acc, sims), "dependence_detected": det / sims}


def before_scalars() -> dict:
    """The table and headline numbers of the FIRST version of this suite (single-label permutation court and detectors, expanding
    baseline), frozen in robustness_results_before.json so the before and after sit side by side in the docs."""
    p = ROOT / "robustness_results_before.json"
    if not p.exists():
        return {}
    b = json.loads(p.read_text(encoding="utf-8"))
    table, fails = rendered(b["cells"])
    stressed = [c for c in b["cells"] if c["stress"] != "baseline_null"]
    wa = max(stressed, key=lambda c: c["any_detector_after_holm"])
    wc = max(stressed, key=lambda c: c["court_wrong_acceptance"])
    ac = next(c for c in b["cells"] if c["stress"] == "autocorrelated_losses")
    al = next(c for c in b["cells"] if c["stress"] == "all_four")
    return {"before_table": table, "before_worst_any": f"{pct(wa['any_detector_after_holm'])} under {wa['stress'].replace('_', ' ')}",
            "before_worst_court": f"{pct(wc['court_wrong_acceptance'])} under {wc['stress'].replace('_', ' ')}",
            "before_ac_court": pct(ac["court_wrong_acceptance"]), "before_all_court": pct(al["court_wrong_acceptance"]),
            "before_all_any": pct(al["any_detector_after_holm"]), "before_n_failures": str(len(fails))}


def main() -> None:
    t0 = time.time()
    cells = [one_cell(s) for s in STRESSES]
    table, fails = rendered(cells)
    pw = power_under_dependence()
    print("power under dependence", pw, flush=True)
    stressed = [c for c in cells if c["stress"] != "baseline_null"]
    worst_any = max(stressed, key=lambda c: c["any_detector_after_holm"])
    worst_court = max(stressed, key=lambda c: c["court_wrong_acceptance"])
    worst_det = max(((c["stress"], k, c["detectors"][k]["flagged_after_holm"]) for c in stressed for k in FAMILY), key=lambda x: x[2])
    out = {"sims_per_cell": SIMS, "trips": N, "n_perm": 300, "holm_family": list(FAMILY), "nominal": NOMINAL,
           "court": "judge_wf (block permutation + dependence guard), 1.5x cap, 4-proposal ledger", "provenance": "SIM_PLANTED, planted_trader skeleton; no size-up habit planted, so every flag is false",
           "cells": cells, "power_under_dependence": pw, "table": table, "failures": fails,
           "scalars": {"sims": str(SIMS), "trips": str(N), "worst_any": f"{pct(worst_any['any_detector_after_holm'])} under {worst_any['stress'].replace('_', ' ')}",
                       "worst_court": f"{pct(worst_court['court_wrong_acceptance'])} under {worst_court['stress'].replace('_', ' ')}",
                       "worst_detector": f"{worst_det[1]} {pct(worst_det[2])} under {worst_det[0].replace('_', ' ')}",
                       "baseline_any": pct(cells[0]["any_detector_after_holm"]), "baseline_court": pct(cells[0]["court_wrong_acceptance"]),
                       "failures": "; ".join(fails) if fails else "none: no cell's 95% interval lies wholly above 5%",
                       "n_failures": str(len(fails)),
                       "ac_court": pct(next(c for c in cells if c["stress"] == "autocorrelated_losses")["court_wrong_acceptance"]),
                       "all_court": pct(next(c for c in cells if c["stress"] == "all_four")["court_wrong_acceptance"]),
                       "all_any": pct(next(c for c in cells if c["stress"] == "all_four")["any_detector_after_holm"]),
                       "dep_power": f"{pct(pw['accepted'])} (95% interval {pct(pw['accepted_ci'][0])} to {pct(pw['accepted_ci'][1])})",
                       "dep_power_trips": str(pw["trips"]), "dep_power_detected": pct(pw["dependence_detected"]),
                       **before_scalars()},
           "seconds": round(time.time() - t0)}
    (ROOT / "robustness_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(table, "\nFAILURES:", fails)


if __name__ == "__main__":
    main()
