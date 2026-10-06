"""Record public Bitget order-book snapshots to JSONL (REPLAY_NATIVE corpus builder).

Public GET /api/v3/market/orderbook only: no key, no orders. Not run in tests.

  python scripts/capture_books.py --symbols RNVDAUSDT,RAAPLUSDT --seconds 120 --interval 10
  python scripts/capture_books.py --symbols NVDAUSDT --category USDT-FUTURES --seconds 600

One line per snapshot:
  {"t_local_ms", "t_local_iso", "symbol", "category", "limit", "latency_ms", "data": {a, b, ts}}
or {"...", "error": "..."} when a call fails (the gap is recorded, never back-filled).
Read back with engine.market.books_from_jsonl(path).

Default output goes under data/snapshots/ (gitignored). Snapshots are point-in-time;
the cadence you pick is the cadence you get (requests are sequential, so a long
symbol list stretches each round). Keep it polite: Bitget public market limits are
per IP; the default interval of 10 s over a handful of symbols is far below them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = "https://api.bitget.com/api/v3/market/orderbook"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", required=True, help="comma separated, e.g. RNVDAUSDT,RAAPLUSDT")
    ap.add_argument("--category", default="SPOT", choices=["SPOT", "USDT-FUTURES"])
    ap.add_argument("--seconds", type=float, default=120.0, help="total run time")
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between rounds")
    ap.add_argument("--limit", type=int, default=200, help="levels per side (documented max 200)")
    ap.add_argument("--out", default=None, help="JSONL path (default data/snapshots/books_<utc>.jsonl)")
    a = ap.parse_args(argv)

    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.out) if a.out else ROOT / "data" / "snapshots" / f"books_{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    n_ok = n_err = 0
    t_end = time.monotonic() + a.seconds
    with httpx.Client(timeout=10.0) as c, open(out, "a", encoding="utf-8") as f:
        while True:
            t_round = time.monotonic()
            for s in syms:
                t0 = time.time()
                rec = {"t_local_ms": int(t0 * 1000),
                       "t_local_iso": dt.datetime.fromtimestamp(t0, dt.timezone.utc).isoformat(timespec="milliseconds"),
                       "symbol": s, "category": a.category, "limit": a.limit}
                try:
                    r = c.get(URL, params={"category": a.category, "symbol": s, "limit": str(a.limit)})
                    body = r.json()
                    rec["latency_ms"] = int((time.time() - t0) * 1000)
                    if str(body.get("code")) != "00000":
                        rec["error"] = f"code {body.get('code')}: {body.get('msg')}"
                    else:
                        rec["data"] = body.get("data") or {"a": [], "b": [], "ts": None}
                except Exception as e:                       # network hiccup: record the gap honestly
                    rec["error"] = f"{type(e).__name__}: {e}"
                if "error" in rec:
                    n_err += 1
                else:
                    n_ok += 1
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                f.flush()
            if time.monotonic() >= t_end:
                break
            time.sleep(max(0.0, a.interval - (time.monotonic() - t_round)))
    print(f"wrote {n_ok} snapshots ({n_err} errors) to {out}")
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
