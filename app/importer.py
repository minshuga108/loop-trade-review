"""Bring-your-own-export: parse a pasted or uploaded history in memory, for this session only.

Accepted layouts (auto-detected from the header, anything else is refused with a plain message):
- Bitget website CSV 'Export futures order history' (English): Date, Order ID, Direction, Futures, ...
- Hyperliquid fills CSV: time_ms, coin, side, dir, px, sz, fee, closedPnl, startPosition, oid
Nothing is stored on disk and nothing is sent anywhere; a visitor's history lives in memory for the session.
Limits: 2 MB, 30,000 data rows.
"""
from __future__ import annotations

import os
import tempfile

from adapters import bitget_csv_en, hyperliquid_csv
from adapters.bitget_uta import SchemaDrift
from engine.schema import Provenance

MAX_BYTES = 2_000_000
MAX_ROWS = 30_000


class ImportRefused(ValueError):
    pass


def detect(text: str) -> str:
    head = text.lstrip("﻿ \t\r\n").split("\n", 1)[0].lower()
    if "order id" in head and "direction" in head and "futures" in head:
        return "bitget_csv_en"
    if "time_ms" in head and "closedpnl" in head:
        return "hyperliquid_csv"
    raise ImportRefused("I could not recognise this file. Supported: the Bitget website 'Export futures order history' CSV "
                        "(English columns) or a Hyperliquid fills CSV. Nothing was stored.")


def parse(text: str, sid: str):
    """Return (fills, note). Raises ImportRefused with a user-readable message on any problem."""
    if len(text.encode("utf-8", errors="ignore")) > MAX_BYTES:
        raise ImportRefused("The file is larger than 2 MB. Nothing was stored.")
    if text.count("\n") > MAX_ROWS + 5:
        raise ImportRefused("The file has more than 30,000 rows. Nothing was stored.")
    kind = detect(text)
    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if kind == "bitget_csv_en":
            fills, notes = bitget_csv_en.parse(path, account=f"import-{sid[:8]}", provenance=Provenance.REAL_OWN)
            note = "Bitget website export read. Opening fees are not in this format, so net results overstate by them. Time zone assumed UTC, unverified."
        else:
            fills = [f.model_copy(update={"provenance": Provenance.REAL_OWN}) for f in hyperliquid_csv.load(path, account=f"import-{sid[:8]}")]
            note = "Hyperliquid fills read."
    except (SchemaDrift, hyperliquid_csv.BadRow, ValueError) as e:
        raise ImportRefused(f"I could not read this file: {str(e)[:200]}. Nothing was stored.") from None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not fills:
        raise ImportRefused("No filled orders were found in this file. Nothing was stored.")
    return fills, note
