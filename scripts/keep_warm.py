"""Optional keep-warm helper: GET /api/health on an interval from your own machine or scheduler.

This repo runs no pinger of its own. Usage:  python scripts/keep_warm.py [URL] [--every 600] [--once]
Render's free tier sleeps after ~15 minutes idle; a request every 10 minutes keeps the first screen fast.
Stop it with Ctrl+C. Read-only: it only calls GET /api/health.
"""
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claims  # noqa: E402


def ping(url: str) -> str:
    t0 = time.time()
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=60) as r:
            return f"{r.status} in {time.time() - t0:.1f}s"
    except Exception as e:                                   # report, keep going
        return f"failed ({e.__class__.__name__}) after {time.time() - t0:.1f}s"


def main(argv: list[str]) -> None:
    every = int(argv[argv.index("--every") + 1]) if "--every" in argv else 600
    urls = [a for a in argv if a.startswith("http")]
    url = urls[0] if urls else claims.LIVE_URL
    while True:
        print(time.strftime("%H:%M:%S"), url, ping(url), flush=True)
        if "--once" in argv:
            return
        time.sleep(max(every, 60))


if __name__ == "__main__":
    main(sys.argv[1:])
