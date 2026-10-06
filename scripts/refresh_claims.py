"""Run the test suite and store the pass count that README and the form quote."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True)
m = re.search(r"(\d+) passed", out.stdout)
failed = re.search(r"(\d+) failed", out.stdout)
if not m or failed:
    print(out.stdout[-1500:])
    sys.exit("tests did not all pass: claims not refreshed")
(ROOT / "claims_cache.json").write_text(json.dumps({"tests_passed": int(m.group(1))}), encoding="utf-8")
print("tests passed:", m.group(1))
