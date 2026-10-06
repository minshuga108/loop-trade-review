"""Checklist built from the trader's own record, with each item's effect measured.

Items come from flagged habits and armed rules. At most MAX_ACTIVE are stored and
at most MAX_SHOWN are shown before an order, chosen by relevance to that order.
An item whose effect can be measured is measured: trips that broke the item
versus trips that kept it (return on notional, within-trader permutation test).
An item is only PROPOSED for retirement once there is enough data to have seen a
useful effect and none was seen; the owner decides. Thresholds are pre-registered.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .court import Rule
from .detectors import after_loss_labels
from .schema import RoundTrip
from .stats import rng

MAX_ACTIVE, MAX_SHOWN = 5, 3
MIN_PER_GROUP = 20            # pre-registered: both groups need this many trades before any effect is stated
RETIRE_P = 0.3                # pre-registered: only proposed for retirement if p is above this at adequate n


@dataclass
class Item:
    item_id: str
    text: str
    source: str                 # finding id or rule id
    context: str                # when it is relevant: "after_loss" | "any"
    effect: dict = field(default_factory=dict)
    state: str = "ACTIVE"       # ACTIVE | PENDING_RETIREMENT


def generate(findings: list[dict], armed: list[tuple[str, Rule]]) -> list[Item]:
    items: list[Item] = []
    for rid, r in armed:
        items.append(Item(f"item-{rid}", f"Is the opening size above {r.value}x your median? (rule {rid}, only after a loss)", rid, "after_loss"))
    for f in findings:
        if f["status"] == "FLAGGED" and f["detector"] == "size_after_loss" and not any(i.context == "after_loss" for i in items):
            items.append(Item("item-size", "Last trade lost: is this order bigger than your usual size?", "size_after_loss", "after_loss"))
        if f["status"] == "FLAGGED" and f["detector"] == "hold_asymmetry":
            items.append(Item("item-hold", "Write the exit for a losing trade before you enter.", "hold_asymmetry", "any"))
    return items[:MAX_ACTIVE]


def measure(item: Item, trips: list[RoundTrip], median_notional: float, multiple: float = 1.5, n_perm: int = 3000, seed: int = 0) -> dict:
    """Effect of breaking the size item: net dollars per trade of after-loss trips above the cap versus at or below it.
    Dollars, not return per unit, because the item is about how much money rides on a trade after a loss."""
    if item.context != "after_loss":
        return {"status": "NOT_MEASURABLE", "reason": "this item cannot be checked from fills alone"}
    lab = after_loss_labels(trips)
    idx = [i for i in range(len(trips)) if lab[i] == 1 and trips[i].first_order_notional > 0]
    cap = multiple * median_notional
    ret = np.array([trips[i].net_pnl for i in idx])
    broke = np.array([trips[i].first_order_notional > cap for i in idx])
    n_b, n_k = int(broke.sum()), int((~broke).sum())
    if min(n_b, n_k) < MIN_PER_GROUP:
        return {"status": "NOT_ENOUGH_TRADES", "n_broke": n_b, "n_kept": n_k,
                "reason": f"needs {MIN_PER_GROUP} trades in each group (has {n_b} that broke it and {n_k} that kept it)"}
    obs = float(ret[~broke].mean() - ret[broke].mean())          # positive: keeping the item did better
    g = rng(seed)
    lab2, ge = broke.copy(), 0
    for _ in range(n_perm):
        g.shuffle(lab2)
        if ret[~lab2].mean() - ret[lab2].mean() >= obs - 1e-12:
            ge += 1
    p = (ge + 1) / (n_perm + 1)
    return {"status": "MEASURED", "n_broke": n_b, "n_kept": n_k, "better_when_kept": obs, "p": p,
            "retire_suggested": bool(p > RETIRE_P)}


def select_for_order(items: list[Item], after_loss: bool) -> list[Item]:
    """The items shown before an order: relevant ones first, never more than MAX_SHOWN."""
    rel = [i for i in items if i.context == "any" or (i.context == "after_loss" and after_loss)]
    return rel[:MAX_SHOWN]
