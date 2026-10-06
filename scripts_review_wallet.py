"""Run the review engine on one sampled public wallet CSV and print the findings.

Usage: python scripts_review_wallet.py deploy_data/trader_samples/wallet_C.csv
"""
from __future__ import annotations

import sys

from adapters import hyperliquid_csv
from engine import detectors, ledger
from engine.court import Court, Rule, price_rule


def review(path: str) -> None:
    fills = ledger.dedupe(hyperliquid_csv.load(path))
    orders = ledger.to_orders(fills)
    trips = ledger.to_round_trips(fills)
    print(f"{path}: {len(fills)} fills, {len(orders)} orders, {len(trips)} round trips "
          f"(provenance {fills[0].provenance.value})")
    for f in detectors.run_all(trips):
        ci = f"[{f.ci[0]:.2f}, {f.ci[1]:.2f}]" if f.ci[0] == f.ci[0] else "n/a"
        print(f"  {f.detector:16s} {f.status:12s} ratio={f.effect:.2f} ci={ci} p={f.p:.4f} n=({f.n_a},{f.n_b})  {f.detail}")
    court = Court()
    for m in (1.0, 1.5, 2.0, 3.0):
        court.propose(Rule(value=m))
    for r in list(court.proposed):
        v = court.judge(trips, r)
        priced = price_rule(trips, r)
        print(f"  rule cap={r.value}x median: {v.status:12s} test effect=${v.test['effect']:.0f} "
              f"(affected {v.test['n_affected']}/{v.test['n_trips']}) p={v.p:.4f} thr={v.alpha_used:.4f} | all-history effect=${priced['effect']:.0f} "
              f"[{priced['ci'][0]:.0f}, {priced['ci'][1]:.0f}]  {v.reason}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        review(p)
