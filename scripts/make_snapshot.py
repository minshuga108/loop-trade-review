"""Pre-render the first-screen API answers into app/static/snapshot.json (commit the result).

The first screen falls back to this file, with a banner, when /api calls fail (cold start, outage).
Run: python scripts/make_snapshot.py
"""
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import service  # noqa: E402

OUT = ROOT / "app" / "static" / "snapshot.json"
RULES = ("cap", "halt")


def build() -> dict:
    traders = [t for t in service.traders("snapshot") if t.get("role") != "import"]
    snap = {"generated": datetime.date.today().isoformat(), "traders": traders, "review": {}, "toggle": {}}
    for t in traders:
        tid = t["id"]
        snap["review"][tid] = service.review(tid)
        for rule in RULES:
            snap["toggle"][f"{tid}|{rule}"] = service.toggle(tid, rule, 2)
    return snap


def main() -> None:
    snap = build()
    OUT.write_text(json.dumps(snap, default=str, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(snap['traders'])} traders, {snap['generated']})")


if __name__ == "__main__":
    main()
