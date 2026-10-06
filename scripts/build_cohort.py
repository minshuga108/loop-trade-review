"""Build the public Hyperliquid cohort (pre-registered rule in COHORT_NOTES.md section 2).

    python scripts/build_cohort.py [--raw ../data/cohort_raw] [--max-kept 60] [--max-tried 400]

Read-only, keyless POSTs to the documented info endpoint, at most 2 requests per second and a rolling
weight budget of half the documented limit. HTTP 429 stops the run at once; the run is resumable
because every fetched wallet is cached.

Everything that holds an address stays under the raw folder (outside git):
  leaderboard.json            snapshot (downloaded once if missing)
  fills/<address>.csv         every fetched candidate, same columns as data/trader_samples
  kept/W001.csv ...           the kept wallets, renamed to ordinal ids
  progress.json               candidates tried, in draw order, with the address -> W id mapping
Nothing this script writes inside the repo contains an address.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import hyperliquid_csv  # noqa: E402
from engine import ledger  # noqa: E402

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
DEFAULT_RAW = ROOT.parent / "data" / "cohort_raw"
if not DEFAULT_RAW.parent.exists():          # worktrees sit two levels deeper than the main checkout
    DEFAULT_RAW = Path(r"C:\Users\neon_\bitget\data\cohort_raw")

# ---- pre-registered constants (COHORT_NOTES.md section 2; do not tune) ----
SEED = 20261006
MIN_ACCOUNT_VALUE = 1_000.0
MIN_ALLTIME_VLM, MAX_ALLTIME_VLM = 1e6, 5e8
MIN_MONTH_VLM = 1e5
N_STRATA = 5
PER_STRATUM_CAP = 12
MIN_TRIPS = 60
MAX_PAGES = 5
COLUMNS = ["time_ms", "coin", "side", "dir", "px", "sz", "fee", "closedPnl", "startPosition", "oid"]

# ---- etiquette ----
MIN_INTERVAL_S = 0.5            # at most 2 requests per second
WEIGHT_BUDGET = 600             # per rolling 60 s; the documented limit is 1200
RETRIES = 3


class RateLimited(RuntimeError):
    pass


# ------------------------------------------------------------------ sampling (pure, unit-tested)

def _perf(row: dict) -> dict:
    return {k: v for k, v in row["windowPerformances"]}


def eligible(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        try:
            av = float(r["accountValue"])
            w = _perf(r)
            vl, mv, pnl = float(w["allTime"]["vlm"]), float(w["month"]["vlm"]), float(w["allTime"]["pnl"])
        except (KeyError, TypeError, ValueError):
            continue
        if av >= MIN_ACCOUNT_VALUE and MIN_ALLTIME_VLM <= vl <= MAX_ALLTIME_VLM and mv >= MIN_MONTH_VLM:
            out.append({"addr": r["ethAddress"].lower(), "pnl": pnl, "account_value": av, "vlm": vl})
    return out


def draw_order(elig: list[dict], seed: int = SEED, n_strata: int = N_STRATA) -> list[tuple[int, dict]]:
    """Quintiles of all-time pnl, shuffled within stratum, interleaved round-robin. Returns (stratum, row)."""
    elig = sorted(elig, key=lambda r: (r["pnl"], r["addr"]))
    strata = [list(s) for s in np.array_split(np.arange(len(elig)), n_strata)]
    g = np.random.default_rng(seed)
    queues = []
    for s in strata:
        s = list(s)
        g.shuffle(s)
        queues.append([elig[i] for i in s])
    out, k = [], 0
    while any(k < len(q) for q in queues):
        for si, q in enumerate(queues):
            if k < len(q):
                out.append((si + 1, q[k]))
        k += 1
    return out


def count_trips(path: Path) -> int:
    fills = ledger.dedupe(hyperliquid_csv.load(path, account="x"))
    return len(ledger.to_round_trips(fills))


# ------------------------------------------------------------------ network

class Client:
    def __init__(self) -> None:
        import httpx
        self.http = httpx.Client(timeout=60.0, headers={"Content-Type": "application/json"})
        self.last = 0.0
        self.window: deque[tuple[float, int]] = deque()
        self.requests = 0

    def _wait(self, need: int) -> None:
        while True:
            now = time.time()
            while self.window and now - self.window[0][0] > 60:
                self.window.popleft()
            used = sum(w for _, w in self.window)
            gap = MIN_INTERVAL_S - (now - self.last)
            if used + need <= WEIGHT_BUDGET and gap <= 0:
                return
            time.sleep(max(gap, 0.5 if used + need > WEIGHT_BUDGET else 0))

    def info(self, body: dict) -> list | dict:
        delay = 2.0
        for attempt in range(RETRIES + 1):
            self._wait(120)
            self.last = time.time()
            self.requests += 1
            try:
                r = self.http.post(INFO_URL, json=body)
            except Exception as e:  # network error: back off and retry
                if attempt == RETRIES:
                    raise
                print(f"  network error {type(e).__name__}, retry in {delay:.0f}s", flush=True)
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 429:
                raise RateLimited("HTTP 429 from the info endpoint: stopping as pre-registered")
            if r.status_code >= 500:
                if attempt == RETRIES:
                    r.raise_for_status()
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            data = r.json()
            n = len(data) if isinstance(data, list) else 0
            self.window.append((time.time(), 20 + (n + 19) // 20))
            return data
        raise RuntimeError("unreachable")


def fetch_fills(client: Client, addr: str) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    start = 0
    for _ in range(MAX_PAGES):
        page = client.info({"type": "userFillsByTime", "user": addr, "startTime": start, "aggregateByTime": False})
        if not page:
            break
        new = [f for f in page if (f.get("tid"), f.get("oid"), f.get("time")) not in seen]
        for f in new:
            seen.add((f.get("tid"), f.get("oid"), f.get("time")))
        out.extend(new)
        last = max(int(f["time"]) for f in page)
        if len(page) < 2000:
            break
        start = last if new else last + 1      # same-ms fills at the boundary are re-read and deduped
    out.sort(key=lambda f: (int(f["time"]), f.get("tid", 0)))
    return out


def write_csv(path: Path, fills: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for f in fills:
            w.writerow([f["time"], f["coin"], f["side"], f["dir"], f["px"], f["sz"], f["fee"], f["closedPnl"],
                        f["startPosition"], f["oid"]])
    tmp.replace(path)


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--max-kept", type=int, default=60)
    ap.add_argument("--max-tried", type=int, default=400)
    a = ap.parse_args(argv)
    raw = a.raw
    (raw / "fills").mkdir(parents=True, exist_ok=True)
    (raw / "kept").mkdir(parents=True, exist_ok=True)
    lb = raw / "leaderboard.json"
    if not lb.exists():
        import httpx
        print("downloading leaderboard snapshot", flush=True)
        r = httpx.get(LEADERBOARD_URL, timeout=300.0)
        if r.status_code == 429:
            raise RateLimited("HTTP 429 on leaderboard")
        r.raise_for_status()
        lb.write_bytes(r.content)
    rows = json.loads(lb.read_text(encoding="utf-8"))["leaderboardRows"]
    elig = eligible(rows)
    order = draw_order(elig)
    print(f"leaderboard rows {len(rows)}, eligible {len(elig)}", flush=True)

    prog_path = raw / "progress.json"
    prog = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else {"tried": []}
    done = {t["addr"]: t for t in prog["tried"]}
    kept_per = {s: 0 for s in range(1, N_STRATA + 1)}
    for t in prog["tried"]:
        if t["kept"]:
            kept_per[t["stratum"]] += 1
    client = Client()

    def save() -> None:
        prog["leaderboard_rows"], prog["eligible"] = len(rows), len(elig)
        tmp = prog_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prog, indent=1), encoding="utf-8")
        tmp.replace(prog_path)

    tried = len(prog["tried"])
    try:
        for stratum, row in order:
            n_kept = sum(kept_per.values())
            if n_kept >= a.max_kept or tried >= a.max_tried:
                break
            if all(v >= PER_STRATUM_CAP for v in kept_per.values()):
                break
            addr = row["addr"]
            if addr in done:
                continue
            if kept_per[stratum] >= PER_STRATUM_CAP:
                continue
            path = raw / "fills" / f"{addr}.csv"
            if not path.exists():
                write_csv(path, fetch_fills(client, addr))
            n_fills = sum(1 for _ in path.open(encoding="utf-8")) - 1
            n_trips = count_trips(path) if n_fills > 0 else 0
            kept = n_trips >= MIN_TRIPS
            rec = {"addr": addr, "stratum": stratum, "n_fills": n_fills, "n_trips": n_trips, "kept": kept,
                   "pnl_alltime": row["pnl"], "account_value": row["account_value"], "vlm_alltime": row["vlm"]}
            tried += 1
            if kept:
                kept_per[stratum] += 1
                wid = f"W{sum(kept_per.values()):03d}"
                rec["wid"] = wid
                shutil.copyfile(path, raw / "kept" / f"{wid}.csv")
            prog["tried"].append(rec)
            done[addr] = rec
            save()
            print(f"tried {tried:3d} Q{stratum} fills {n_fills:5d} trips {n_trips:5d} "
                  f"{'KEPT ' + rec['wid'] if kept else 'skip'}  kept/stratum {kept_per}  requests {client.requests}",
                  flush=True)
    except RateLimited as e:
        save()
        print(str(e), flush=True)
        return 2
    save()
    print(f"done: tried {tried}, kept {sum(kept_per.values())} {kept_per}, requests {client.requests}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
