"""Render README.md and SUBMISSION.md from their .template.md files using claims.py; --check fails on drift."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import claims  # noqa: E402

PAIRS = [("README.template.md", "README.md"), ("SUBMISSION.template.md", "SUBMISSION.md"),
         ("SELF_ASSESSMENT.template.md", "SELF_ASSESSMENT.md"),
         ("VALIDATION.template.md", "VALIDATION.md")]


def render(text: str, vals: dict[str, str]) -> str:
    missing = set(re.findall(r"\{\{([\w.]+)\}\}", text)) - set(vals)
    if missing:
        raise SystemExit(f"template uses unknown claims: {sorted(missing)}")
    return re.sub(r"\{\{([\w.]+)\}\}", lambda m: vals[m.group(1)], text)


def main(check: bool) -> None:
    vals = claims.values()
    bad = 0
    for tpl, out in PAIRS:
        rendered = render((ROOT / tpl).read_text(encoding="utf-8"), vals)
        path = ROOT / out
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                print(f"DRIFT: {out} does not match its template and the current numbers (run scripts/render_docs.py)")
                bad += 1
        else:
            path.write_text(rendered, encoding="utf-8")
            print("wrote", out)
    if check:
        if bad:
            sys.exit(1)
        print("claims check passed: docs match their templates and the numbers claims.py computes right now (live pytest collection, results files, app data)")


if __name__ == "__main__":
    main("--check" in sys.argv)
