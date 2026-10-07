"""Fetch Bitget PUBLIC 1H USDT-futures candles for equity perps and cache [t_ms, close] to tests/fixtures/equity_candles.

Run: python scripts/fetch_equity_candles.py SYM [SYM ...] [--from 2026-02-20] [--to 2026-09-30]
Source label for the chase detector: REAL_PLATFORM_PUBLIC candles (api.bitget.com history-candles). Symbols Bitget does not list
come back empty and are skipped; the detector then falls back to the trader's own fill prices and says so.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "equity_candles"
URL = "https://api.bitget.com/api/v2/mix/market/history-candles"


def ms(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch(base: str, t0: int, t1: int) -> list[list[float]]:
    rows: dict[int, float] = {}
    end = t1
    with httpx.Client(timeout=10) as c:
        while end > t0:
            r = c.get(URL, params=dict(symbol=f"{base}USDT", productType="USDT-FUTURES", granularity="1H", limit="200", endTime=str(end)))
            data = r.json().get("data") or []
            if not data:
                break
            for x in data:
                rows[int(x[0])] = float(x[4])
            first = min(int(x[0]) for x in data)
            if first >= end:
                break
            end = first - 1
            time.sleep(0.15)
    return [[t, rows[t]] for t in sorted(rows) if t >= t0]


def main() -> None:
    a = sys.argv[1:]
    t0, t1 = ms("2026-02-20"), ms("2026-09-30")
    syms = []
    while a:
        x = a.pop(0)
        if x == "--from":
            t0 = ms(a.pop(0))
        elif x == "--to":
            t1 = ms(a.pop(0))
        else:
            syms.append(x.upper())
    OUT.mkdir(parents=True, exist_ok=True)
    for s in syms:
        rows = fetch(s, t0, t1)
        if rows:
            (OUT / f"{s}.json").write_text(json.dumps({"symbol": f"{s}USDT", "granularity": "1H", "source": "bitget public history-candles",
                                                       "rows": rows}, separators=(",", ":")), encoding="utf-8")
        print(s, len(rows), flush=True)


if __name__ == "__main__":
    main()
