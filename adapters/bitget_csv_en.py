"""Adapter for Bitget's website export "Export futures order history" (English).

Header verified from one real 2025 account (see data/bitget_samples/SOURCES.md):
Date, Order ID, Direction, Coin, Futures, order source, Transaction type, Price,
Average Price, Order amount, Executed, Trading volume, Realized P/L, NetProfits, Status

Facts that shape the code (all checked on that real file):
- This is an ORDER history, one row per order. Direction is "Open long", "Close long",
  "Open short" or "Close short".
- Realized P/L is gross; NetProfits = Realized P/L minus the CLOSE fee only. The opening
  fee appears nowhere in the file, so net figures overstate by it. That is reported in
  `notes`, never silently filled in.
- Date is a local wall-clock string with no zone; the zone follows the account setting, so
  the caller passes it (default 0 = treat as UTC) and the notes say it is unverified.
An unexpected header raises SchemaDrift. Rows that never filled are skipped.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.schema import Fill, Provenance

from .bitget_uta import SchemaDrift

REQUIRED = ("Date", "Order ID", "Direction", "Futures", "Average Price", "Executed", "Realized P/L", "NetProfits", "Status")
DIRECTIONS = {"open long": ("buy", True, "long"), "close long": ("sell", False, "long"),
              "open short": ("sell", True, "short"), "close short": ("buy", False, "short")}


def _f(x: str) -> float:
    if x is None or x.strip() == "":
        return 0.0
    try:
        v = float(x)
    except ValueError:
        raise SchemaDrift(f"not a number: {x[:40]!r}") from None
    if not math.isfinite(v):
        raise SchemaDrift(f"non-finite number {x[:40]!r}")
    return v


def parse(path: str | Path, account: str = "csv-export", tz_offset_hours: float = 0.0,
          provenance: Provenance = Provenance.REAL_PLATFORM_PUBLIC) -> tuple[list[Fill], dict]:
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (rd.fieldnames or [])]
        if missing:
            raise SchemaDrift(f"export header changed: missing {missing}; got {rd.fieldnames}")
        rows = list(rd)
    for i, r in enumerate(rows, start=2):                  # a short row has None cells; a long one has a None key
        if None in r or any(r.get(c) is None for c in REQUIRED):
            raise SchemaDrift(f"row {i} has the wrong number of cells")
    tz = timezone(timedelta(hours=tz_offset_hours))
    rows.sort(key=lambda r: (r["Date"], r["Order ID"].strip("\t")))
    pos: dict[tuple[str, str], float] = {}
    fills: list[Fill] = []
    skipped = 0
    for r in rows:
        status = (r["Status"] or "").lower()
        executed = _f(r["Executed"])
        if executed <= 0 or "cancel" in status:
            skipped += 1
            continue
        d = DIRECTIONS.get((r["Direction"] or "").strip().lower())
        if d is None:
            raise SchemaDrift(f"unknown Direction {r['Direction']!r}")
        side, is_open, leg = d
        sym = r["Futures"].strip().upper()
        key = (sym, leg)
        start = pos.get(key, 0.0)
        pos[key] = start + executed if is_open else start - executed
        gross, net = _f(r["Realized P/L"]), _f(r["NetProfits"])
        fee = round(gross - net, 10) if not is_open else 0.0          # close fee; open fee is not in the file
        try:
            t = datetime.strptime(r["Date"].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        except ValueError:
            raise SchemaDrift(f"unreadable Date {r['Date'][:40]!r}") from None
        oid = r["Order ID"].strip("\t ")
        fills.append(Fill(venue="bitget", account=account, exec_id=oid, order_id=oid, t_ms=int(t.timestamp() * 1000),
                          symbol=f"{sym}:{leg}", side=side, is_open=is_open, price=_f(r["Average Price"]), size=executed,
                          fee=fee, realized_pnl=gross, start_position=start, provenance=provenance))
    notes = {"rows": len(rows), "orders_used": len(fills), "skipped_unfilled": skipped,
             "open_fees_missing": True, "timezone": f"UTC{tz_offset_hours:+g} assumed, unverified",
             "unflattened_positions": {f"{k[0]}:{k[1]}": v for k, v in pos.items() if abs(v) > 1e-9}}
    return fills, notes
