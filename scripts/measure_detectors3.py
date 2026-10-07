"""Measure power and false-flag rate of the three stock-perp habit detectors on planted traders; writes detectors3_results.json.

Run: python scripts/measure_detectors3.py [sims_per_cell]
Planted traders only (SIM_PLANTED). "FLAGGED" here means the detector's own rule (p < 0.05, effect floor), before the Holm family
correction the app applies on top; `flagged_after_holm7` repeats the count with a 7-test family (the 4 shipped tests, p taken as
1, plus these 3) so the family-corrected rate is on the record too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import detectors3 as d  # noqa: E402
from engine import planted3 as p  # noqa: E402
from engine.stats import holm  # noqa: E402

SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
NPERM = 400


def wilson(k, n, z=1.96):
    q = k / n
    dd = 1 + z * z / n
    c = (q + z * z / (2 * n)) / dd
    h = z * ((q * (1 - q) / n + z * z / (4 * n * n)) ** 0.5) / dd
    return [max(0.0, c - h), min(1.0, c + h)]


def run(name, make, tilt):
    n = fl = fh = under = 0
    for s in range(SIMS):
        f = make(tilt, 31_000 + s)
        n += 1
        under += f.status == "UNDERPOWERED"
        fl += f.status == "FLAGGED"
        if f.p == f.p:
            adj = holm([f.p, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])[0]
            fh += (f.status == "FLAGGED" and adj < 0.05)
    return {"detector": name, "scenario": "habit_costly" if tilt else "habit_costless", "sims": n, "flagged": fl / n, "flagged_ci": wilson(fl, n),
            "flagged_after_holm7": fh / n, "underpowered": under / n}


def chase_candles(tilt, seed):
    tr, fills, c = p.planted_chase_trader(n=300, p_chase=0.5, tilt=tilt, seed=seed)
    return d.chase_after_move(tr, None, c, n_perm=NPERM, seed=seed)


def chase_own(tilt, seed):
    tr, fills, c = p.planted_chase_trader(n=300, p_chase=0.5, tilt=tilt, seed=seed)
    return d.chase_after_move(tr, fills, {}, n_perm=NPERM, seed=seed)


def chase_nohabit(tilt, seed):       # no habit at all: p_chase 0.16 is the chance share for a 1-sigma tail; tilt applies to the same label
    tr, fills, c = p.planted_chase_trader(n=300, p_chase=0.0, tilt=tilt, seed=seed)
    return d.chase_after_move(tr, None, c, n_perm=NPERM, seed=seed)


def off(tilt, seed):
    return d.off_hours_trading(p.planted_offhours_trader(n=300, p_off=0.7, tilt=tilt, seed=seed), n_perm=NPERM, seed=seed)


def avg(tilt, seed):
    tr, fills = p.planted_avgdown_trader(n=250, tilt=tilt, seed=seed)
    return d.averaging_down(tr, fills, n_perm=NPERM, seed=seed)


def main() -> None:
    out = {"sims_per_cell": SIMS, "n_perm": NPERM, "cells": []}
    for name, fn in (("chase_after_move[candles]", chase_candles), ("chase_after_move[own_fills]", chase_own),
                     ("chase_after_move[no_habit]", chase_nohabit), ("off_hours_trading", off), ("averaging_down", avg)):
        for tilt in (0.0, -0.01):
            c = run(name, fn, tilt)
            out["cells"].append(c)
            print(f"{name:30s} {c['scenario']:15s} flagged {c['flagged']:.1%} {c['flagged_ci']} holm7 {c['flagged_after_holm7']:.1%} under {c['underpowered']:.1%}", flush=True)
    (ROOT / "detectors3_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
