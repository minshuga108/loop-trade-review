"""Walk financial-records rows that carry a running `balance` and find where the balance moved
by more than the row says (the input ledger_drift.reconcile needs, taken from the rows themselves).

For rows sorted by time: expected balance after row i = balance after row i-1 + amount + fee.
A row where the reported balance differs from that is listed with the gap; the gap is reported,
never assigned to a category. The balance before the first row is inferred from that row
(balance - amount - fee) and is labelled as inferred.
"""
from __future__ import annotations

from decimal import Decimal

from .ledger_drift import _dec, classify, row_amount


def walk(rows: list[dict]) -> dict:
    rs = sorted([r for r in rows if r.get("balance") not in (None, "")], key=lambda r: (int(r.get("ts") or 0), str(r.get("id"))))
    if not rs:
        return {"status": "NO_BALANCES", "rows": [], "start": None, "end": None, "gaps": []}
    start = _dec(rs[0]["balance"]) - row_amount(rs[0])
    prev = start
    out, gaps = [], []
    for r in rs:
        bal = _dec(r["balance"])
        exp = prev + row_amount(r)
        gap = bal - exp
        row = {"id": r.get("id"), "ts": int(r.get("ts") or 0), "type": r.get("type") or "", "group": r.get("groupType"),
               "category": classify(r), "amount": float(row_amount(r)), "balance": float(bal), "expected": float(exp),
               "gap": float(gap)}
        out.append(row)
        if gap != Decimal(0):
            gaps.append(row)
        prev = bal
    return {"status": "OK" if not gaps else "GAPS", "rows": out, "start": float(start), "start_inferred": True,
            "end": float(_dec(rs[-1]["balance"])), "gaps": gaps}
