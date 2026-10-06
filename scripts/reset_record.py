"""Archive the development record and start an empty one (run once, right before launch).

Usage: python scripts/reset_record.py
Moves data/record/* to data/record_archive_<timestamp>/ (kept locally, never published) so the public counter
starts honest on launch day. Anchors for the archived days are kept in the archive too.
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.record import default_path  # noqa: E402

p = Path(default_path())
folder = p.parent
if not p.exists():
    print("no record file at", p, "- nothing to reset")
    sys.exit(0)
dest = folder.parent / f"record_archive_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
dest.mkdir(parents=True)
for f in folder.iterdir():
    if f.name != ".gitignore":
        shutil.move(str(f), str(dest / f.name))
print(f"archived {p.name} and friends to {dest}; the public record now starts empty")
