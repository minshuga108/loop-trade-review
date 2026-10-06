"""Adapter for the sampled public Hyperliquid wallet CSVs (data/trader_samples).

Columns: time_ms, coin, side, dir, px, sz, fee, closedPnl, startPosition, oid.
Side is B or A. These are public on-chain fills of someone else, so the label
is REAL_PLATFORM_PUBLIC, never REAL_OWN.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

from engine.schema import Fill, Provenance


COLUMNS = ("time_ms", "coin", "side", "dir", "px", "sz", "fee", "closedPnl", "startPosition", "oid")


class BadRow(ValueError):
    """A row that does not have the documented columns or numbers."""


def _num(row: dict, k: str) -> float:
    try:
        v = float(row[k])
    except ValueError:
        raise BadRow(f"{k} is not a number: {row[k][:40]!r}") from None
    if not math.isfinite(v):
        raise BadRow(f"{k} is not finite: {row[k][:40]!r}")
    return v


def load(path: str | Path, account: str | None = None) -> list[Fill]:
    path = Path(path)
    account = account or path.stem
    fills: list[Fill] = []
    with path.open(newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (rd.fieldnames or [])]
        if missing:
            raise BadRow(f"missing columns {missing}")
        for i, row in enumerate(rd):
            if None in row or any(row.get(c) is None for c in COLUMNS):
                raise BadRow(f"row {i + 2} has the wrong number of cells")
            if row["side"] not in ("B", "A"):
                raise BadRow(f"row {i + 2}: side must be B or A")
            try:
                t_ms = int(row["time_ms"])
            except ValueError:
                raise BadRow(f"row {i + 2}: time_ms is not an integer") from None
            d = row["dir"]
            pnl = _num(row, "closedPnl")
            is_open = d.startswith("Open") or (not d.startswith("Close") and pnl == 0.0)
            fills.append(
                Fill(
                    venue="hyperliquid",
                    account=account,
                    exec_id=f"{row['oid']}-{i}",
                    order_id=row["oid"],
                    t_ms=t_ms,
                    symbol=row["coin"],
                    side="buy" if row["side"] == "B" else "sell",
                    is_open=is_open,
                    price=_num(row, "px"),
                    size=_num(row, "sz"),
                    fee=_num(row, "fee"),
                    realized_pnl=pnl,
                    start_position=_num(row, "startPosition"),
                    provenance=Provenance.REAL_PLATFORM_PUBLIC,
                )
            )
    return fills
