"""Claims registry: every number quoted in README.md and SUBMISSION.md comes from here.

Each claim has an id, a human description, the command that reproduces it, and a
function that reads the real artefact or runs the real code. Templates use
{{id}}; scripts/render_docs.py fills them; scripts/check_claims.py fails if a
rendered file differs from what the code says today (so a number cannot drift).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Public links quoted in README.md and SUBMISSION.md (single source; no placeholders in rendered docs)
LIVE_URL = "https://loop-trade-review.onrender.com"
REPO_URL = "https://github.com/minshuga108/loop-trade-review"
VIDEO_URL = LIVE_URL + "/video"


def _court(scenario: str, trips: int, key: str = "accepted") -> float:
    data = json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))
    for c in data["cells"]:
        if c["scenario"] == scenario and c["trips"] == trips:
            return c[key]
    raise KeyError((scenario, trips))


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _cache(key: str):
    p = ROOT / "claims_cache.json"
    if not p.exists():
        raise FileNotFoundError("run scripts/refresh_claims.py first")
    return json.loads(p.read_text(encoding="utf-8"))[key]


def _router_blind() -> str:
    txt = (ROOT / "eval" / "RESULTS.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*Blind, single frozen run: (\d+)/(\d+) = ([\d.]+)%\*\*", txt)
    return f"{m.group(1)} of {m.group(2)}"


def _router_independent() -> str:
    txt = (ROOT / "eval" / "INDEPENDENT_RESULTS.md").read_text(encoding="utf-8")
    m = re.search(r"\| \*\*all\*\* \| (\d+)/(\d+) \| \*\*([\d.]+)%\*\*", txt)
    return f"{m.group(1)} of {m.group(2)} ({m.group(3)}%)"


def _ind2():
    txt = (ROOT / "eval" / "INDEPENDENT_2_RESULTS.md").read_text(encoding="utf-8")
    first = re.search(r"all\s+(\d+)/(\d+)\s+([\d.]+)%", txt)
    after = re.search(r"all (\d+)/(\d+) ([\d.]+)% \(was (\d+)/(\d+) ([\d.]+)%\)", txt)
    if not first or not after or (first.group(1), first.group(3)) != (after.group(4), after.group(6)):
        raise ValueError("INDEPENDENT_2_RESULTS.md: first-score and after-tuning lines not found or inconsistent")
    return first, after


def _router_independent2() -> str:
    f, _ = _ind2()
    return f"{f.group(1)} of {f.group(2)} ({f.group(3)}%)"


def _router_independent2_after() -> str:
    _, a = _ind2()
    return f"{a.group(1)} of {a.group(2)} ({a.group(3)}%)"


def _mcp_tools() -> str:
    from app import mcp_server
    names = [t["name"] for t in mcp_server.TOOLS] if hasattr(mcp_server, "TOOLS") else []
    return str(len(names))


def _habit_tests() -> str:
    from app import service
    return str(len(service.review("A")["findings"]))


def _wallets() -> str:
    """Wallets with a real history file (Hyperliquid A-E plus the Bitget export). Kept for the count; use wallets.text in prose."""
    from app import service
    return str(sum(1 for t in service.TRADERS if t["file"] is not None))


def _real_traders():
    from app import service
    hl = [t for t in service.TRADERS if t["file"] is not None and t["role"] != "real_bitget"
          and not str(t["file"]).startswith(("bitget_csv:", "journal:"))]
    bg = [t for t in service.TRADERS if t["role"] == "real_bitget"]
    return hl, bg


def _wallets_text() -> str:
    hl, bg = _real_traders()
    return f"{len(hl)} public Hyperliquid wallets plus {len(bg)} Bitget futures export (a trading bot's account, not a human trader)"


def _real_acceptance() -> str:
    from app import service
    hl, bg = _real_traders()
    accepted, tested = [], 0
    for t in hl + bg:
        c = service.review(t["id"]).get("court") or {}
        tested += c.get("tested", 0)
        acc = [v for v in c.get("verdicts", []) if v.get("status") == "ACCEPTED"]
        if acc:
            accepted.append((t["id"], len(acc), c.get("proposed", 0), acc))
    n = len(hl) + len(bg)
    if not accepted:
        return f"On the {n} real wallets the court accepted none of the {tested} rules it tested."
    parts = []
    for tid, k, prop, acc in accepted:
        eff = ", ".join(f"{v['rule'].replace('cap opening size at ', 'cap at ').replace(' your median after a loss', ' median after a loss')} (held-out effect {'+' if v['held_out_effect']>=0 else '-'}${abs(v['held_out_effect']):,.0f})" for v in acc)
        parts.append(f"wallet {tid} had {k} of {prop} proposed rules accepted: {eff}")
    rest = n - len(accepted)
    return (f"On the {n} real wallets the court accepted at least one rule on {len(accepted)} ({'; '.join(parts)}) "
            f"and accepted none on the other {rest}; the remaining proposals were rejected or underpowered")


def _tests_collected() -> str:
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+) tests? collected", out.stdout) or re.search(r"^(\d+) tests?", out.stdout, re.M)
    if not m:
        m = re.search(r"(\d+)/\d+ tests collected|(\d+) tests", out.stdout)
    if not m:
        raise RuntimeError("could not read pytest collection count: " + out.stdout[-500:])
    return next(g for g in m.groups() if g)


SUMMARY = ("Your Bitget fills in. Your costly habits priced in dollars, court-tested on your own trades, "
           "armed as rules before your next order.")


def _evidence_rows():
    p = ROOT / "evidence" / "bitget_calls.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _signal_ta() -> str:
    rows = [r for r in _evidence_rows() if r["source"] == "bitget-signal"]
    ta = [r for r in rows if r["operation"].startswith("technical-analysis")]
    ta_ok = [r for r in ta if r["ok"]]
    syms = {r["operation"].split()[2] for r in ta_ok}
    srv = [r for r in rows if not r["operation"].startswith(("technical-analysis", "mcp:", "initialize", "notifications/", "tools/"))]
    srv_ok = sum(1 for r in srv if r["ok"])
    return (f"bitget-signal technical-analysis (the skill's own indicator code run locally on Bitget public candles) answered "
            f"{len(ta_ok)} of {len(ta)} logged calls on {len(syms)} symbols; its hosted data skills (sentiment, news, macro) "
            f"answered {srv_ok} of {len(srv)} logged data calls (evidence/bitget_calls.jsonl, /evidence)")


CLAIMS: dict[str, dict] = {
    "court.fa_null_600": {"desc": "court wrongly accepts a rule on a trader with no leak, 600 trips", "cmd": "python scripts/measure_court.py",
                          "fn": lambda: _pct(_court("null", 600))},
    "court.fa_costless_600": {"desc": "court wrongly accepts a costless habit, 600 trips", "cmd": "python scripts/measure_court.py",
                              "fn": lambda: _pct(_court("costless_habit", 600))},
    "court.power_150": {"desc": "court accepts a real costly leak, 150 trips", "cmd": "python scripts/measure_court.py",
                        "fn": lambda: _pct(_court("costly_leak", 150))},
    "court.power_300": {"desc": "court accepts a real costly leak, 300 trips", "cmd": "python scripts/measure_court.py",
                        "fn": lambda: _pct(_court("costly_leak", 300))},
    "court.power_600": {"desc": "court accepts a real costly leak, 600 trips", "cmd": "python scripts/measure_court.py",
                        "fn": lambda: _pct(_court("costly_leak", 600))},
    "court.sims": {"desc": "simulated traders per cell", "cmd": "python scripts/measure_court.py",
                   "fn": lambda: str(json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))["sims_per_cell"])},
    "router.blind": {"desc": "chat router, frozen blind run (author-written set)", "cmd": "see eval/RESULTS.md", "fn": _router_blind},
    "router.independent": {"desc": "chat router on an independent author's set, scored once", "cmd": "python scripts/score_independent.py", "fn": _router_independent},
    "router.independent2": {"desc": "chat router v2 on a second independent set, FIRST score (before any tuning on it)", "cmd": "python scripts/score_independent_2.py", "fn": _router_independent2},
    "router.independent2_after": {"desc": "same second set re-scored after we tuned zh patterns on its misses (not blind any more)", "cmd": "eval/INDEPENDENT_2_RESULTS.md", "fn": _router_independent2_after},
    "tests.collected": {"desc": "automated tests collected by pytest right now", "cmd": "python -m pytest --collect-only -q", "fn": _tests_collected},
    "url.live": {"desc": "public live demo URL", "cmd": "claims.LIVE_URL", "fn": lambda: LIVE_URL},
    "url.repo": {"desc": "public repo URL", "cmd": "claims.REPO_URL", "fn": lambda: REPO_URL},
    "url.video": {"desc": "demo video page URL", "cmd": "claims.VIDEO_URL", "fn": lambda: VIDEO_URL},
    "summary.text": {"desc": "one-line summary", "cmd": "claims.SUMMARY", "fn": lambda: SUMMARY},
    "summary.chars": {"desc": "characters in the one-line summary", "cmd": "len(claims.SUMMARY)", "fn": lambda: str(len(SUMMARY))},
    "evidence.signal": {"desc": "what bitget-signal calls are logged", "cmd": "evidence/bitget_calls.jsonl", "fn": _signal_ta},
    "wallets.text": {"desc": "wallet composition", "cmd": "GET /api/traders", "fn": _wallets_text},
    "court.real_acceptance": {"desc": "rules accepted on real wallets", "cmd": "GET /api/review/{A..E,G}", "fn": _real_acceptance},
    "habit.tests": {"desc": "habit tests run on every trader", "cmd": "GET /api/review/A (findings)", "fn": _habit_tests},
    "wallets.real": {"desc": "real public wallets in the demo", "cmd": "GET /api/traders", "fn": _wallets},
    "mcp.tools": {"desc": "read-only MCP tools", "cmd": "POST /mcp tools/list", "fn": _mcp_tools},
}


def _vr() -> dict:
    p = ROOT / "validation_results.json"
    if not p.exists():
        raise FileNotFoundError("run scripts/crosscheck_stats.py then scripts/run_validation.py first")
    return json.loads(p.read_text(encoding="utf-8"))


# Validation numbers: every one is computed by scripts/crosscheck_stats.py or scripts/run_validation.py and stored in
# validation_results.json (dev-only tooling); VALIDATION.template.md and the README/SUBMISSION links quote them from here.
_VAL_SCALARS = {
    "p_agree": "detector permutation p-values that agree with scipy.stats.permutation_test",
    "ci_agree": "detector bootstrap CIs that agree with scipy.stats.bootstrap within the declared tolerance",
    "holm_agree": "shipped Holm-adjusted p-values that agree with statsmodels",
    "holm_random_maxdiff": "largest Holm difference vs statsmodels on random p-vectors",
    "court_agree": "court verdicts that agree with our independent re-implementation",
    "block_width": "stationary-bootstrap CI width relative to our iid CI (cap rule, per wallet range)",
    "detector_power_300": "size-after-loss detector flags a planted 3x size-up, 300 trips",
    "detector_power_15_300": "size-after-loss detector flags a planted 1.5x size-up, 300 trips",
    "detector_power_125_300": "size-after-loss detector flags a planted 1.25x size-up, 300 trips",
    "detector_power_600": "size-after-loss detector flags a planted 3x size-up, 600 trips",
    "detector_falseflag_300": "size-after-loss detector flags a trader with no size habit, 300 trips",
    "pbo_null": "mean PBO (CSCV) of the cap rules on planted no-leak traders",
    "pbo_costly": "mean PBO (CSCV) of the cap rules on planted costly-leak traders",
    "dsr_null": "mean deflated Sharpe of the best cap rule, planted no-leak traders",
    "dsr_costly": "mean deflated Sharpe of the best cap rule, planted costly-leak traders",
    "props_passed": "hypothesis property tests passing",
    "real_accepted_wallets": "real wallets on which the court accepted a rule",
    "ci_finding": "the one bootstrap CI that missed its tolerance, with the noise study",
    "d_finding": "wallet D: accepted by the court, but not supported by all-history, PBO and DSR views",
    "tools": "reference tool versions",
}
for _k, _d in _VAL_SCALARS.items():
    CLAIMS[f"validation.{_k}"] = {"desc": _d, "cmd": "python scripts/run_validation.py", "fn": (lambda k=_k: _vr()["scalars"][k])}
for _k in ("crosscheck_summary", "crosscheck_detectors", "crosscheck_court", "crosscheck_dependence", "power_court", "power_detector", "pbo_planted", "pbo_real"):
    CLAIMS[f"validation.table.{_k}"] = {"desc": f"validation table {_k}", "cmd": "python scripts/run_validation.py", "fn": (lambda k=_k: _vr()["tables"][k])}


def values() -> dict[str, str]:
    return {k: v["fn"]() for k, v in CLAIMS.items()}
