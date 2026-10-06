"""Run the planted-rule suite and write SUITE_RESULTS.md (and suite_results.json) with the measured table.

Usage: python scripts/run_suite.py [sims_per_cell=100] [budget_seconds=3600] [workers=8]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import suite  # noqa: E402


def main() -> None:
    sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 3600.0
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    res = suite.run_suite(sims=sims, budget_s=budget, workers=workers, progress=lambda m: print(m, flush=True))
    (ROOT / "SUITE_RESULTS.md").write_text(suite.to_markdown(res), encoding="utf-8")
    (ROOT / "suite_results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"wrote SUITE_RESULTS.md in {res['runtime_s']:.0f}s")


if __name__ == "__main__":
    main()
