"""Planted-rule suite: false-admission and power of the detector and the court.

Run: python selftest_suite.py [sims_per_cell]
All histories are SIM_PLANTED. The table is written to SELFTEST_RESULTS.md with
the numbers exactly as measured; losses are printed, not hidden.
"""
from __future__ import annotations

import sys
import time

from engine import detectors
from engine.court import Court, Rule
from engine.planted import planted_trader

SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
SCENARIOS = {
    "null (no leak)": dict(size_mult=1.0, tilt=0.0),
    "costless habit (sizes up 3x after a loss, no extra loss)": dict(size_mult=3.0, tilt=0.0),
    "costly leak (sizes up 3x and does worse after a loss)": dict(size_mult=3.0, tilt=-0.006),
}
SIZES = (60, 150, 300, 600)


def main() -> None:
    t0 = time.time()
    rows = []
    for name, kw in SCENARIOS.items():
        for n in SIZES:
            flagged = accepted = under = 0
            for s in range(SIMS):
                trips = planted_trader(n=n, seed=1000 * n + s, **kw)
                if detectors.size_after_loss(trips, n_perm=300, seed=s).status == "FLAGGED":
                    flagged += 1
                court = Court(n_perm=300, seed=s)
                for m in (1.0, 1.5, 2.0, 3.0):          # four proposals counted in the ledger
                    court.propose(Rule(value=m))
                v = court.judge(trips, Rule(value=1.5))
                accepted += v.status == "ACCEPTED"
                under += v.status == "UNDERPOWERED"
            rows.append((name, n, flagged / SIMS, accepted / SIMS, under / SIMS))
            print(f"{name[:40]:40s} n={n:4d} detector flags {flagged/SIMS:5.0%}  court accepts {accepted/SIMS:5.0%}  underpowered {under/SIMS:5.0%}", flush=True)
    out = ["# Planted-rule suite (SIM_PLANTED), measured results", "",
           f"{SIMS} simulated traders per cell, 300 permutations, 4 proposals in the trial ledger (threshold 0.05/4), "
           f"run in {time.time()-t0:.0f}s. Fraction of simulated traders for which:", "",
           "| scenario | trips | detector flags size habit | court ACCEPTS the cap rule | court says UNDERPOWERED |",
           "|---|---|---|---|---|"]
    for name, n, f, a, u in rows:
        out.append(f"| {name} | {n} | {f:.0%} | {a:.0%} | {u:.0%} |")
    out += ["", "Reading: on the null the court must accept about 0 percent (false admission). On the costless habit the detector "
            "may flag but the court must not accept (a habit that does not cost money is not a leak). On the costly leak, power "
            "rises with sample size and is low at small n; that is why UNDERPOWERED is the normal answer at 40-80 trades."]
    open("SELFTEST_RESULTS.md", "w", encoding="utf-8").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
