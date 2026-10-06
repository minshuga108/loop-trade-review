"""Measure the court's false-admission rate and power on planted traders and write court_results.json.

Run: python scripts/measure_court.py [sims_per_cell]
Everything in README, LOSSES.md and the form text about the court is read from that file (see claims.py).
Planted traders only (SIM_PLANTED). The cap rule is judged by the walk-forward court with a 4-proposal ledger.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.court import Court, Rule  # noqa: E402
from engine.planted import planted_trader  # noqa: E402
from engine.stats import rng  # noqa: E402
from engine.walkforward import judge_wf  # noqa: E402

SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
SCEN = {"null": dict(size_mult=1.0, tilt=0.0), "costless_habit": dict(size_mult=3.0, tilt=0.0), "costly_leak": dict(size_mult=3.0, tilt=-0.006)}
SIZES = (60, 150, 300, 600)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> None:
    t0 = time.time()
    out = {"sims_per_cell": SIMS, "n_perm": 300, "proposals_in_ledger": 4, "threshold_per_rule": 0.05 / 4, "cells": []}
    for name, kw in SCEN.items():
        for n in SIZES:
            acc = under = 0
            for s in range(SIMS):
                trips = planted_trader(n=n, seed=9000 * n + s, **kw)
                c = Court(n_perm=300, seed=s)
                for m in (1.0, 1.5, 2.0, 3.0):
                    c.propose(Rule(value=m))
                v = judge_wf(c, trips, Rule(value=1.5))
                acc += v.status == "ACCEPTED"
                under += v.status == "UNDERPOWERED"
            lo, hi = wilson(acc, SIMS)
            out["cells"].append({"scenario": name, "trips": n, "accepted": acc / SIMS, "accepted_ci": [lo, hi], "underpowered": under / SIMS})
            print(f"{name:15s} n={n:4d} accepts {acc/SIMS:5.1%} [{lo:.1%}, {hi:.1%}] underpowered {under/SIMS:5.1%}", flush=True)
    out["seconds"] = round(time.time() - t0)
    (ROOT / "court_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
