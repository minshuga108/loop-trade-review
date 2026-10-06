"""Cross-check our habit-test p-values, CIs, court p-values and Holm adjustments on the shipped traders
against independent implementations (scipy.stats, statsmodels, arch, and a from-the-docs re-implementation
of the walk-forward court). DEV-ONLY: needs requirements-dev.txt.  Run: python scripts/crosscheck_stats.py

Tolerances are declared here, before looking at results:
  p-values        |ours - ref| <= 3 * sqrt(se_ours^2 + se_ref^2) + 1e-4   (Monte-Carlo error of both, plus 4-dp rounding)
  CI endpoints    |ours - ref| <= 10% of the reference CI width           (1500-draw percentile bootstrap noise)
  Holm            |ours - ref| <= 5e-4 on shipped (4-dp rounded) p-values; exact (1e-12) on random vectors
  court effect    |ours - ref| <= 0.01 dollars (deterministic quantity)
Results go to validation_results.json["crosscheck"]. Disagreements are findings, never tuned away.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import arch  # noqa: E402
import scipy  # noqa: E402
import statsmodels  # noqa: E402
from arch.bootstrap import CircularBlockBootstrap, IIDBootstrap, StationaryBootstrap  # noqa: E402
from scipy import stats as sst  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from app import service  # noqa: E402
from engine.detectors import after_loss_labels  # noqa: E402
from engine.detectors2 import MIN_ACTIVE_DAYS, MIN_PER_GROUP, OVERTRADE_PERCENTILE  # noqa: E402
from engine.stats import holm  # noqa: E402
from validation_lib import merge_results  # noqa: E402

TRADERS = ["A", "B", "C", "D", "E", "G"]
DAY_MS = 86_400_000
N_REF_PERM = 40_000
N_REF_BOOT = 9_999
FOLDS = 5
MULTS = (1.0, 1.5, 2.0, 3.0)


def indep_after_loss(trips) -> np.ndarray:
    opn = np.array([t.t_open_ms for t in trips])
    cls = np.array([t.t_close_ms for t in trips])
    pnl = np.array([t.net_pnl for t in trips])
    order = np.argsort(cls, kind="stable")
    k = np.searchsorted(cls[order], opn, side="left") - 1
    return np.where(k >= 0, (pnl[order][np.maximum(k, 0)] < 0).astype(int), -1)


def _p_ok(p1, n1, p2, n2):
    se = float(np.hypot(np.sqrt(p1 * (1 - p1) / n1), np.sqrt(p2 * (1 - p2) / n2)))
    return abs(p1 - p2) <= 3 * se + 1e-4, se


def _ci_ok(ci1, ci2):
    w = max(ci2[1] - ci2[0], 1e-12)
    d = max(abs(ci1[0] - ci2[0]), abs(ci1[1] - ci2[1]))
    return d <= 0.10 * w, d / w


def _med_log_gap(x, y, axis=-1):
    return np.median(np.log(x), axis=axis) - np.median(np.log(y), axis=axis)


def _mean_gap(x, y, axis=-1):          # ours: mean(b) - mean(a), a = labelled group
    return np.mean(y, axis=axis) - np.mean(x, axis=axis)


def _ratio(x, y, axis=-1):
    return np.exp(_med_log_gap(x, y, axis))


def _mean_diff(x, y, axis=-1):
    return np.mean(x, axis=axis) - np.mean(y, axis=axis)


def our_style_boot(a, b, kind: str, seed: int, reps: int = 1500) -> tuple[float, float]:
    """Same procedure as engine.detectors (resample each group, percentile CI), different seed / draw count."""
    g = np.random.default_rng(seed)
    f = _ratio if kind == "ratio" else _mean_diff
    boots = [float(f(a[g.integers(0, len(a), len(a))], b[g.integers(0, len(b), len(b))])) for _ in range(reps)]
    return float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))


def ci_noise_study(a, b, kind: str, ref_ci, seeds: int = 40) -> dict:
    """Why did a CI miss the tolerance? Repeat OUR procedure with other seeds, and with many more draws."""
    cis = [our_style_boot(a, b, kind, 1000 + s) for s in range(seeds)]
    within = sum(_ci_ok(c, ref_ci)[0] for c in cis)
    conv = our_style_boot(a, b, kind, 4242, reps=20000)
    return {"seeds": seeds, "share_of_1500_draw_runs_within_tolerance": within / seeds,
            "our_procedure_20000_draws": list(conv), "upper_endpoint_range_1500_draws": [min(c[1] for c in cis), max(c[1] for c in cis)]}


def check_two_sample(shipped: dict, name: str, a, b, kind: str, seed: int) -> dict:
    """a = labelled group, b = other. kind 'ratio' (median log gap, CI on ratio) or 'meangap' (CI on mean(a)-mean(b))."""
    row = {"detector": name, "shipped_status": shipped["status"], "shipped_p": shipped["p"], "shipped_ci": shipped["ci"],
           "n_a": int(len(a)), "n_b": int(len(b))}
    under_ref = min(len(a), len(b)) < MIN_PER_GROUP
    if shipped["p"] is None:
        row["agree"] = bool(under_ref)
        row["note"] = "UNDERPOWERED in both" if under_ref else "DISAGREE: shipped underpowered, reference is not"
        return row
    if under_ref:
        row.update(agree=False, note="DISAGREE: shipped ran a test, reference says underpowered")
        return row
    stat, ci_stat = (_med_log_gap, _ratio) if kind == "ratio" else (_mean_gap, _mean_diff)
    pt = sst.permutation_test((a, b), stat, permutation_type="independent", alternative="greater",
                              n_resamples=N_REF_PERM, vectorized=True, random_state=seed)
    ok, se = _p_ok(shipped["p"], 4000, float(pt.pvalue), N_REF_PERM)
    bt = sst.bootstrap((a, b), ci_stat, vectorized=True, paired=False, n_resamples=N_REF_BOOT, method="percentile",
                       confidence_level=0.95, random_state=seed)
    ref_ci = (float(bt.confidence_interval.low), float(bt.confidence_interval.high))
    ci_ok, rel = _ci_ok(shipped["ci"], ref_ci)
    if not ci_ok:
        row["ci_noise_study"] = ci_noise_study(a, b, kind, ref_ci)
    bca = sst.bootstrap((a, b), ci_stat, vectorized=True, paired=False, n_resamples=N_REF_BOOT, method="BCa",
                        confidence_level=0.95, random_state=seed)
    row.update(scipy_p=float(pt.pvalue), p_tol_3se=float(3 * se), p_ok=bool(ok), scipy_ci_percentile=ref_ci,
               ci_endpoint_gap_rel_width=float(rel), ci_ok=bool(ci_ok),
               scipy_ci_bca=[float(bca.confidence_interval.low), float(bca.confidence_interval.high)],
               decision_agrees=bool((shipped["p"] < 0.05) == (pt.pvalue < 0.05)) if abs(shipped["p"] - 0.05) > 3 * se else True,
               agree=bool(ok and ci_ok))
    return row


def detector_inputs(trips):
    lab = indep_after_loss(trips)
    out = {}
    notional = np.array([t.first_order_notional for t in trips])
    keep = lab >= 0
    n, lo = notional[keep], lab[keep] == 1
    ok = n > 0
    out["size_after_loss"] = (n[ok][lo[ok]], n[ok][~lo[ok]], "ratio")
    hold = np.array([max(t.t_close_ms - t.t_open_ms, 1) for t in trips], dtype=float)
    loser = np.array([t.net_pnl < 0 for t in trips])
    out["hold_asymmetry"] = (hold[loser], hold[~loser], "ratio")
    df = pd.DataFrame({"day": [t.t_open_ms // DAY_MS for t in trips], "pnl": [t.net_pnl for t in trips]})
    cnt = df.groupby("day")["pnl"].transform("size")
    per_day = df.groupby("day").size()
    thr = float(np.percentile(per_day.values, OVERTRADE_PERCENTILE))
    heavy = (cnt > thr).values
    if len(per_day) < MIN_ACTIVE_DAYS:
        out["overtrading_clusters"] = (np.array([]), np.array([]), "meangap")
    else:
        out["overtrading_clusters"] = (df.pnl.values[heavy], df.pnl.values[~heavy], "meangap")
    return out


def indep_court(trips, mult: float, n_perm: int, seed: int) -> dict:
    """Walk-forward court re-implemented from the docstring in engine/walkforward.py, vectorised, more permutations."""
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    n = len(ts)
    lab = indep_after_loss(ts)
    notional = np.array([t.first_order_notional for t in ts])
    pnl = np.array([t.net_pnl for t in ts])
    edges = np.linspace(0, n, FOLDS + 2).astype(int)
    chunks, n_aff, n_test, obs = [], 0, 0, 0.0
    for j in range(1, FOLDS + 1):
        lo, hi = edges[j], edges[j + 1]
        calm = notional[:lo][lab[:lo] == 0]
        base = float(np.median(calm if len(calm) >= 10 else notional[:lo]))
        cap = mult * base
        idx = np.arange(lo, hi)[lab[lo:hi] >= 0]
        if len(idx) == 0:
            continue
        nt, pn, af = notional[idx], pnl[idx], lab[idx] == 1
        big = nt > cap
        w = pn * (cap / np.maximum(nt, 1e-12) - 1.0) * big
        obs += float(np.sum(w[af]))
        n_aff += int(np.sum(af & big))
        n_test += len(idx)
        chunks.append((af, w))
    res = {"effect": obs, "n_test": n_test, "n_affected": n_aff}
    if n_test < 30 or n_aff < 10:
        res["status"] = "UNDERPOWERED"
        return res
    rng = np.random.default_rng(seed)
    ge, done = 0, 0
    while done < n_perm:
        r = min(5000, n_perm - done)
        tot = np.zeros(r)
        for af, w in chunks:
            sh = rng.permuted(np.tile(af, (r, 1)), axis=1)
            tot += sh @ w
        ge += int(np.sum(tot >= obs - 1e-9))
        done += r
    p = (ge + 1) / (n_perm + 1)
    alpha = 0.05 / len(MULTS)
    res.update(p=p, status="ACCEPTED" if (obs > 0 and p < alpha) else "REJECTED")
    return res


def block_ci(trips, mult: float, reps: int, seed: int) -> dict:
    """All-history effect of the cap rule: iid CI vs arch iid, stationary and circular-block bootstrap."""
    lab = indep_after_loss(trips)
    notional = np.array([t.first_order_notional for t in trips])
    pnl = np.array([t.net_pnl for t in trips])
    calm = notional[lab == 0]
    base = float(np.median(calm if len(calm) >= 10 else notional))
    cap = mult * base
    k = lab >= 0
    nt, pn, af = notional[k], pnl[k], (lab[k] == 1)

    def eff(n_, p_, a_):
        f = np.where(a_ & (n_ > cap), cap / np.maximum(n_, 1e-12), 1.0)
        return float(np.sum(p_ * (f - 1.0)))

    out = {"effect": eff(nt, pn, af), "n": int(k.sum())}
    for label, cls, args in (("arch_iid", IIDBootstrap, ()), ("arch_stationary_b5", StationaryBootstrap, (5,)),
                             ("arch_stationary_b10", StationaryBootstrap, (10,)), ("arch_circular_b5", CircularBlockBootstrap, (5,))):
        bs = cls(*args, nt, pn, af, seed=seed) if args else cls(nt, pn, af, seed=seed)
        ci = np.asarray(bs.conf_int(eff, reps=reps, method="percentile", size=0.95)).reshape(-1)
        out[label] = [float(ci[0]), float(ci[1])]
    return out


def main() -> dict:
    res = {"tools": {"scipy": scipy.__version__, "statsmodels": statsmodels.__version__, "arch": arch.__version__},
           "tolerances": {"p": "3 combined MC standard errors + 1e-4", "ci": "10% of reference CI width", "holm": "5e-4 shipped, 1e-12 random",
                          "court_effect_usd": 0.01},
           "reference_draws": {"permutations": N_REF_PERM, "bootstrap": N_REF_BOOT, "court_permutations": 100_000}, "traders": {}}
    det_rows, court_rows, holm_rows, block_rows = [], [], [], []
    for ti, tid in enumerate(TRADERS):
        rev = service.review(tid)
        trips = service._load(tid)[3]
        shipped = {f["detector"]: f for f in rev["findings"]}
        lab_ok = bool(np.array_equal(after_loss_labels(trips), indep_after_loss(trips)))
        for name, (a, b, kind) in detector_inputs(trips).items():
            r = check_two_sample(shipped[name], name, a, b, kind, seed=100 + ti)
            r["trader"] = tid
            det_rows.append(r)
        raw = [1.0 if f["p"] is None else f["p"] for f in rev["findings"]]
        adj_sm = multipletests(raw, method="holm")[1]
        for f, a_sm in zip(rev["findings"], adj_sm):
            if f["p"] is None:
                continue
            holm_rows.append({"trader": tid, "detector": f["detector"], "ours": f["p_adj"], "statsmodels": float(a_sm),
                              "abs_diff": abs(f["p_adj"] - float(a_sm)), "agree": abs(f["p_adj"] - float(a_sm)) <= 5e-4})
        for v in rev["court"]["verdicts"]:
            ref = indep_court(trips, v["multiple"], 100_000, seed=500 + ti)
            row = {"trader": tid, "multiple": v["multiple"], "shipped_status": v["status"], "ref_status": ref["status"],
                   "shipped_p": v["p"], "ref_p": ref.get("p"), "shipped_effect": v["held_out_effect"], "ref_effect": ref["effect"]}
            if v["status"] == "UNDERPOWERED" or ref["status"] == "UNDERPOWERED":
                row["agree"] = v["status"] == ref["status"]
            else:
                ok, se = _p_ok(v["p"], 1500, ref["p"], 100_000)
                eff_ok = abs((v["held_out_effect"] or 0.0) - ref["effect"]) <= 0.01
                row.update(p_ok=bool(ok), effect_ok=bool(eff_ok), status_agrees=v["status"] == ref["status"],
                           agree=bool(ok and eff_ok and v["status"] == ref["status"]))
            court_rows.append(row)
        b = block_ci(trips, 1.5, 5000, seed=900 + ti)
        sh = next(v for v in rev["court"]["verdicts"] if v["multiple"] == 1.5)
        b.update(trader=tid, shipped_ci=sh["all_history_ci"], shipped_effect=sh["all_history_effect"])
        iid_w = b["arch_iid"][1] - b["arch_iid"][0]
        for k in ("arch_stationary_b5", "arch_stationary_b10", "arch_circular_b5"):
            b[k + "_width_ratio"] = (b[k][1] - b[k][0]) / iid_w if iid_w > 0 else float("nan")
        b["ours_vs_arch_iid_ok"] = bool(_ci_ok(sh["all_history_ci"], b["arch_iid"])[0]) if iid_w > 0 else True
        b["zero_in_iid_ci"] = bool(b["arch_iid"][0] <= 0 <= b["arch_iid"][1])
        b["zero_in_stationary_b5_ci"] = bool(b["arch_stationary_b5"][0] <= 0 <= b["arch_stationary_b5"][1])
        block_rows.append(b)
        res["traders"][tid] = {"after_loss_labels_identical": lab_ok, "n_trips": len(trips)}
    rng = np.random.default_rng(7)
    worst = 0.0
    nvec = 3000
    for _ in range(nvec):
        m = int(rng.integers(1, 12))
        p = np.round(rng.random(m) ** rng.choice([1, 3]), int(rng.choice([2, 4, 8])))
        worst = max(worst, float(np.max(np.abs(np.array(holm(list(p))) - multipletests(p, method="holm")[1]))))
    res["holm_random"] = {"vectors": nvec, "max_abs_diff": worst}
    res["detectors"], res["holm_shipped"], res["court"], res["dependence"] = det_rows, holm_rows, court_rows, block_rows
    comp = [r for r in det_rows if "p_ok" in r]
    unders = [r for r in det_rows if "p_ok" not in r]
    res["summary"] = {
        "detector_pvalues_compared": len(comp), "detector_pvalues_agree": sum(r["p_ok"] for r in comp),
        "detector_cis_agree": sum(r["ci_ok"] for r in comp),
        "detector_underpowered_total": len(unders), "detector_underpowered_agree": sum(1 for r in unders if r["agree"]),
        "holm_shipped_compared": len(holm_rows), "holm_shipped_agree": sum(r["agree"] for r in holm_rows),
        "holm_shipped_max_abs_diff": max((r["abs_diff"] for r in holm_rows), default=0.0),
        "court_compared": len(court_rows), "court_agree": sum(r["agree"] for r in court_rows),
        "court_pvalues_compared": sum(1 for r in court_rows if "p_ok" in r), "court_pvalues_agree": sum(r.get("p_ok", False) for r in court_rows),
        "labels_identical": sum(v["after_loss_labels_identical"] for v in res["traders"].values()), "traders": len(TRADERS),
        "ours_vs_arch_iid_agree": sum(b["ours_vs_arch_iid_ok"] for b in block_rows), "dependence_traders": len(block_rows),
        "stationary_b5_width_ratio_min": min(b["arch_stationary_b5_width_ratio"] for b in block_rows),
        "stationary_b5_width_ratio_max": max(b["arch_stationary_b5_width_ratio"] for b in block_rows),
        "ci_zero_status_changes": sum(b["zero_in_iid_ci"] != b["zero_in_stationary_b5_ci"] for b in block_rows),
    }
    merge_results("crosscheck", res)
    return res


if __name__ == "__main__":
    import json
    out = main()
    print(json.dumps(out["summary"], indent=2))
    for r in out["detectors"] + out["court"] + out["dependence"]:
        if not r.get("agree", r.get("ours_vs_arch_iid_ok", True)):
            print("DISAGREE", r)
