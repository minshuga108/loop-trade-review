"""Hand-written mutation testing: apply one small deliberate bug at a time, run the tests, restore.

    python scripts/mutate.py                 # all mutants, writes docs/stress/mutation_results.json
    python scripts/mutate.py --only M05 M16  # a subset

Each mutant is an exact, unique text replacement in one file. The original bytes are written back
in a `finally` block after every run (and checked byte-for-byte), so a crash or Ctrl-C mid-run still
leaves the tree clean; `git diff --stat` at the end must show nothing under engine/ or app/static/.
A mutant is KILLED when the test command fails, SURVIVED when it passes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
# Tests that fail on the unmutated tree are deselected (otherwise every mutant would look "killed" by
# them under -x); main() refuses to start unless the baseline run passes.
KNOWN_RED = ["--deselect", "tests/test_judge.py::test_losses_says_the_uncomfortable_parts"]
ENGINE_TESTS = ["tests", "--ignore=tests/test_browser.py", "-x", "-q", "-p", "no:cacheprovider", *KNOWN_RED]
BACKUP = ROOT / ".mutate_backup"                    # survives a hard kill; restored on the next start
BROWSER_TESTS = ["tests/test_browser.py", "-x", "-q", "-p", "no:cacheprovider"]

# (id, file, old, new, what, tests)
MUTANTS = [
    # ---- engine/court.py ------------------------------------------------------------------
    ("M01", "engine/court.py", "zip(trips, lab) if l == 0]", "zip(trips, lab) if l == 1]",
     "baseline taken from AFTER-loss trips (the habit inflates its own yardstick)", ENGINE_TESTS),
    ("M02", "engine/court.py", "alpha = self.alpha / max(self.trials, 1)", "alpha = self.alpha",
     "split court: no Bonferroni over the trial ledger", ENGINE_TESTS),
    ("M03", "engine/court.py", "if obs > 0 and p < alpha:", "if obs > 0 and p > alpha:",
     "split court: acceptance comparison flipped", ENGINE_TESTS),
    ("M04", "engine/court.py", "if te[\"n_trips\"] < self.min_test_trips or te[\"n_affected\"] < self.min_affected:",
     "if te[\"n_trips\"] < self.min_test_trips and te[\"n_affected\"] < self.min_affected:",
     "split court: underpowered guard needs both shortfalls (or -> and)", ENGINE_TESTS),
    ("M05", "engine/court.py", "        self.proposed.append(rule)", "        pass",
     "trial-count ledger never increments", ENGINE_TESTS),
    ("M06", "engine/court.py", "train, test = trips[:cut], trips[cut:]", "train, test = trips[:cut], trips[cut - 1:]",
     "off-by-one split: one trip is in both train and test", ENGINE_TESTS),
    ("M07", "engine/court.py", "base = _baseline(train)                       # fixed from the TRAIN window only",
     "base = _baseline(trips)", "look-ahead: baseline from the whole history incl. test", ENGINE_TESTS),
    ("M08", "engine/court.py", "return float(np.sum(pnl * (f - 1.0)))", "return float(np.sum(pnl * (1.0 - f)))",
     "effect sign flipped", ENGINE_TESTS),
    # ---- engine/walkforward.py -------------------------------------------------------------
    ("M09", "engine/walkforward.py", "base = _baseline(ts[:lo])", "base = _baseline(ts[:hi])",
     "walk-forward look-ahead guard skipped: baseline includes the judged chunk", ENGINE_TESTS),
    ("M10", "engine/walkforward.py", "alpha = court.alpha / max(court.trials, 1)", "alpha = court.alpha",
     "walk-forward: no Bonferroni over the trial ledger", ENGINE_TESTS),
    ("M11", "engine/walkforward.py", "if tot >= obs - 1e-9:", "if tot > obs + 1e9:",
     "walk-forward permutation never counts a null at least as good (p collapses)", ENGINE_TESTS),
    ("M12", "engine/walkforward.py", "if n_test < court.min_test_trips or n_aff < court.min_affected:",
     "if n_test < court.min_test_trips and n_aff < court.min_affected:",
     "walk-forward underpowered guard needs both shortfalls", ENGINE_TESTS),
    ("M13", "engine/walkforward.py", "lab_all[idx] == 1, rule.value * base))", "lab_all[idx] >= 0, rule.value * base))",
     "walk-forward applies the cap to every trip, not only after a loss", ENGINE_TESTS),
    # ---- engine/rulebook.py -----------------------------------------------------------------
    ("M14", "engine/rulebook.py", "if not approved_by or not approved_by.strip():", "if False:",
     "human-approval check dropped", ENGINE_TESTS),
    ("M15", "engine/rulebook.py", "\"REJECTED\": \"QUARANTINED\"", "\"REJECTED\": \"ACCEPTED\"",
     "a REJECTED rule lands as ACCEPTED, so it can be armed", ENGINE_TESTS),
    ("M16", "engine/rulebook.py", "        self.proposed_count += 1\n        rid", "        rid",
     "rulebook proposal counter not incremented", ENGINE_TESTS),
    ("M17", "engine/rulebook.py", "ACTIVE = (\"ARMED\", \"PENDING_RETIREMENT\")", "ACTIVE = (\"ARMED\",)",
     "a rule pending retirement stops guarding orders", ENGINE_TESTS),
    ("M18", "engine/rulebook.py", "        prev = \"GENESIS\"\n        for e in self.log:", "        return True\n        prev = \"GENESIS\"\n        for e in self.log:",
     "hash-chain verification always says intact", ENGINE_TESTS),
    ("M19", "engine/rulebook.py", "if v.status != \"ACCEPTED\":", "if v.status == \"REJECTED\":",
     "an UNDERPOWERED revision replaces the current version", ENGINE_TESTS),
    # ---- engine/gate.py -----------------------------------------------------------------------
    ("M20", "engine/gate.py", "if last_trip_was_loss and idea.notional > cap:", "if last_trip_was_loss and idea.notional < cap:",
     "gate cap comparison flipped", ENGINE_TESTS),
    ("M21", "engine/gate.py", "elif len(set(evidence)) >= 2:", "elif len(set(evidence)) >= 1:",
     "REVIEW_NEEDED on one evidence item instead of two", ENGINE_TESTS),
    ("M22", "engine/gate.py", "mult = {\"k\": 1e3,", "mult = {\"k\": 1.0,",
     "'20k' read as 20", ENGINE_TESTS),
    # ---- engine/numberlock.py -------------------------------------------------------------------
    ("M23", "engine/numberlock.py", "tol = 0.5 * 10 ** (-dec) + 1e-9", "tol = 0.5 * 10 ** (-dec) + 1.0",
     "number-lock tolerance widened by 1", ENGINE_TESTS),
    ("M24", "engine/numberlock.py", "        if val in allow:\n            continue", "        if True:\n            continue",
     "number-lock lets every numeral through", ENGINE_TESTS),
    # ---- app/static/index.html (escaping) --------------------------------------------------------
    ("M25", "app/static/index.html", "const esc = (s) => String(s == null ? \"\" : s).replace(",
     "const esc = (s) => String(s == null ? \"\" : s); const _unused = (s) => String(s).replace(",
     "HTML escaping removed from the first screen", BROWSER_TESTS),
]


def run_one(mid, rel, old, new, what, tests) -> dict:
    p = ROOT / rel
    orig = p.read_bytes()
    text = orig.decode("utf-8")
    if "\r\n" in text:                              # a Windows checkout: match the file's line endings
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    n = text.count(old)
    if n != 1:
        return {"id": mid, "file": rel, "what": what, "result": "NOT_APPLIED", "detail": f"snippet found {n} times"}
    t0 = time.time()
    BACKUP.mkdir(exist_ok=True)
    bk = BACKUP / rel.replace("/", "__")
    bk.write_bytes(orig)
    try:
        p.write_bytes(text.replace(old, new).encode("utf-8"))
        r = subprocess.run([PY, "-m", "pytest", *tests], cwd=ROOT, capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace")
        failed = r.returncode != 0
        tail = [ln for ln in r.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))][:3]
    finally:
        p.write_bytes(orig)
        assert p.read_bytes() == orig, f"{rel} was not restored"
        bk.unlink()
    return {"id": mid, "file": rel, "what": what, "result": "KILLED" if failed else "SURVIVED",
            "killed_by": tail, "seconds": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "docs" / "stress" / "mutation_results.json"))
    a = ap.parse_args(argv)
    if BACKUP.exists():                              # a previous run was killed mid-mutant: put the original back
        for bk in BACKUP.iterdir():
            (ROOT / bk.name.replace("__", "/")).write_bytes(bk.read_bytes())
            print("restored", bk.name)
            bk.unlink()
    base = subprocess.run([PY, "-m", "pytest", *ENGINE_TESTS], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if base.returncode != 0:
        print("baseline is red; fix or deselect first:\n" + base.stdout[-2000:])
        return 2
    rows = []
    for m in MUTANTS:
        if a.only and m[0] not in a.only:
            continue
        row = run_one(*m)
        rows.append(row)
        print(f"{row['id']} {row['result']:9} {row['file']:24} {row['what']}  {row.get('killed_by', '')}", flush=True)
    applied = [r for r in rows if r["result"] != "NOT_APPLIED"]
    killed = sum(r["result"] == "KILLED" for r in applied)
    summary = {"mutants": len(rows), "applied": len(applied), "killed": killed,
               "kill_rate": round(killed / len(applied), 3) if applied else None,
               "survivors": [r["id"] for r in applied if r["result"] == "SURVIVED"], "rows": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nkill rate {killed}/{len(applied)}; survivors: {summary['survivors']}")
    diff = subprocess.run(["git", "diff", "--stat", "--", "engine", "app/static"], cwd=ROOT, capture_output=True, text=True).stdout
    print("git diff engine/ app/static/:", diff.strip() or "clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
