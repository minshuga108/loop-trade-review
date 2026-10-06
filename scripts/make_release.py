"""Make a clean release folder: tracked files only, one fresh commit, no old history, and a safety scan.

Usage: python scripts/make_release.py [target=../release/loop]
The scan refuses to finish if it finds a wallet-address-looking string, an API-key-looking string, or a
forbidden folder in what would be published. Run it, read the report, then push the target folder.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "release" / "loop"
FORBIDDEN_DIRS = (".claude", "data", ".venv", "__pycache__", ".pytest_cache")
FULL_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")
def _known_prefixes() -> set[str]:
    out: set[str] = set()
    d = ROOT.parent / "data"
    for folder in (d / "trader_samples", d / "cohort_raw" / "fills"):
        if folder.exists():
            out |= {f.stem[:10].lower() for f in folder.glob("0x*.csv")}
    return out
KNOWN = _known_prefixes()
KEYLIKE = [re.compile(p) for p in (r"sk-[A-Za-z0-9]{20,}", r"(?i)(api[_-]?key|secret|passphrase)\s*[:=]\s*['\"][A-Za-z0-9+/=_-]{16,}['\"]")]
TEXT_EXT = {".py", ".md", ".js", ".css", ".html", ".json", ".jsonl", ".txt", ".toml", ".yml", ".yaml", ".csv", ".cfg", ".ini", ""}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def main() -> int:
    files = tracked()
    problems: list[str] = []
    for f in files:
        parts = Path(f).parts
        if any(d in parts for d in FORBIDDEN_DIRS) and Path(f).name != ".gitignore":
            problems.append(f"forbidden path: {f}")
        if FULL_ADDR.search(f) or any(k in f.lower() for k in KNOWN):
            problems.append(f"address-like file name: {f}")
        p = ROOT / f
        if p.suffix.lower() in TEXT_EXT and p.is_file() and p.stat().st_size < 3_000_000:
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            low = txt.lower()
            hit = FULL_ADDR.search(txt) or next((k for k in KNOWN if k in low), None)
            if hit:
                problems.append(f"wallet address or prefix in {f}")
            for rx in KEYLIKE:
                if rx.search(txt):
                    problems.append(f"key-like text in {f}: pattern {rx.pattern[:20]}")
                    break
    if problems:
        print("RELEASE REFUSED. Fix these first:")
        for pr in problems[:50]:
            print(" -", pr)
        return 1
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    for f in files:
        dst = TARGET / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, dst)
    env = {"GIT_AUTHOR_NAME": "Loop", "GIT_AUTHOR_EMAIL": "loop@local", "GIT_COMMITTER_NAME": "Loop", "GIT_COMMITTER_EMAIL": "loop@local"}
    import os
    e = {**os.environ, **env}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=TARGET, check=True, env=e)
    subprocess.run(["git", "add", "-A"], cwd=TARGET, check=True, env=e)
    subprocess.run(["git", "commit", "-q", "-m", "Loop: trade review that tests its own rules (Bitget AI Hackathon S2, Review & Self-Evolution)"], cwd=TARGET, check=True, env=e)
    n = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=TARGET, capture_output=True, text=True).stdout.strip()
    print(f"Release folder ready: {TARGET}\n  files: {len(files)}  commits: {n} (fresh history)\n  scan: no address-like or key-like strings, no forbidden folders.\n  next: create an empty public GitHub repo, then in that folder: git remote add origin <url> && git push -u origin main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
