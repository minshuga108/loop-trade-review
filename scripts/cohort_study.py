"""Cohort study on the public Hyperliquid wallets built by scripts/build_cohort.py.

    python scripts/cohort_study.py [--raw ../data/cohort_raw] [--out cohort_results.json] [--jobs 4]

Plan pre-registered in COHORT_NOTES.md section 4. Engine code is used unchanged:
- per wallet: size_after_loss, hold_asymmetry (detectors), overtrading_clusters, revenge_reentry (detectors2),
  each a within-trader permutation test as implemented;
- Benjamini-Hochberg at q = 0.10 across wallets, per detector;
- pooled versus within-trader: the same statistic on every wallet's trips stacked, with labels shuffled
  across all trips (pooled p) or only inside each wallet (within-trader p);
- replication of Blotter's (JUICEWRLD998) weekend and 60-minutes-after-a-loss win-rate gaps, same contrast;
- the walk-forward court with the 4 cap rules on every wallet, with its trial-count ledger.

Reads kept/W###.csv (ordinal ids) and the stratum from progress.json; writes no address, no address
prefix, no order id and no leaderboard pnl to any output.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import hyperliquid_csv  # noqa: E402
from engine import detectors, detectors2, ledger  # noqa: E402
from engine.court import Court, Rule  # noqa: E402
from engine.detectors import MIN_PER_GROUP, after_loss_labels  # noqa: E402
from engine.schema import RoundTrip  # noqa: E402
from engine.stats import median_log_gap, perm_p_greater  # noqa: E402
from engine.walkforward import judge_wf  # noqa: E402

DEFAULT_RAW = Path(r"C:\Users\neon_\bitget\data\cohort_raw")
Q_FDR = 0.10
N_PERM_WALLET = 4000
N_PERM_POOLED = 2000
N_PERM_COURT = 2000
CAP_RULES = (1.0, 1.5, 2.0, 3.0)
AFTER_LOSS_WINDOW_MS = 60 * 60_000
DETECTORS = ("size_after_loss", "hold_asymmetry", "overtrading_clusters", "revenge_reentry")
BLOTTER = ("weekend_entry", "entry_within_60m_of_loss")


# ------------------------------------------------------------------ statistics helpers (pure)

def bh_reject(pvals, q: float = Q_FDR) -> np.ndarray:
    """Benjamini-Hochberg step-up. NaN p-values are never rejected and do not count in m."""
    p = np.asarray(pvals, dtype=float)
    out = np.zeros(len(p), dtype=bool)
    ok = ~np.isnan(p)
    m = int(ok.sum())
    if m == 0:
        return out
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx], kind="mergesort")]
    thr = q * np.arange(1, m + 1) / m
    passed = np.where(p[order] <= thr)[0]
    if len(passed):
        out[order[: passed[-1] + 1]] = True
    return out


def perm_p_grouped(x: np.ndarray, labels: np.ndarray, groups: np.ndarray, stat, within: bool,
                   n_perm: int = N_PERM_POOLED, seed: int = 0) -> tuple[float, float]:
    """One-sided permutation p that stat(x[labels], x[~labels]) is this large.

    within=False shuffles labels across every row (the naive pooled test); within=True shuffles them
    only inside each group (stratified: a wallet keeps its own number of labelled trips).
    """
    labels = labels.astype(bool)
    obs = stat(x[labels], x[~labels])
    g = np.random.default_rng(seed)
    lab = labels.copy()
    blocks = [np.where(groups == k)[0] for k in np.unique(groups)] if within else None
    ge = 0
    for _ in range(n_perm):
        if within:
            for b in blocks:
                lab[b] = lab[b][g.permutation(len(b))]
        else:
            g.shuffle(lab)
        if stat(x[lab], x[~lab]) >= obs - 1e-12:
            ge += 1
    return float(obs), (ge + 1) / (n_perm + 1)


def win_rate_gap(a: np.ndarray, b: np.ndarray) -> float:
    """Win rate of the other group minus win rate of the labelled group (positive = labelled wins less)."""
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    return float(np.mean(b) - np.mean(a))


def mean_gap(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(b) - np.mean(a))


def sign_test(effects, null: float) -> dict:
    e = np.asarray([x for x in effects if not math.isnan(x)], dtype=float)
    above, below = int(np.sum(e > null)), int(np.sum(e < null))
    p = float(sps.binomtest(above, above + below, 0.5).pvalue) if above + below else float("nan")
    return {"above_null": above, "below_null": below, "two_sided_p": p}


def dist(values) -> dict:
    v = np.asarray([x for x in values if not (x is None or math.isnan(x))], dtype=float)
    if len(v) == 0:
        return {"n": 0}
    q = np.quantile(v, [0, 0.25, 0.5, 0.75, 1])
    return {"n": int(len(v)), "min": float(q[0]), "q25": float(q[1]), "median": float(q[2]),
            "q75": float(q[3]), "max": float(q[4])}


# ------------------------------------------------------------------ labels (per wallet)

def weekend_labels(trips: list[RoundTrip]) -> np.ndarray:
    return np.array([datetime.fromtimestamp(t.t_open_ms / 1000, tz=timezone.utc).weekday() >= 5 for t in trips],
                    dtype=bool)


def recent_loss_labels(trips: list[RoundTrip], window_ms: int = AFTER_LOSS_WINDOW_MS, loss: bool = True) -> np.ndarray:
    """True if the trader's most recent close (any symbol) before this open was a loss within window_ms.

    loss=False gives the mirror label (most recent close was a WIN within window_ms), used only by the
    exploratory serial-correlation check."""
    closes = sorted(trips, key=lambda t: t.t_close_ms)
    ct = np.array([t.t_close_ms for t in closes], dtype=np.int64)
    out = np.zeros(len(trips), dtype=bool)
    for i, t in enumerate(trips):
        k = int(np.searchsorted(ct, t.t_open_ms, side="left")) - 1
        if k >= 0 and t.t_open_ms - ct[k] <= window_ms and ((closes[k].net_pnl < 0) == loss):
            out[i] = True
    return out


def pooled_inputs(trips: list[RoundTrip]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """For each test: (values, labels, standardised values) exactly as the per-wallet test builds them."""
    out = {}
    lab = after_loss_labels(trips)
    notional = np.array([t.first_order_notional for t in trips], dtype=float)
    keep = (lab >= 0) & (notional > 0)
    v = notional[keep]
    out["size_after_loss"] = (v, lab[keep] == 1, v / np.median(v) if len(v) else v)
    hold = np.array([max(t.hold_ms, 1) for t in trips], dtype=float)
    out["hold_asymmetry"] = (hold, np.array([t.net_pnl < 0 for t in trips]), hold / np.median(hold))
    pnl = np.array([t.net_pnl for t in trips], dtype=float)
    heavy, _, _ = detectors2.heavy_day_labels(trips)
    sd = float(np.std(pnl, ddof=1)) or 1.0
    out["overtrading_clusters"] = (pnl, heavy, pnl / sd)
    is_re, is_rv, _ = detectors2.reentry_labels(trips)
    rp = pnl[is_re]
    rsd = float(np.std(rp, ddof=1)) if len(rp) > 1 else 1.0
    out["revenge_reentry"] = (rp, is_rv[is_re], rp / (rsd or 1.0))
    win = (pnl > 0).astype(float)
    out["weekend_entry"] = (win, weekend_labels(trips), win)
    out["entry_within_60m_of_loss"] = (win, recent_loss_labels(trips), win)
    # EXPLORATORY (not pre-registered): entries within 60 minutes after a WIN. If these win MORE than other
    # entries, the after-loss gap is outcome clustering in time, not something specific to losing.
    out["entry_within_60m_of_win"] = (win, recent_loss_labels(trips, loss=False), win)
    return out


POOLED_STAT = {"size_after_loss": median_log_gap, "hold_asymmetry": median_log_gap,
               "overtrading_clusters": mean_gap, "revenge_reentry": mean_gap,
               "weekend_entry": win_rate_gap, "entry_within_60m_of_loss": win_rate_gap,
               "entry_within_60m_of_win": win_rate_gap}


# ------------------------------------------------------------------ per-wallet work

def load_trips(path: Path) -> tuple[list[RoundTrip], int, float]:
    fills = ledger.dedupe(hyperliquid_csv.load(path, account=path.stem))
    trips = ledger.to_round_trips(fills)
    span_d = (max(f.t_ms for f in fills) - min(f.t_ms for f in fills)) / 86_400_000 if fills else 0.0
    return trips, len(fills), span_d


def _finding(f) -> dict:
    return {"status": f.status, "n_a": f.n_a, "n_b": f.n_b, "effect": f.effect, "ci": list(f.ci), "p": f.p,
            "std_effect": float("nan")}


def wallet_job(args: tuple[str, str, int, int, int]) -> dict:
    wid, path, n_perm, n_perm_court, seed = args
    trips, n_fills, span_d = load_trips(Path(path))
    rec = {"wid": wid, "n_fills": n_fills, "n_trips": len(trips), "span_days": round(span_d, 1),
           "fills_per_day": round(n_fills / span_d, 1) if span_d > 0 else None,
           "win_rate": float(np.mean([t.net_pnl > 0 for t in trips])) if trips else None}
    fs = detectors.run_all(trips, n_perm, seed) + detectors2.run_all(trips, n_perm, seed)
    pin = pooled_inputs(trips)
    rec["detectors"] = {}
    for f in fs:
        d = _finding(f)
        if f.detector in ("overtrading_clusters", "revenge_reentry") and f.status != "UNDERPOWERED":
            vals = pin[f.detector][0]
            sd = float(np.std(vals, ddof=1)) if len(vals) > 1 else float("nan")
            d["std_effect"] = f.effect / sd if sd > 0 else float("nan")
        elif f.status != "UNDERPOWERED":
            d["std_effect"] = math.log(f.effect)          # log ratio for the two ratio detectors
        rec["detectors"][f.detector] = d
    # Blotter's two gaps, per wallet (within-trader permutation, same floor of 20 per group)
    rec["blotter"] = {}
    for name in BLOTTER:
        x, lab, _ = pin[name]
        n_a, n_b = int(lab.sum()), int((~lab).sum())
        if min(n_a, n_b) < MIN_PER_GROUP:
            rec["blotter"][name] = {"status": "UNDERPOWERED", "n_a": n_a, "n_b": n_b, "effect": float("nan"),
                                    "p": float("nan")}
            continue
        obs, p = perm_p_greater(x, lab, win_rate_gap, n_perm, seed)
        rec["blotter"][name] = {"status": "TESTED", "n_a": n_a, "n_b": n_b, "effect": obs, "p": p}
    # court: 4 cap rules, ledger of 4 per wallet
    court = Court(n_perm=n_perm_court, seed=seed)
    for m in CAP_RULES:
        court.propose(Rule(value=m))
    rec["court"] = []
    for m in CAP_RULES:
        v = judge_wf(court, trips, Rule(value=m))
        rec["court"].append({"cap_multiple": m, "status": v.status, "p": v.p, "alpha_used": v.alpha_used,
                             "trials": v.trials, "oos_effect": v.test["effect"], "oos_trips": v.test["n_trips"],
                             "oos_affected": v.test["n_affected"]})
    rec["court_trials"] = court.trials
    rec["_pooled"] = {k: [v.tolist(), lab.tolist(), z.tolist()] for k, (v, lab, z) in pin.items()}
    return rec


# ------------------------------------------------------------------ cohort aggregation (pure)

def aggregate(wallets: list[dict], n_perm_pooled: int = N_PERM_POOLED, seed: int = 0) -> dict:
    out: dict = {"n_wallets": len(wallets), "n_round_trips": int(sum(w["n_trips"] for w in wallets)),
                 "n_fills": int(sum(w["n_fills"] for w in wallets)), "fdr_q": Q_FDR, "detectors": {}}
    for name in DETECTORS + BLOTTER:
        src = "detectors" if name in DETECTORS else "blotter"
        ps = [w[src][name]["p"] for w in wallets]
        rej = bh_reject(ps, Q_FDR)
        for w, r in zip(wallets, rej):
            w[src][name]["bh_significant"] = bool(r)
        tested = [w for w in wallets if w[src][name]["status"] != "UNDERPOWERED"]
        effects = [w[src][name]["effect"] for w in tested]
        null = 1.0 if name in ("size_after_loss", "hold_asymmetry") else 0.0
        row = {"tested": len(tested), "underpowered": len(wallets) - len(tested),
               "bh_significant": int(rej.sum()),
               "raw_p_below_0_05": int(sum(1 for w in tested if w[src][name]["p"] < 0.05)),
               "expected_raw_p_below_0_05_if_no_habit": 0.05 * len(tested),
               "effect_distribution": dist(effects),
               "sign_test": sign_test(effects, null)}
        if src == "detectors":
            row["engine_flagged"] = int(sum(1 for w in wallets if w[src][name]["status"] == "FLAGGED"))
            row["std_effect_distribution"] = dist([w[src][name]["std_effect"] for w in tested])
        # pooled versus within-trader
        xs, labs, zs, gs = [], [], [], []
        for k, w in enumerate(wallets):
            v, lab, z = w["_pooled"][name]
            xs += v
            labs += lab
            zs += z
            gs += [k] * len(v)
        x, lab, z, g = (np.array(xs, dtype=float), np.array(labs, dtype=bool), np.array(zs, dtype=float),
                        np.array(gs))
        stat = POOLED_STAT[name]
        pooled = {"n_rows": int(len(x)), "n_labelled": int(lab.sum())}
        if lab.sum() and (~lab).sum():
            obs, p_pool = perm_p_grouped(x, lab, g, stat, within=False, n_perm=n_perm_pooled, seed=seed)
            _, p_within = perm_p_grouped(x, lab, g, stat, within=True, n_perm=n_perm_pooled, seed=seed)
            pooled.update({"statistic": obs, "p_pooled_shuffle": p_pool, "p_within_trader_shuffle": p_within})
            if name in ("overtrading_clusters", "revenge_reentry", "size_after_loss", "hold_asymmetry"):
                zstat = mean_gap if name in ("overtrading_clusters", "revenge_reentry") else median_log_gap
                zobs, zp_pool = perm_p_grouped(z, lab, g, zstat, within=False, n_perm=n_perm_pooled, seed=seed)
                _, zp_within = perm_p_grouped(z, lab, g, zstat, within=True, n_perm=n_perm_pooled, seed=seed)
                pooled["scale_free"] = {"statistic": zobs, "p_pooled_shuffle": zp_pool,
                                        "p_within_trader_shuffle": zp_within}
        row["pooled"] = pooled
        out.setdefault("detectors" if src == "detectors" else "blotter_replication", {})[name] = row
    # EXPLORATORY, not pre-registered: is the after-loss gap just outcome clustering in time?
    name = "entry_within_60m_of_win"
    if all(name in w["_pooled"] for w in wallets):
        x = np.array([v for w in wallets for v in w["_pooled"][name][0]], dtype=float)
        lab = np.array([v for w in wallets for v in w["_pooled"][name][1]], dtype=bool)
        g = np.array([k for k, w in enumerate(wallets) for _ in w["_pooled"][name][0]])
        exp = {"note": "exploratory, added after seeing results; tests whether entries within 60 minutes after a "
                       "WIN win MORE than other entries (statistic = labelled win rate minus other win rate)",
               "n_labelled": int(lab.sum())}
        if lab.sum() and (~lab).sum():
            more = lambda a, b: -win_rate_gap(a, b)  # noqa: E731
            obs, p_pool = perm_p_grouped(x, lab, g, more, within=False, n_perm=n_perm_pooled, seed=seed)
            _, p_within = perm_p_grouped(x, lab, g, more, within=True, n_perm=n_perm_pooled, seed=seed)
            per = []
            for w in wallets:
                xv, lv = np.array(w["_pooled"][name][0]), np.array(w["_pooled"][name][1], dtype=bool)
                if min(lv.sum(), (~lv).sum()) >= MIN_PER_GROUP:
                    per.append(float(np.mean(xv[lv]) - np.mean(xv[~lv])))
            exp.update({"statistic": obs, "p_pooled_shuffle": p_pool, "p_within_trader_shuffle": p_within,
                        "per_wallet_gap_distribution": dist(per), "sign_test": sign_test(per, 0.0)})
        out["exploratory_after_win_60m"] = exp
    # court
    verdicts =[c for w in wallets for c in w["court"]]
    per_rule = {}
    for m in CAP_RULES:
        vs = [c for c in verdicts if c["cap_multiple"] == m]
        per_rule[str(m)] = {s: sum(1 for c in vs if c["status"] == s) for s in ("ACCEPTED", "REJECTED", "UNDERPOWERED")}
    n_judged = sum(1 for c in verdicts if c["status"] != "UNDERPOWERED")
    out["court"] = {
        "rules": list(CAP_RULES), "trials_per_wallet": 4, "alpha_per_rule": 0.05 / 4,
        "cohort_trials": len(verdicts), "judged_not_underpowered": n_judged,
        "per_rule": per_rule,
        "wallets_with_any_accepted": sum(1 for w in wallets if any(c["status"] == "ACCEPTED" for c in w["court"])),
        "wallets_with_all_underpowered": sum(1 for w in wallets if all(c["status"] == "UNDERPOWERED" for c in w["court"])),
        "expected_acceptances_if_no_leak_at_most": round(0.0125 * n_judged, 2),
    }
    return out


def public_wallet_rows(wallets: list[dict], strata: dict[str, int]) -> list[dict]:
    rows = []
    for w in wallets:
        r = {k: v for k, v in w.items() if not k.startswith("_")}
        r["stratum"] = strata.get(w["wid"])
        rows.append(r)
    return rows


def _clean(o):
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 6)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return _clean(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out", type=Path, default=ROOT / "cohort_results.json")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    t0 = time.time()
    prog = json.loads((a.raw / "progress.json").read_text(encoding="utf-8"))
    strata = {t["wid"]: t["stratum"] for t in prog["tried"] if t.get("kept")}
    tried_per = {s: sum(1 for t in prog["tried"] if t["stratum"] == s) for s in range(1, 6)}
    files = sorted((a.raw / "kept").glob("W*.csv"))
    jobs = [(p.stem, str(p), N_PERM_WALLET, N_PERM_COURT, 0) for p in files]
    with ProcessPoolExecutor(a.jobs) as ex:
        wallets = list(ex.map(wallet_job, jobs))
    for w in wallets:
        print(f"{w['wid']} trips {w['n_trips']}", flush=True)
    agg = aggregate(wallets)
    agg["sampling"] = {"leaderboard_rows": prog.get("leaderboard_rows"), "eligible": prog.get("eligible"),
                       "candidates_tried": len(prog["tried"]), "tried_per_stratum": tried_per,
                       "kept_per_stratum": {s: sum(1 for v in strata.values() if v == s) for s in range(1, 6)},
                       "rule": "COHORT_NOTES.md section 2 (pre-registered)"}
    agg["wallets"] = public_wallet_rows(wallets, strata)
    agg["n_perm"] = {"wallet": N_PERM_WALLET, "pooled": N_PERM_POOLED, "court": N_PERM_COURT}
    agg["seconds"] = round(time.time() - t0)
    agg["provenance"] = "REAL_PLATFORM_PUBLIC: Hyperliquid on-chain fills via the public info API; ids are ordinal"
    a.out.write_text(json.dumps(_clean(agg), indent=1), encoding="utf-8")
    print(f"wrote {a.out} in {agg['seconds']} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
