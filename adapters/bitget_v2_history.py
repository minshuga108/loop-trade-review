"""Bitget mix v2 'history-position' rows (one row per closed position) -> RoundTrip.

Row shape (real, from a public MPL-2.0 trading journal): positionId, symbol, holdSide, openAvgPrice,
openTotalPos, pnl (gross), netProfit, totalFunding, openFee and closeFee (both stored NEGATIVE),
ctime and utime in integer milliseconds. Identity checked on every row:
    netProfit = pnl + openFee + closeFee + totalFunding
A mismatch means the convention changed, so the row is refused loudly instead of guessed.
Rows without pnl and fees (typed in by hand) are skipped and counted in parse.skipped.
Journal extras (entryReason, remark) are returned separately and never enter the statistics.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.bitget_uta import SchemaDrift, _f, _ms
from engine.schema import Provenance, RoundTrip

NEED = ("positionId", "symbol", "holdSide", "openAvgPrice", "openTotalPos", "pnl", "netProfit", "ctime", "utime")


def parse(rows: list[dict[str, Any]], provenance: Provenance = Provenance.REAL_PLATFORM_PUBLIC):
    """Return (trips, notes) where notes maps first_order_id -> {entry_reason, remark}."""
    trips: list[RoundTrip] = []
    notes: dict[str, dict[str, str]] = {}
    skipped = {"hand_entered": 0}
    for r in rows:
        if not isinstance(r, dict):
            raise SchemaDrift("position row is not an object")
        if r.get("type") == "summery" or str(r.get("exchange", "bitget")) != "bitget":
            continue
        if "pnl" not in r and "openFee" not in r:      # hand-entered journal row: no fees, no real timestamps -> never counted
            skipped["hand_entered"] += 1
            continue
        missing = [k for k in NEED if k not in r]
        if missing:
            raise SchemaDrift(f"position row is missing {missing}")
        gross, net = _f(r["pnl"]), _f(r["netProfit"])
        fees = _f(r.get("openFee")) + _f(r.get("closeFee"))
        funding = _f(r.get("totalFunding"))
        if abs(net - (gross + fees + funding)) > 0.01:
            raise SchemaDrift(f"position {r['positionId']}: netProfit {net} != pnl {gross} + fees {fees} + funding {funding}")
        opened = _f(r["openAvgPrice"]) * _f(r["openTotalPos"])
        pid = str(r["positionId"])
        trips.append(RoundTrip(symbol=str(r["symbol"]).upper(), t_open_ms=_ms(r["ctime"]), t_close_ms=_ms(r["utime"]),
                               side="buy" if str(r["holdSide"]).lower() == "long" else "sell",
                               first_order_notional=opened, opened_notional=opened, net_pnl=net,
                               first_order_id=pid, provenance=provenance))
        if r.get("entryReason") or r.get("remark"):
            notes[pid] = {"entry_reason": str(r.get("entryReason") or ""), "remark": str(r.get("remark") or "").strip()}
    parse.skipped = skipped
    return sorted(trips, key=lambda t: t.t_open_ms), notes


def load(path: str | Path, provenance: Provenance = Provenance.REAL_PLATFORM_PUBLIC):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SchemaDrift("expected a JSON list of position rows")
    return parse(data, provenance)
