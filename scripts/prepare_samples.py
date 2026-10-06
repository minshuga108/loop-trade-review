"""Copy only the wallet histories the app uses into deploy_data/ for the Docker image.

    python scripts/prepare_samples.py [--src ../data/trader_samples] [--dst deploy_data/trader_samples]

What it does:
- copies only the CSVs named in app/service.py TRADERS (nothing else: summary.json
  holds full wallet addresses and is never copied);
- replaces the on-chain order ids (oid) with rank numbers that keep the same
  string order, so fills group and sort exactly as before but cannot be looked up;
- re-runs the ledger on the original and the copy and refuses to write if the
  fill, order or round-trip counts or the net P&L differ;
- writes SOURCES.md next to the files.

File names stay as the 8-hex-digit prefixes because app/service.py expects them;
the UI shows aliases (Wallet A, B, ...) and never a file name or address.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import hyperliquid_csv  # noqa: E402
from engine import ledger  # noqa: E402

DEFAULT_SRC = ROOT.parent / "data" / "trader_samples"
DEFAULT_DST = ROOT / "deploy_data" / "trader_samples"


def used_files() -> list[tuple[str, str, str]]:
    # read TRADERS without importing the app (keeps this script free of FastAPI)
    import ast
    tree = ast.parse((ROOT / "app" / "service.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TRADERS" for t in node.targets):
            rows = ast.literal_eval(node.value)
            return [(r["id"], r["file"], r["role"]) for r in rows if r["file"]]
    raise SystemExit("TRADERS not found in app/service.py")


def anonymise(text: str) -> str:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return text
    oids = sorted({r["oid"] for r in rows})                    # string order, as the ledger sorts exec ids
    width = len(str(len(oids)))
    rank = {o: str(i + 1).zfill(width) for i, o in enumerate(oids)}
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    for r in rows:
        r["oid"] = rank[r["oid"]]
        w.writerow(r)
    return out.getvalue()


def fingerprint(path: Path) -> tuple:
    fills = ledger.dedupe(hyperliquid_csv.load(path, account="x"))
    trips = ledger.to_round_trips(fills)
    return (len(fills), len(ledger.to_orders(fills)), len(trips), round(sum(t.net_pnl for t in trips), 6),
            tuple((t.t_open_ms, t.t_close_ms, round(t.first_order_notional, 6), round(t.net_pnl, 6)) for t in trips))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--dst", type=Path, default=DEFAULT_DST)
    a = ap.parse_args(argv)
    a.dst.mkdir(parents=True, exist_ok=True)
    lines = []
    for tid, fname, role in used_files():
        src = a.src / fname
        if not src.exists():
            print(f"missing: wallet {tid} ({role}) not found in {a.src}")
            return 1
        anon = anonymise(src.read_text(encoding="utf-8"))
        dst = a.dst / fname
        tmp = dst.with_suffix(".tmp")
        tmp.write_text(anon, encoding="utf-8", newline="")
        before, after = fingerprint(src), fingerprint(tmp)
        if before != after:
            tmp.unlink()
            print(f"refused: wallet {tid} changed after anonymising {before} -> {after}")
            return 1
        tmp.replace(dst)
        lines.append(f"| Wallet {tid} | {role} | {after[0]} | {after[2]} |")
        print(f"wallet {tid}: {after[0]} fills, {after[2]} round trips, identical before and after")
    (a.dst / "SOURCES.md").write_text(
        "# Trader samples shipped in the image\n\n"
        "Public Hyperliquid wallet fills (on-chain, public), hand-picked as illustrative examples. "
        "Not Bitget users and not the owner's account. Provenance label in the app: REAL_PLATFORM_PUBLIC.\n\n"
        "Anonymised by scripts/prepare_samples.py: only the wallets the app uses are copied; order ids are "
        "replaced by order-preserving rank numbers; the full addresses (in the source summary.json) are not shipped. "
        "The app shows aliases only. The ledger was re-run on each copy and matched the original exactly.\n\n"
        "| Alias | Role | Fills | Round trips |\n|---|---|---|---|\n" + "\n".join(lines) + "\n\n"
        "Wallet F in the app is simulated (SIM_PLANTED) and needs no file.\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
