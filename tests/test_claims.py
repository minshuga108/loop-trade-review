import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_number_in_the_docs_matches_the_code():
    out = subprocess.run([sys.executable, "scripts/render_docs.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
