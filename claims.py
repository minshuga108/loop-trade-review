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


def _d3_cells() -> list:
    return json.loads((ROOT / "detectors3_results.json").read_text(encoding="utf-8"))["cells"]


def _d3(detector: str, scenario: str) -> str:
    return _pct(next(c["flagged"] for c in _d3_cells() if c["detector"] == detector and c["scenario"] == scenario))


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
    "d3.power_chase": {"desc": "chase_after_move flags a planted costly chaser (candle price source), 300 trips", "cmd": "python scripts/measure_detectors3.py",
                       "fn": lambda: _d3("chase_after_move[candles]", "habit_costly")},
    "d3.power_chase_own": {"desc": "chase_after_move flags a planted costly chaser (own fill prices as the series), 300 trips", "cmd": "python scripts/measure_detectors3.py",
                           "fn": lambda: _d3("chase_after_move[own_fills]", "habit_costly")},
    "d3.power_offhours": {"desc": "off_hours_trading flags a planted costly off-hours trader, 300 trips", "cmd": "python scripts/measure_detectors3.py",
                          "fn": lambda: _d3("off_hours_trading", "habit_costly")},
    "d3.power_avgdown": {"desc": "averaging_down flags a planted costly averager, 250 trips", "cmd": "python scripts/measure_detectors3.py",
                         "fn": lambda: _d3("averaging_down", "habit_costly")},
    "d3.falseflag_max": {"desc": "highest false-flag rate of the three new detectors on costless/absent planted habits (before Holm)", "cmd": "python scripts/measure_detectors3.py",
                         "fn": lambda: _pct(max(c["flagged"] for c in _d3_cells() if c["scenario"] == "habit_costless" or "no_habit" in c["detector"]))},
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


def _rr() -> dict:
    p = ROOT / "robustness_results.json"
    if not p.exists():
        raise FileNotFoundError("run scripts/robustness_suite.py first")
    return json.loads(p.read_text(encoding="utf-8"))


_ROB = {"sims": "simulated traders per stress cell", "trips": "round trips per simulated trader", "worst_any": "highest family-wise false-flag rate (after Holm) under any stress",
        "worst_court": "highest court wrong-acceptance rate under any stress", "worst_detector": "highest single-detector false-flag rate (after Holm) under any stress",
        "baseline_any": "family-wise false-flag rate, no stress", "baseline_court": "court wrong acceptance, no stress",
        "failures": "cells whose 95% interval lies wholly above 5% (our own failures)", "n_failures": "number of such cells",
        "ac_court": "court wrong acceptance under autocorrelated returns (current court)", "all_court": "court wrong acceptance under all four stresses (current court)",
        "all_any": "family-wise false-flag rate under all four stresses (current detectors)",
        "dep_power": "court acceptance of a REAL costly leak under autocorrelated returns (does the dependence guard cost power)",
        "dep_power_trips": "trips in that power cell", "dep_power_detected": "share of those traders where dependence was detected",
        "before_table": "robustness table of the first version (single-label permutation, expanding baseline), frozen",
        "before_worst_any": "first version: highest family-wise false-flag rate", "before_worst_court": "first version: highest court wrong acceptance",
        "before_ac_court": "first version: court wrong acceptance under autocorrelated returns", "before_all_court": "first version: court wrong acceptance under all four",
        "before_all_any": "first version: family-wise flag rate under all four", "before_n_failures": "first version: number of failing cells"}
for _k, _d in _ROB.items():
    CLAIMS[f"robustness.{_k}"] = {"desc": _d, "cmd": "python scripts/robustness_suite.py", "fn": (lambda k=_k: _rr()["scalars"][k])}
CLAIMS["robustness.table"] = {"desc": "robustness table", "cmd": "python scripts/robustness_suite.py", "fn": lambda: _rr()["table"]}


# ---- Whitepaper-only numbers: each is read from its source file or code constant, never typed ----------------------------
def _p1(x: float) -> str:
    return f"{100 * x:.1f}%"


def _court_cell(scenario: str, trips: int) -> dict:
    data = json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))
    return next(c for c in data["cells"] if c["scenario"] == scenario and c["trips"] == trips)


def _court_table() -> str:
    rows = ["| Planted trader | " + " | ".join(f"{t} trips" for t in (60, 150, 300, 600)) + " |", "|---|---|---|---|---|"]
    for sc, label in (("null", "No leak: court wrongly accepts"), ("costless_habit", "Costless habit: court wrongly accepts"),
                      ("costly_leak", "Costly leak: court correctly accepts (power)")):
        cells = []
        for t in (60, 150, 300, 600):
            c = _court_cell(sc, t)
            lo, hi = c["accepted_ci"]
            cells.append(f"{_p1(c['accepted'])} ({_p1(lo)} to {_p1(hi)})")
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _court_meta(key: str) -> str:
    return str(json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))[key])


def _look() -> dict:
    s = json.loads((ROOT / "suite_results.json").read_text(encoding="utf-8"))
    return next(x for x in s["summaries"] if x["scenario"] == "LOOKAHEAD")["rules"]


def _look_k(rule: str, key: str) -> str:
    r = _look()[rule][key]
    return f"{r['k']} of {r['n']}"


def _cohort() -> dict:
    return json.loads((ROOT / "cohort_results.json").read_text(encoding="utf-8"))


def _coh_det(name: str) -> str:
    d = _cohort()["detectors"][name]
    return f"{d['bh_significant']} of {d['tested']}"


def _selftest() -> dict:
    return json.loads((ROOT / "eval" / "selftest_first_run.json").read_text(encoding="utf-8"))["summary"]


def _pbo_real(tid: str, key: str) -> str:
    return f"{_vr()['pbo']['real'][tid][key]:.2f}"


def _journal_trades() -> str:
    p = ROOT / "deploy_data" / "real_bitget_journal" / "journal_verified.json"
    return str(len(json.loads(p.read_text(encoding="utf-8"))))


def _qwen_deadline() -> str:
    from app import qa_chat
    return f"{qa_chat.QWEN_TIMEOUT_S:g}"


def _qwen_cap() -> str:
    from app import llm
    return str(llm.DAILY_CAP)


def _d3_extreme(key: str) -> str:
    return _p1(max(c[key] for c in _d3_cells() if c["scenario"] == "habit_costless" or "no_habit" in c["detector"]))


_WP = {
    "court.table": ("court false admission and power table, 1 decimal with Wilson intervals", "python scripts/measure_court.py", _court_table),
    "court.fa_null_600_1dp": ("court wrongly accepts a no-leak trader, 600 trips, 1 decimal", "python scripts/measure_court.py", lambda: _p1(_court_cell("null", 600)["accepted"])),
    "court.power_150_1dp": ("court power at 150 trips, 1 decimal", "python scripts/measure_court.py", lambda: _p1(_court_cell("costly_leak", 150)["accepted"])),
    "court.power_300_1dp": ("court power at 300 trips, 1 decimal", "python scripts/measure_court.py", lambda: _p1(_court_cell("costly_leak", 300)["accepted"])),
    "court.ledger": ("proposals in the trial ledger", "python scripts/measure_court.py", lambda: _court_meta("proposals_in_ledger")),
    "court.threshold": ("per-rule threshold", "python scripts/measure_court.py", lambda: _court_meta("threshold_per_rule")),
    "look.leaky_refused": ("peeking rule refused by the look-ahead guard", "python scripts/run_suite.py", lambda: _look_k("peek", "refused")),
    "look.leaky_stats_only": ("peeking rule the statistics alone would accept", "python scripts/run_suite.py", lambda: _look_k("peek", "stats_only_accept")),
    "look.following_stats_only": ("second leaky rule the statistics alone would accept", "python scripts/run_suite.py", lambda: _look_k("following", "stats_only_accept")),
    "look.honest_refused": ("honest control rule refused by the guard", "python scripts/run_suite.py", lambda: _look_k("honest_cap", "refused")),
    "look.honest_accepted": ("honest control rule accepted", "python scripts/run_suite.py", lambda: _look_k("honest_cap", "accepted")),
    "cohort.wallets": ("wallets in the cohort study", "python scripts/cohort_study.py", lambda: str(_cohort()["n_wallets"])),
    "cohort.trips": ("round trips in the cohort", "python scripts/cohort_study.py", lambda: f"{_cohort()['n_round_trips']:,}"),
    "cohort.fills": ("fills in the cohort", "python scripts/cohort_study.py", lambda: f"{_cohort()['n_fills']:,}"),
    "cohort.leaderboard": ("leaderboard rows in the snapshot", "python scripts/cohort_study.py", lambda: f"{_cohort()['sampling']['leaderboard_rows']:,}"),
    "cohort.eligible": ("eligible wallets in the snapshot", "python scripts/cohort_study.py", lambda: f"{_cohort()['sampling']['eligible']:,}"),
    "cohort.size_bh": ("wallets with size-after-loss habit after BH", "python scripts/cohort_study.py", lambda: _coh_det("size_after_loss")),
    "cohort.hold_bh": ("wallets with hold asymmetry after BH", "python scripts/cohort_study.py", lambda: _coh_det("hold_asymmetry")),
    "cohort.over_bh": ("wallets with overtrading days after BH", "python scripts/cohort_study.py", lambda: _coh_det("overtrading_clusters")),
    "cohort.revenge_bh": ("wallets with revenge re-entry after BH", "python scripts/cohort_study.py", lambda: _coh_det("revenge_reentry")),
    "cohort.pooled_p": ("pooled size-after-loss p", "python scripts/cohort_study.py", lambda: f"{_cohort()['detectors']['size_after_loss']['pooled']['p_pooled_shuffle']:.4f}"),
    "cohort.within_p": ("within-trader size-after-loss p", "python scripts/cohort_study.py", lambda: f"{_cohort()['detectors']['size_after_loss']['pooled']['p_within_trader_shuffle']:.2f}"),
    "cohort.court_wallets": ("cohort wallets with an accepted rule", "python scripts/cohort_study.py", lambda: f"{_cohort()['court']['wallets_with_any_accepted']} of {_cohort()['n_wallets']}"),
    "cohort.court_trials": ("cohort rule trials", "python scripts/cohort_study.py", lambda: str(_cohort()["court"]["cohort_trials"])),
    "cohort.court_judged": ("cohort rule trials judged", "python scripts/cohort_study.py", lambda: str(_cohort()["court"]["judged_not_underpowered"])),
    "cohort.expected_chance": ("acceptances expected by chance at most", "python scripts/cohort_study.py", lambda: f"{_cohort()['court']['expected_acceptances_if_no_leak_at_most']:.1f}"),
    "selftest.passed": ("selftest first run passes", "eval/selftest_first_run.json", lambda: f"{_selftest()['passed']} of {_selftest()['n']}"),
    "wallet.d_pbo": ("wallet D PBO", "python scripts/run_validation.py", lambda: _pbo_real("D", "pbo")),
    "wallet.d_dsr": ("wallet D deflated Sharpe", "python scripts/run_validation.py", lambda: _pbo_real("D", "dsr")),
    "journal.trades": ("wallet H verified trades", "deploy_data/real_bitget_journal/journal_verified.json", _journal_trades),
    "qwen.deadline": ("Qwen per-call deadline in seconds", "app/qa_chat.py QWEN_TIMEOUT_S", _qwen_deadline),
    "qwen.cap": ("Qwen daily call cap", "app/llm.py DAILY_CAP", _qwen_cap),
    "d3.falseflag_max_1dp": ("highest false flag of the three newer detectors before Holm, 1 decimal", "python scripts/measure_detectors3.py", lambda: _d3_extreme("flagged")),
    "d3.falseflag_after_holm": ("highest false flag of the three newer detectors after Holm", "python scripts/measure_detectors3.py", lambda: _d3_extreme("flagged_after_holm7")),
}
for _k, (_d, _c, _f) in _WP.items():
    CLAIMS[_k] = {"desc": _d, "cmd": _c, "fn": _f}


def values() -> dict[str, str]:
    return {k: v["fn"]() for k, v in CLAIMS.items()}
