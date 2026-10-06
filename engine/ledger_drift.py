"""Classify Bitget financial-records rows and reconcile them against a balance change.

Rows are the raw dicts of GET /api/v3/account/financial-records (fields id, type,
amount, fee, coin, ts, ...) or of the funding wallet's funding-financial-records
(id, coin, groupType, type, amount, balance, ts); see SCHEMA.md section 4.
All numbers arrive as strings and are summed as Decimals.

Reconciliation:
    explained = trade realised pnl - trade fees            (from fills / trips, the caller passes them)
              + FUNDING + LIQUIDATION_FEE + TRANSFER + REBATE_AIRDROP_OTHER   (classified rows)
    residual  = balance_change - explained                 -> reported as UNEXPLAINED when too large
TRADE rows (OPEN_*, CLOSE_*, *_DEAL, ...) are the ledger's own copy of the trades; they
are totalled as a cross-check only and NOT added, or trading would be counted twice.
UNCLASSIFIED rows are listed and left out of `explained`, so they surface in the residual.
The residual is never plugged into any category.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

# --- pre-registered constants (fixed before looking at any demo wallet; never tuned on them) ---
DEFAULT_THRESHOLD_FRAC = 0.001   # residual tolerated up to 0.1 percent of start equity (rounding, dust); configurable

# funding: the S5 regex from SCHEMA.md section 4, which also catches the undocumented RWA_CONTRACT_MAIN_* variant
FUNDING_RE = re.compile(r"(?:SETTLE_FEE|FUNDING).*USER_(?:IN|OUT)$")
TRADE_RE = re.compile(r"^(?:OPEN_(?:LONG|SHORT)|CLOSE_(?:LONG|SHORT)|BUY_DEAL|SELL_DEAL|FORCE_CLOSE_\w*|"
                      r"BURST_CLOSE_\w*|FIXED_ADL_CLOSE_\w*|ORDER_DEALT_\w*|ORDER_PLF_FEE_OUT)$")
LIQ_FEE_RE = re.compile(r"^LIQ_FEE$")
TRANSFER_RE = re.compile(r"(?:^|_)(?:TRANSFER|DEPOSIT|WITHDRAW)(?:_|$)", re.IGNORECASE)
TRANSFER_GROUPS = {"deposit", "withdraw", "transfer"}
OTHER_RE = re.compile(r"TRACE_SHARE_BENEFIT|REBATE|AIRDROP|BONUS|CASHBACK|COUPON|REWARD|VOUCHER", re.IGNORECASE)

CATEGORIES = ("FUNDING", "TRADE", "LIQUIDATION_FEE", "TRANSFER", "REBATE_AIRDROP_OTHER", "UNCLASSIFIED")
EXPLAINING = ("FUNDING", "LIQUIDATION_FEE", "TRANSFER", "REBATE_AIRDROP_OTHER")


def classify(row: dict) -> str:
    t = (row.get("type") or "").strip()
    tu = t.upper()
    if FUNDING_RE.search(tu):
        return "FUNDING"
    if TRADE_RE.match(tu):
        return "TRADE"
    if LIQ_FEE_RE.match(tu):
        return "LIQUIDATION_FEE"
    if TRANSFER_RE.search(tu) or (not t and (row.get("groupType") or "").lower() in TRANSFER_GROUPS):
        return "TRANSFER"
    if OTHER_RE.search(tu):
        return "REBATE_AIRDROP_OTHER"
    return "UNCLASSIFIED"


def _dec(x) -> Decimal:
    if x is None or x == "":
        return Decimal(0)
    try:
        return Decimal(str(x))
    except InvalidOperation as e:
        raise ValueError(f"not a number: {x!r}") from e


def row_amount(row: dict) -> Decimal:
    """Balance movement of one row: amount plus fee (fee is negative when charged; '0' on funding rows).
    [inferred] that `amount` excludes the row's fee, as documented for the spot transactions export."""
    return _dec(row.get("amount")) + _dec(row.get("fee"))


class Reconciliation(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str                          # RECONCILED | UNEXPLAINED
    totals: dict[str, float]             # per category, every category present
    counts: dict[str, int]
    trade_pnl: float
    trade_fees: float                    # positive = cost
    explained: float
    balance_change: float
    residual: float                      # balance_change - explained, never plugged
    threshold: float
    unclassified_types: list[str]
    duplicates_dropped: int
    detail: str


def reconcile(rows: list[dict], trade_pnl: float, trade_fees: float, balance_change: float, start_equity: float,
              threshold_frac: float = DEFAULT_THRESHOLD_FRAC, coin: str | None = None) -> Reconciliation:
    """Compare trading + classified non-trade events with a balance change. coin filters rows if given."""
    seen: set[str] = set()
    dup = 0
    totals = {c: Decimal(0) for c in CATEGORIES}
    counts = {c: 0 for c in CATEGORIES}
    unknown: set[str] = set()
    for r in rows:
        if coin is not None and r.get("coin") not in (None, "", coin):
            continue
        rid = r.get("id")
        if rid:
            if rid in seen:
                dup += 1
                continue
            seen.add(rid)
        c = classify(r)
        totals[c] += row_amount(r)
        counts[c] += 1
        if c == "UNCLASSIFIED":
            unknown.add(r.get("type") or "")
    explained = _dec(trade_pnl) - _dec(trade_fees) + sum((totals[c] for c in EXPLAINING), Decimal(0))
    residual = _dec(balance_change) - explained
    thr = abs(_dec(start_equity)) * _dec(threshold_frac)
    ok = abs(residual) <= thr
    detail = ("balance change explained within the threshold" if ok else
              f"UNEXPLAINED residual {float(residual):.8g} exceeds {float(thr):.8g} "
              f"({threshold_frac * 100:g}% of start equity); not assigned to any category")
    return Reconciliation(status="RECONCILED" if ok else "UNEXPLAINED",
                          totals={k: float(v) for k, v in totals.items()}, counts=counts,
                          trade_pnl=float(trade_pnl), trade_fees=float(trade_fees), explained=float(explained),
                          balance_change=float(balance_change), residual=float(residual), threshold=float(thr),
                          unclassified_types=sorted(unknown), duplicates_dropped=dup, detail=detail)
