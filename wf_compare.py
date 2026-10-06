"""Measure false admission and power: single split court vs walk-forward court (planted traders)."""
import sys
import time

from engine.court import Court, Rule
from engine.planted import planted_trader
from engine.walkforward import judge_wf

SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
rows = []
t0 = time.time()
for name, kw in (("null", dict(size_mult=1.0, tilt=0.0)), ("costless", dict(size_mult=3.0, tilt=0.0)),
                 ("costly", dict(size_mult=3.0, tilt=-0.006))):
    for n in (150, 300, 600):
        a_split = a_wf = u_wf = 0
        for s in range(SIMS):
            trips = planted_trader(n=n, seed=5000 * n + s, **kw)
            c1 = Court(n_perm=300, seed=s)
            c2 = Court(n_perm=300, seed=s)
            for m in (1.0, 1.5, 2.0, 3.0):
                c1.propose(Rule(value=m))
                c2.propose(Rule(value=m))
            a_split += c1.judge(trips, Rule(value=1.5)).status == "ACCEPTED"
            v = judge_wf(c2, trips, Rule(value=1.5))
            a_wf += v.status == "ACCEPTED"
            u_wf += v.status == "UNDERPOWERED"
        rows.append((name, n, a_split / SIMS, a_wf / SIMS, u_wf / SIMS))
        print(f"{name:9s} n={n:4d} split accepts {a_split/SIMS:5.0%} | walk-forward accepts {a_wf/SIMS:5.0%} underpowered {u_wf/SIMS:5.0%}", flush=True)
print("seconds", round(time.time() - t0))
