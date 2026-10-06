"""Compute every number in VALIDATION.md and store it in validation_results.json. DEV-ONLY (see requirements-dev.txt).

Run order: python scripts/crosscheck_stats.py   (slow, minutes; independent re-computation of shipped p-values)
           python scripts/run_validation.py     (planted-bias protocol, PBO/deflated Sharpe, property tests, tables)
Then:      python scripts/render_docs.py        (VALIDATION.md is rendered from VALIDATION.template.md via claims.py)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import service  # noqa: E402
from engine.detectors import after_loss_labels, size_after_loss  # noqa: E402
from engine.planted import planted_trader  # noqa: E402
from validation_lib import dsr, load_results, merge_results, pbo_cscv  # noqa: E402

SIMS_DETECTOR = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100
SIMS_PBO = 60
SIZES = (60, 150, 300, 600)
MULTS = (1.0, 1.5, 2.0, 3.0)
SCEN = {"null": dict(size_mult=1.0, tilt=0.0), "costless_habit": dict(size_mult=3.0, tilt=0.0), "costly_leak": dict(size_mult=3.0, tilt=-0.006)}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def rule_effect_matrix(trips, mults=MULTS) -> np.ndarray:
    """T x N matrix: per-trip dollar change if each pre-declared cap had applied (the court's own pricing), time order."""
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    lab = after_loss_labels(ts)
    k = lab >= 0
    notional = np.array([t.first_order_notional for t in ts])
    pnl = np.array([t.net_pnl for t in ts])
    calm = notional[lab == 0]
    base = float(np.median(calm if len(calm) >= 10 else notional))
    nt, pn, af = notional[k], pnl[k], lab[k] == 1
    cols = []
    for m in mults:
        cap = m * base
        f = np.where(af & (nt > cap), cap / np.maximum(nt, 1e-12), 1.0)
        cols.append(pn * (f - 1.0))
    return np.stack(cols, axis=1)


DET_SCEN = (("no_size_habit", 1.0), ("size_up_1.25x", 1.25), ("size_up_1.5x", 1.5), ("size_up_2x", 2.0), ("size_up_3x", 3.0))


def detector_power() -> dict:
    cells = []
    for label, mult in DET_SCEN:
        for n in SIZES:
            flagged = 0
            for s in range(SIMS_DETECTOR):
                tr = planted_trader(n=n, size_mult=mult, tilt=0.0, seed=777_000 + 31 * n + s)
                flagged += size_after_loss(tr, n_perm=300, seed=s).status == "FLAGGED"
            cells.append({"scenario": label, "size_mult": mult, "trips": n, "flagged": flagged / SIMS_DETECTOR, "ci": wilson(flagged, SIMS_DETECTOR)})
            print("detector", cells[-1], flush=True)
    return {"sims_per_cell": SIMS_DETECTOR, "n_perm": 300, "detector": "size_after_loss (raw FLAGGED: p<0.05 and ratio>=1.25, before Holm)", "cells": cells}


def pbo_section() -> dict:
    out = {"mults": list(MULTS), "blocks": 16, "planted": {}, "real": {}}
    for name, kw in SCEN.items():
        pbos, dsrs, psrs, oosneg, corr = [], [], [], [], []
        for s in range(SIMS_PBO):
            m = rule_effect_matrix(planted_trader(n=300, seed=424_000 + s, **kw))
            r, d = pbo_cscv(m), dsr(m)
            pbos.append(r["pbo"])
            oosneg.append(r["p_oos_best_not_positive"])
            dsrs.append(d["dsr"])
            psrs.append(d["psr0"])
            corr.append(d["avg_trial_corr"])
        out["planted"][name] = {"sims": SIMS_PBO, "trips": 300, "mean_pbo": float(np.mean(pbos)), "mean_p_oos_best_not_positive": float(np.mean(oosneg)),
                                "mean_dsr": float(np.nanmean(dsrs)), "mean_psr0": float(np.nanmean(psrs)),
                                "share_dsr_above_0.95": float(np.mean(np.array(dsrs) > 0.95)), "mean_trial_corr": float(np.nanmean(corr))}
    for tid in ("A", "B", "C", "D", "E", "G"):
        m = rule_effect_matrix(service._load(tid)[3])
        r, d = pbo_cscv(m), dsr(m)
        out["real"][tid] = {"rows": int(m.shape[0]), "pbo": r["pbo"], "p_oos_best_not_positive": r["p_oos_best_not_positive"],
                            "best_cap": MULTS[d["best_trial"]], "psr0": d["psr0"], "dsr": d["dsr"], "sr_best_per_trip": d["sr_best"],
                            "sr0_deflation": d["sr0_deflation"], "trial_corr": d["avg_trial_corr"],
                            "court_accepted": service.review(tid)["court"]["accepted"]}
    return out


def properties() -> dict:
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_validation_properties.py"],
                         cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+) passed", out.stdout)
    f = re.search(r"(\d+) failed", out.stdout)
    import hypothesis
    return {"passed": int(m.group(1)) if m else 0, "failed": int(f.group(1)) if f else 0, "hypothesis": hypothesis.__version__,
            "properties": ["round trips conserve net pnl (with an unfinished tail)", "dedupe idempotent, order-free and duplicate-proof",
                           "trips unchanged by replayed fills", "after-loss label ignores every later trip",
                           "court cap uses only earlier chunks", "Holm bounded, monotone, no worse than Bonferroni",
                           "Holm: adding a test never helps the others", "Holm permutation-equivariant", "Holm equals statsmodels"]}


def fmt(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def tables(res: dict) -> dict:
    cc, t = res["crosscheck"], {}
    s = cc["summary"]
    t["crosscheck_summary"] = "\n".join([
        "| Quantity | Reference implementation | Compared | Agree | Tolerance (declared before running) |", "|---|---|---|---|---|",
        f"| Detector p-values (permutation) | scipy.stats.permutation_test, {cc['reference_draws']['permutations']:,} resamples | {s['detector_pvalues_compared']} | {s['detector_pvalues_agree']} | 3 combined Monte-Carlo SE + 1e-4 |",
        f"| Detector 95% CIs (bootstrap) | scipy.stats.bootstrap, {cc['reference_draws']['bootstrap']:,} resamples | {s['detector_pvalues_compared']} | {s['detector_cis_agree']} | endpoints within 10% of the reference CI width |",
        f"| UNDERPOWERED gating | independent group counts | {s['detector_underpowered_total']} | {s['detector_underpowered_agree']} | same decision |",
        f"| Holm adjusted p (shipped, per trader) | statsmodels multipletests(holm) | {s['holm_shipped_compared']} | {s['holm_shipped_agree']} | 5e-4 (max observed {s['holm_shipped_max_abs_diff']:.1e}) |",
        f"| Holm on random p-vectors | statsmodels multipletests(holm) | {cc['holm_random']['vectors']:,} | {cc['holm_random']['vectors']:,} | 1e-12 (max observed {cc['holm_random']['max_abs_diff']:.1e}) |",
        f"| Court walk-forward verdicts (effect, p, status) | our re-implementation from the docs, {cc['reference_draws']['court_permutations']:,} permutations | {s['court_compared']} | {s['court_agree']} | effect within $0.01; p within 3 combined SE |",
        f"| After-loss labels | independent searchsorted implementation | {s['traders']} traders | {s['labels_identical']} | identical arrays |",
        f"| All-history CI of the 1.5x rule | arch IIDBootstrap, 5,000 resamples | {s['dependence_traders']} | {s['ours_vs_arch_iid_agree']} | endpoints within 10% of width |"])
    rows = ["| Trader | Test | n (flagged group / other) | Our p | scipy p | Our 95% CI | scipy 95% CI (percentile) | scipy BCa | p ok | CI ok |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in cc["detectors"]:
        if "p_ok" not in r:
            rows.append(f"| {r['trader']} | {r['detector']} | {r['n_a']}/{r['n_b']} | underpowered | underpowered | | | | {'yes' if r['agree'] else 'NO'} | |")
            continue
        sci = lambda c: f"[{c[0]:.3g}, {c[1]:.3g}]"  # noqa: E731
        rows.append(f"| {r['trader']} | {r['detector']} | {r['n_a']}/{r['n_b']} | {r['shipped_p']:.4f} | {r['scipy_p']:.4f} | {sci(r['shipped_ci'])} | "
                    f"{sci(r['scipy_ci_percentile'])} | {sci(r['scipy_ci_bca'])} | {'yes' if r['p_ok'] else 'NO'} | {'yes' if r['ci_ok'] else 'NO'} |")
    t["crosscheck_detectors"] = "\n".join(rows)
    rows = ["| Trader | Cap | Our status | Reference status | Our p (1,500 perms) | Reference p (100,000) | Our held-out effect | Reference effect |", "|---|---|---|---|---|---|---|---|"]
    for r in cc["court"]:
        rows.append(f"| {r['trader']} | {r['multiple']}x | {r['shipped_status']} | {r['ref_status']} | {fmt(r['shipped_p'], 4)} | {fmt(r['ref_p'], 4)} | "
                    f"{fmt(r['shipped_effect'], 2)} | {fmt(r['ref_effect'], 2)} |")
    t["crosscheck_court"] = "\n".join(rows)
    rows = ["| Trader | Rule | Effect | Our iid CI (800 draws) | arch iid CI | arch stationary (mean block 5) | width vs iid | arch circular block 5 | width vs iid |", "|---|---|---|---|---|---|---|---|---|"]
    ci = lambda c: f"[{c[0]:,.0f}, {c[1]:,.0f}]"  # noqa: E731
    for b in cc["dependence"]:
        rows.append(f"| {b['trader']} | cap 1.5x | {b['effect']:,.0f} | {ci(b['shipped_ci'])} | {ci(b['arch_iid'])} | {ci(b['arch_stationary_b5'])} | "
                    f"{b['arch_stationary_b5_width_ratio']:.2f}x | {ci(b['arch_circular_b5'])} | {b['arch_circular_b5_width_ratio']:.2f}x |")
    t["crosscheck_dependence"] = "\n".join(rows)
    # power
    court = json.loads((ROOT / "court_results.json").read_text(encoding="utf-8"))
    rows = ["| Planted trader | " + " | ".join(f"{n} trips" for n in SIZES) + " |", "|---|" + "---|" * len(SIZES)]
    for scen, label in (("null", "No leak (court wrongly accepts)"), ("costless_habit", "Costless habit, 3x size up (court wrongly accepts)"),
                        ("costly_leak", "Costly leak (court correctly accepts = power)")):
        cells = {c["trips"]: c for c in court["cells"] if c["scenario"] == scen}
        rows.append(f"| {label} | " + " | ".join(f"{pct(cells[n]['accepted'])} [{pct(cells[n]['accepted_ci'][0])}, {pct(cells[n]['accepted_ci'][1])}]" for n in SIZES) + " |")
    t["power_court"] = "\n".join(rows)
    d = res["detector_power"]
    rows = ["| Planted trader | " + " | ".join(f"{n} trips" for n in SIZES) + " |", "|---|" + "---|" * len(SIZES)]
    for scen, label in (("no_size_habit", "No size habit (false flag)"), ("size_up_1.25x", "Sizes up 1.25x after a loss (power)"),
                        ("size_up_1.5x", "Sizes up 1.5x after a loss (power)"), ("size_up_2x", "Sizes up 2x after a loss (power)"),
                        ("size_up_3x", "Sizes up 3x after a loss (power)")):
        cells = {c["trips"]: c for c in d["cells"] if c["scenario"] == scen}
        rows.append(f"| {label} | " + " | ".join(f"{pct(cells[n]['flagged'])} [{pct(cells[n]['ci'][0])}, {pct(cells[n]['ci'][1])}]" for n in SIZES) + " |")
    t["power_detector"] = "\n".join(rows)
    p = res["pbo"]
    rows = ["| Planted trader (300 trips, 60 sims) | Mean PBO | Mean P(best rule loses out of sample) | Mean DSR | Mean PSR(0) | Share DSR > 0.95 | Mean correlation between rules |", "|---|---|---|---|---|---|---|"]
    for k, label in (("null", "No leak"), ("costless_habit", "Costless habit"), ("costly_leak", "Costly leak")):
        v = p["planted"][k]
        rows.append(f"| {label} | {v['mean_pbo']:.2f} | {v['mean_p_oos_best_not_positive']:.2f} | {v['mean_dsr']:.2f} | {v['mean_psr0']:.2f} | {pct(v['share_dsr_above_0.95'])} | {v['mean_trial_corr']:.2f} |")
    t["pbo_planted"] = "\n".join(rows)
    rows = ["| Wallet | Trips used | PBO | P(best rule loses OOS) | In-sample best cap | PSR(0) | DSR (4 trials) | Court accepted |", "|---|---|---|---|---|---|---|---|"]
    for tid, v in p["real"].items():
        rows.append(f"| {tid} | {v['rows']} | {fmt(v['pbo'], 2)} | {fmt(v['p_oos_best_not_positive'], 2)} | {v['best_cap']}x | {fmt(v['psr0'], 2)} | {fmt(v['dsr'], 2)} | {v['court_accepted']} |")
    t["pbo_real"] = "\n".join(rows)
    return t


def ci_finding(cc: dict) -> str:
    bad = [r for r in cc["detectors"] if "p_ok" in r and not r["ci_ok"]]
    if not bad:
        return "No bootstrap CI missed its tolerance."
    parts = []
    for r in bad:
        n = r["ci_noise_study"]
        parts.append(f"wallet {r['trader']} {r['detector']}: our shipped CI is [{r['shipped_ci'][0]:.3g}, {r['shipped_ci'][1]:.3g}] and scipy's is "
                     f"[{r['scipy_ci_percentile'][0]:.3g}, {r['scipy_ci_percentile'][1]:.3g}]. Re-running our own procedure with {n['seeds']} other seeds, "
                     f"{pct(n['share_of_1500_draw_runs_within_tolerance'])} landed within tolerance (upper endpoint ranged {n['upper_endpoint_range_1500_draws'][0]:.3g} to "
                     f"{n['upper_endpoint_range_1500_draws'][1]:.3g}), and with 20,000 draws our procedure gives [{n['our_procedure_20000_draws'][0]:.3g}, "
                     f"{n['our_procedure_20000_draws'][1]:.3g}], matching scipy. The p-value is unaffected")
    return "; ".join(parts)


def d_finding(res: dict) -> str:
    d = res["pbo"]["real"]["D"]
    dep = next(b for b in res["crosscheck"]["dependence"] if b["trader"] == "D")
    ct = [r for r in res["crosscheck"]["court"] if r["trader"] == "D" and r["shipped_status"] == "ACCEPTED"]
    eff = ", ".join(f"{r['multiple']}x (held-out ${r['shipped_effect']:,.0f})" for r in ct)
    return (f"wallet D is the one real wallet where the court accepted rules ({eff}); the independent re-implementation reproduces both verdicts. "
            f"But the same cap rules priced on ALL of D's history give ${dep['effect']:,.0f} at 1.5x with a 95% interval of [{dep['arch_iid'][0]:,.0f}, {dep['arch_iid'][1]:,.0f}] (it contains zero), "
            f"the CSCV probability of backtest overfitting over D's four caps is {d['pbo']:.2f}, and the deflated Sharpe of the best cap is {d['dsr']:.2f}")


def scalars(res: dict) -> dict:
    cc, s = res["crosscheck"], res["crosscheck"]["summary"]
    pl, det = res["pbo"]["planted"], {(c["scenario"], c["trips"]): c["flagged"] for c in res["detector_power"]["cells"]}
    real_acc = [t for t, v in res["pbo"]["real"].items() if v["court_accepted"]]
    return {
        "p_agree": f"{s['detector_pvalues_agree']} of {s['detector_pvalues_compared']}",
        "ci_agree": f"{s['detector_cis_agree']} of {s['detector_pvalues_compared']}",
        "holm_agree": f"{s['holm_shipped_agree']} of {s['holm_shipped_compared']}",
        "holm_random_maxdiff": f"{cc['holm_random']['max_abs_diff']:.0e}",
        "court_agree": f"{s['court_agree']} of {s['court_compared']}",
        "block_width": f"{s['stationary_b5_width_ratio_min']:.2f}x to {s['stationary_b5_width_ratio_max']:.2f}x",
        "detector_power_300": pct(det[("size_up_3x", 300)]), "detector_power_15_300": pct(det[("size_up_1.5x", 300)]),
        "detector_power_125_300": pct(det[("size_up_1.25x", 300)]),
        "detector_falseflag_300": pct(det[("no_size_habit", 300)]),
        "detector_power_600": pct(det[("size_up_3x", 600)]),
        "pbo_null": f"{pl['null']['mean_pbo']:.2f}", "pbo_costly": f"{pl['costly_leak']['mean_pbo']:.2f}",
        "dsr_null": f"{pl['null']['mean_dsr']:.2f}", "dsr_costly": f"{pl['costly_leak']['mean_dsr']:.2f}",
        "props_passed": str(res["properties"]["passed"]),
        "real_accepted_wallets": ", ".join(real_acc) if real_acc else "none",
        "ci_finding": ci_finding(cc), "d_finding": d_finding(res),
        "tools": f"scipy {cc['tools']['scipy']}, statsmodels {cc['tools']['statsmodels']}, arch {cc['tools']['arch']}, hypothesis {res['properties']['hypothesis']}",
    }


def main() -> None:
    t0 = time.time()
    if "crosscheck" not in load_results():
        sys.exit("run scripts/crosscheck_stats.py first")
    if "--final" not in sys.argv:            # --final: only rebuild tables and scalars from stored results
        merge_results("detector_power", detector_power())
        merge_results("pbo", pbo_section())
        merge_results("properties", properties())
    res = load_results()
    merge_results("tables", tables(res))
    merge_results("scalars", scalars(res))
    merge_results("seconds_run_validation", round(time.time() - t0))
    print(json.dumps(load_results()["scalars"], indent=2))


if __name__ == "__main__":
    main()
