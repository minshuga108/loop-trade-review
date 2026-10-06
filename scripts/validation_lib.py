"""Validation helpers written by us from published formulas (no code copied from any library).

- pbo_cscv: Probability of Backtest Overfitting by combinatorially symmetric cross-validation,
  Bailey, Borwein, Lopez de Prado, Zhu (2015), "The Probability of Backtest Overfitting".
- dsr / psr: Probabilistic and Deflated Sharpe Ratio, Bailey and Lopez de Prado (2014),
  "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality".
Dev-only (scripts/): nothing here is imported by the app.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats as sst

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "validation_results.json"
EULER_GAMMA = 0.5772156649015329


def merge_results(key: str, value) -> None:
    cur = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    cur[key] = value
    RESULTS.write_text(json.dumps(cur, indent=2, sort_keys=True), encoding="utf-8")


def load_results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}


def pbo_cscv(perf: np.ndarray, s: int = 16) -> dict:
    """perf: T x N matrix, one column per trial (strategy), rows in time order.

    Split the rows into s contiguous blocks; for each of the C(s, s/2) ways to pick half of the
    blocks as in-sample, find the trial with the best in-sample mean, and rank it among all trials
    out-of-sample. omega = rank/(N+1) (rank 1 = worst, ties averaged); logit = ln(omega/(1-omega));
    PBO = share of splits with logit <= 0 (the in-sample winner is at or below the OOS median).
    A degenerate split where every trial ties lands exactly at the median and counts as overfit.
    """
    t, n = perf.shape
    if n < 2 or t < 2 * s:
        return {"pbo": float("nan"), "n_splits": 0, "reason": f"needs >=2 trials and >={2*s} rows (has {n}, {t})"}
    blocks = np.array_split(np.arange(t), s)
    sums = np.stack([perf[b].sum(axis=0) for b in blocks])            # s x n
    cnts = np.array([len(b) for b in blocks], dtype=float)
    combos = np.array(list(itertools.combinations(range(s), s // 2)))   # C x s/2
    tot_s, tot_c = sums.sum(axis=0), cnts.sum()
    is_s = sums[combos].sum(axis=1)                                       # C x n
    is_c = cnts[combos].sum(axis=1)[:, None]
    is_mean = is_s / is_c
    oos_mean = (tot_s - is_s) / (tot_c - is_c)
    best = np.argmax(is_mean, axis=1)
    ranks = sst.rankdata(oos_mean, axis=1)
    rb = ranks[np.arange(len(best)), best]
    omega = rb / (n + 1.0)
    logit = np.log(omega / (1 - omega))
    oos_best = oos_mean[np.arange(len(best)), best]
    return {"pbo": float(np.mean(logit <= 1e-12)), "n_splits": int(len(best)),
            "p_oos_best_not_positive": float(np.mean(oos_best <= 0)),
            "mean_oos_rank_of_is_best": float(np.mean(rb)), "n_trials": int(n)}


def sharpe(x: np.ndarray) -> float:
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    return float(np.mean(x) / sd) if sd > 0 else 0.0


def psr(x: np.ndarray, sr0: float = 0.0) -> float:
    """Probability the true Sharpe exceeds sr0, given skew and kurtosis (per-period Sharpe)."""
    t = len(x)
    if t < 3:
        return float("nan")
    sr = sharpe(x)
    g3 = float(sst.skew(x))
    g4 = float(sst.kurtosis(x, fisher=False))
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    if den <= 0:
        return float("nan")
    return float(sst.norm.cdf((sr - sr0) * np.sqrt(t - 1) / np.sqrt(den)))


def expected_max_sr(var_sr: float, n_trials: int) -> float:
    """SR0 = sqrt(V[SR]) * ((1-g) Phi^-1(1-1/N) + g Phi^-1(1-1/(N e)))  (expected max of N trials under H0)."""
    if n_trials < 2:
        return 0.0
    return float(np.sqrt(var_sr) * ((1 - EULER_GAMMA) * sst.norm.ppf(1 - 1.0 / n_trials)
                                    + EULER_GAMMA * sst.norm.ppf(1 - 1.0 / (n_trials * np.e))))


def dsr(perf: np.ndarray) -> dict:
    """Deflated Sharpe of the best trial (by mean/sd) in a T x N matrix of per-period results."""
    t, n = perf.shape
    srs = np.array([sharpe(perf[:, j]) for j in range(n)])
    j = int(np.argmax(srs))
    var_sr = float(np.var(srs, ddof=1)) if n > 1 else 0.0
    sr0 = expected_max_sr(var_sr, n)
    live = perf[:, np.std(perf, axis=0) > 0]          # a rule that never binds has zero variance: no correlation to speak of
    avg_corr = float(np.mean(np.corrcoef(live.T)[np.triu_indices(live.shape[1], 1)])) if live.shape[1] > 1 else float("nan")
    return {"best_trial": j, "sr_best": float(srs[j]), "sr0_deflation": sr0, "psr0": psr(perf[:, j], 0.0),
            "dsr": psr(perf[:, j], sr0), "n_trials": int(n), "avg_trial_corr": avg_corr}


if __name__ == "__main__":
    sys.exit("library module")
