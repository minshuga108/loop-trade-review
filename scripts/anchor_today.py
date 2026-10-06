"""Anchor a day's record root with OpenTimestamps (the ONLY place this project uses the network for anchoring).

    python scripts/anchor_today.py                 # anchor today (UTC); submits once, later runs only upgrade
    python scripts/anchor_today.py --day 2026-10-06
    python scripts/anchor_today.py --upgrade-all   # fetch Bitcoin attestations for older receipts and check headers

Writes data/anchors/<day>.json (receipt) and data/anchors/<day>.ots (standard proof:
`ots verify -d <root> data/anchors/<day>.ots`). data/anchors is gitignored.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import anchor  # noqa: E402
from engine.record import RecordLog, utc_day  # noqa: E402


def urllib_transport(method, url, body, headers):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def report(receipt):
    v = anchor.verify_anchor(receipt["root"], receipt)
    print(json.dumps({"day": receipt["day"], "root": receipt["root"], "ok": v["ok"], "reason": v["reason"],
                      "calendars": [(c["url"], c["ok"], c.get("error")) for c in receipt["calendars"]],
                      "pending": [p["uri"] for p in v["pending"]], "bitcoin": v["bitcoin"], "proves": v["proves"]}, indent=1))
    for b in v["bitcoin"]:
        try:
            print("header check:", anchor.check_bitcoin_header(b, urllib_transport))
        except Exception as e:
            print("header check unavailable:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    ap.add_argument("--upgrade-all", action="store_true")
    a = ap.parse_args()
    folder = anchor.anchors_dir()
    if a.upgrade_all:
        for p in sorted(folder.glob("????-??-??.json")):
            r = anchor.upgrade(json.loads(p.read_text(encoding="utf-8")), urllib_transport)
            anchor.save_receipt(r, folder)
            report(r)
        return
    log = RecordLog()
    day = a.day or utc_day(int(time.time() * 1000))
    dr = log.day_root(day)
    existing = folder / f"{day}.json"
    if existing.exists():
        r = json.loads(existing.read_text(encoding="utf-8"))
        if r["root"] == dr["root"]:
            r = anchor.upgrade(r, urllib_transport)
            anchor.save_receipt(r, folder)
            report(r)
            return
        print(f"note: {day} root changed since the last anchor ({dr['n']} entries now); anchoring the new root as well")
        existing.rename(folder / f"{day}.{r['root'][:8]}.json")
    r = anchor.submit(dr["root"], urllib_transport, day=day)
    r["entries"], r["first_seq"], r["last_seq"], r["chain_head"] = dr["n"], dr["first_seq"], dr["last_seq"], dr["chain_head"]
    print("saved", anchor.save_receipt(r, folder))
    report(r)


if __name__ == "__main__":
    main()
