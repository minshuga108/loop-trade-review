"""Serial-dependence tools: autocorrelation, Ljung-Box, effective sample size, a data-driven block length, block permutation.

Why this exists. The habit tests and the court shuffle a per-trip label (after a loss, heavy day, ...) against per-trip
outcomes as if trips were exchangeable. If outcomes are serially dependent (a loss tends to be followed by a loss) the
shuffled statistic varies LESS than the real one would under "no habit", so p-values are too small. Block permutation
(shuffling contiguous blocks of the label sequence, block length from the data) keeps the dependence in the null.

Block length: Politis-White (2004) flat-top lag-window rule for the stationary bootstrap, our own implementation
(tests compare it with arch.bootstrap.optimal_block_length where arch is installed). Block length is 1 (an ordinary
permutation, unchanged behaviour) unless a Ljung-Box test says the series is serially dependent.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as _sps

LB_LAGS = 5
LB_ALPHA = 0.01          # dependence is "detected" only on strong evidence, so independent data is almost never re-routed
MIN_N = 30


def acf(x: np.ndarray, nlags: int) -> np.ndarray:
    """Sample autocorrelations at lags 0..nlags (biased denominator, as statsmodels.tsa.stattools.acf)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    d = x - x.mean()
    var = float(np.dot(d, d))
    if n < 2 or var <= 0:
        return np.r_[1.0, np.zeros(nlags)]
    out = np.empty(nlags + 1)
    for k in range(nlags + 1):
        out[k] = float(np.dot(d[: n - k], d[k:])) / var if k < n else 0.0
    return out


def ljung_box(x: np.ndarray, lags: int = LB_LAGS) -> tuple[float, float]:
    """(Q, p) of the Ljung-Box test of no autocorrelation up to `lags`."""
    n = len(x)
    lags = max(1, min(lags, n - 2))
    r = acf(x, lags)[1:]
    q = n * (n + 2) * float(np.sum(r ** 2 / (n - np.arange(1, lags + 1))))
    return q, float(_sps.chi2.sf(q, lags))


def effective_n(x: np.ndarray, lags: int = LB_LAGS) -> float:
    """n / (1 + 2 sum_k (1 - k/(L+1)) rho_k) with a Bartlett window, floored at 1 and capped at n (no credit for negative dependence)."""
    n = len(x)
    if n < 3:
        return float(n)
    L = max(1, min(lags, n - 2))
    r = acf(x, L)[1:]
    w = 1 - np.arange(1, L + 1) / (L + 1)
    return float(min(n, max(1.0, n / max(1e-9, 1 + 2 * float(np.sum(w * r))))))


def optimal_block_length(x: np.ndarray) -> float:
    """Politis-White stationary-bootstrap block length (flat-top lag window, Politis-Romano style), our implementation."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 10:
        return 1.0
    kn = max(5, int(np.ceil(np.sqrt(np.log10(n)))))
    mmax = int(np.ceil(np.sqrt(n))) + kn
    r = acf(x, min(mmax, n - 1))
    thr = 2 * np.sqrt(np.log10(n) / n)
    m = 0
    for k in range(1, len(r) - kn + 1):
        if np.all(np.abs(r[k:k + kn]) < thr):
            m = max(k - 1, 0)
            break
    else:
        m = len(r) - kn
    M = min(2 * max(m, 1), len(r) - 1)
    ks = np.arange(-M, M + 1)
    lam = np.where(np.abs(ks) <= M / 2, 1.0, 2 * (1 - np.abs(ks) / M))
    var = float(np.var(x))
    R = np.array([r[abs(k)] * var for k in ks])
    G = float(np.sum(lam * np.abs(ks) * R))
    Dsb = 2 * float(np.sum(lam * R)) ** 2
    if Dsb <= 0:
        return 1.0
    b = (2 * G * G / Dsb) ** (1 / 3) * n ** (1 / 3)
    return float(min(max(b, 1.0), n / 4))


@dataclass
class Dependence:
    n: int
    rho1: float
    lb_p: float
    ess: float
    detected: bool
    block: int                       # 1 = plain permutation

    def sentence(self) -> str:
        return (f"serial dependence detected in per-trip returns (lag-1 autocorrelation {self.rho1:.2f}, Ljung-Box p={self.lb_p:.4f}; "
                f"effective sample size about {self.ess:.0f} of {self.n}; block length {self.block})")


def assess(x: np.ndarray) -> Dependence:
    """Dependence report for a chronological series. Too short or constant series are reported as not dependent."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < MIN_N or float(np.std(x)) <= 0:
        return Dependence(n, 0.0, 1.0, float(n), False, 1)
    rho = float(acf(x, 1)[1])
    _, p = ljung_box(x)
    det = p < LB_ALPHA and (abs(rho) > 0.1 or p < 1e-6)
    blk = int(round(optimal_block_length(x))) if det else 1
    return Dependence(n, rho, p, effective_n(x), det, max(1, blk))


def block_permute(labels: np.ndarray, block: int, g: np.random.Generator) -> np.ndarray:
    """Permute a label sequence by whole contiguous blocks (order inside a block kept). block <= 1 is an ordinary shuffle."""
    n = len(labels)
    if block <= 1 or n <= block:
        out = labels.copy()
        g.shuffle(out)
        return out
    starts = np.arange(0, n, block)
    order = g.permutation(len(starts))
    return np.concatenate([labels[starts[k]:starts[k] + block] for k in order])


def circular_shift(labels: np.ndarray, g: np.random.Generator) -> np.ndarray:
    return np.roll(labels, int(g.integers(1, max(2, len(labels)))))
