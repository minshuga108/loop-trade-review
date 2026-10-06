"""Small, dependency-light statistics used by the detectors and the court."""
from __future__ import annotations

import numpy as np


def rng(seed: int | None) -> np.random.Generator:
    return np.random.default_rng(seed)


def median_log_gap(a: np.ndarray, b: np.ndarray) -> float:
    """median(log a) - median(log b); both inputs must be positive."""
    return float(np.median(np.log(a)) - np.median(np.log(b)))


def perm_p_greater(x: np.ndarray, labels: np.ndarray, stat, n_perm: int = 4000, seed: int | None = 0) -> tuple[float, float]:
    """One-sided permutation p-value that stat(x[labels], x[~labels]) is this large.

    The labels are shuffled WITHIN this one trader, so the test is within-trader
    by construction. Returns (observed, p) with the +1 correction.
    """
    g = rng(seed)
    labels = labels.astype(bool)
    obs = stat(x[labels], x[~labels])
    ge = 0
    lab = labels.copy()
    for _ in range(n_perm):
        g.shuffle(lab)
        if stat(x[lab], x[~lab]) >= obs - 1e-12:
            ge += 1
    return obs, (ge + 1) / (n_perm + 1)


def bootstrap_ci(values: np.ndarray, stat, n_boot: int = 2000, alpha: float = 0.05, seed: int | None = 0) -> tuple[float, float]:
    g = rng(seed)
    n = len(values)
    if n == 0:
        return (float("nan"), float("nan"))
    out = np.empty(n_boot)
    for i in range(n_boot):
        out[i] = stat(values[g.integers(0, n, n)])
    return (float(np.quantile(out, alpha / 2)), float(np.quantile(out, 1 - alpha / 2)))


def holm(pvals: list[float | None]) -> list[float | None]:
    """Holm step-down adjusted p-values; None (no test) stays None and does not count as a test."""
    idx = [i for i, p in enumerate(pvals) if p is not None]
    order = sorted(idx, key=lambda i: pvals[i])
    m = len(order)
    out: list[float | None] = [None] * len(pvals)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * pvals[i]))
        out[i] = run
    return out
