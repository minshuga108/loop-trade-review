"""Send the weekly review digest for one trader to the configured chat channels (dry run if none).

Usage:  python scripts/push_weekly.py [trader=B] [--lang en|zh] [--link URL]
Schedule it with cron or a GitHub Actions workflow (see docs/PUSH.md). Needs no account access.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import service  # noqa: E402
from engine import push, report  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tid = args[0] if args else "B"
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
    link = sys.argv[sys.argv.index("--link") + 1] if "--link" in sys.argv else None
    rv = service.review(tid)
    key = f"push-{tid}"
    prev = report.previous_snapshot(key)
    built = report.build(rv, prev, lang)
    report.save_snapshot(key, built["facts"])
    text = push.summary_text(rv, built["markdown"], link, lang)
    print(text)
    print(push.send_weekly(text))


if __name__ == "__main__":
    main()
