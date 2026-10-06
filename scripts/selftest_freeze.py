"""Run the 24 selftest sentences once and freeze the result as the public first run.

    python scripts/selftest_freeze.py

Writes eval/selftest_first_run.json only if it does not exist yet: the first run is
kept as it was, misses included, even after later fixes. No network (the book
refresher is not started and Qwen is forced off for the frozen run).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOOP_NO_REFRESH"] = "1"
os.environ.pop("QWEN_API_KEY", None)

from app import selftest  # noqa: E402


def main() -> int:
    if selftest.FIRST_RUN.exists():
        print(f"{selftest.FIRST_RUN} already exists; the first run is never overwritten.")
        return 1
    res = selftest.run_prompts()
    res["frozen"] = True
    res["note"] = ("First run of eval/selftest_prompts.jsonl, frozen. Template path only (Qwen off). "
                   "The prompts were written by an agent that had already read app/router.py, so this is not a blind score.")
    selftest.FIRST_RUN.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    s = res["summary"]
    print(f"trader {res['trader']}: {s['passed']}/{s['n']} passed, misses {s['misses']}, chat p50 {s['chat_ms']['p50']} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
