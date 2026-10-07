"""Second batch of behaviour detectors on round trips: overtrading days, fee drag, revenge re-entry.

Same contract as detectors.py: a finding is FLAGGED only when it clears a
minimum sample, an effect-size floor and a within-trader permutation p-value;
otherwise it is NOT_FLAGGED or UNDERPOWERED. Fee drag is descriptive only (an
interval, no p-value), so its status is DESCRIPTIVE or UNDERPOWERED.
Holding-time and size-after-loss features live in detectors.py and are not
duplicated here. Nothing here guesses intent or emotion: "revenge re-entry" is
a name for a timing-and-size pattern, not a claim about the trader's mood.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .detectors import MIN_PER_GROUP, Finding
from .dependence import assess
from .ledger import EPS
from .schema import Fill, RoundTrip
from .stats import perm_p_greater

DAY_MS = 86_400_000

# --- pre-registered constants (fixed before looking at any demo wallet; never tuned on them) ---
OVERTRADE_PERCENTILE = 90.0      # a day is "heavy" when its trip count exceeds the trader's own 90th percentile
MIN_ACTIVE_DAYS = 20             # fewer active UTC days than this and the percentile is not meaningful
REVENGE_WINDOW_MS = 15 * 60_000  # re-entry on the same symbol within 15 minutes of a close
REVENGE_SIZE_MULT = 1.4          # first-order notional at least 1.4x the trader's median first-order notional
EFFECT_FLOOR_SD = 0.25           # mean pnl gap must be at least 0.25 standard deviations of the trader's trip pnl
MIN_TRIPS_FEE_DRAG = 20          # fee drag needs at least this many trips with known fees
MIN_WINNERS_FEE_DRAG = 5         # ... and at least this many trips with positive gross pnl
ALPHA = 0.05


def _mean_gap(a: np.ndarray, b: np.ndarray) -> float:
    """mean(b) - mean(a): positive when group a (the labelled group) earns less per trip."""
    return float(np.mean(b) - np.mean(a))


def _gap_finding(name: str, pnl: np.ndarray, labels: np.ndarray, detail: str, why_underpowered: str,
                 n_perm: int, seed: int, extra: dict) -> Finding:
    labels = labels.astype(bool)
    n_a, n_b = int(labels.sum()), int((~labels).sum())
    if min(n_a, n_b) < MIN_PER_GROUP:
        return Finding(name, "UNDERPOWERED", n_a, n_b, float("nan"), (float("nan"),) * 2, float("nan"),
                       f"needs at least {MIN_PER_GROUP} trips in each group ({why_underpowered}: has {n_a} and {n_b})",
                       extra)
    dep = assess(pnl)                  # serial dependence in per-trip pnl: block-permute the labels, block length from the data
    obs, p = perm_p_greater(pnl, labels, _mean_gap, n_perm, seed, block=dep.block)
    effect = -obs   # mean(labelled) - mean(other), dollars per trip; negative = labelled trips earn less
    g = np.random.default_rng(seed)
    a, b = pnl[labels], pnl[~labels]
    boots = [float(np.mean(a[g.integers(0, n_a, n_a)]) - np.mean(b[g.integers(0, n_b, n_b)])) for _ in range(1500)]
    ci = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
    sd = float(np.std(pnl, ddof=1)) if len(pnl) > 1 else 0.0
    floor = EFFECT_FLOOR_SD * sd
    flagged = p < ALPHA and obs >= floor and obs > 0
    extra = dict(extra, block_length=dep.block, effective_n=dep.ess, effect_floor=floor, mean_labelled=float(np.mean(a)), mean_other=float(np.mean(b)))
    if dep.detected:
        detail += f" Per-trip pnl is serially dependent (lag-1 autocorrelation {dep.rho1:.2f}), so the p-value comes from a block permutation (block length {dep.block}), not single-trip shuffling."
    return Finding(name, "FLAGGED" if flagged else "NOT_FLAGGED", n_a, n_b, effect, ci, p, detail, extra)


# ---------------------------------------------------------------- (a) overtrading clusters

def heavy_day_labels(trips: list[RoundTrip]) -> tuple[np.ndarray, float, int]:
    """True for trips opened on a UTC day whose trip count exceeds the trader's own 90th percentile.

    Only active days (at least one trip opened) enter the percentile. Returns
    (labels, threshold, number of active days).
    """
    days = np.array([t.t_open_ms // DAY_MS for t in trips], dtype=np.int64)
    if len(days) == 0:
        return np.zeros(0, dtype=bool), float("nan"), 0
    uniq, counts = np.unique(days, return_counts=True)
    thr = float(np.percentile(counts, OVERTRADE_PERCENTILE))
    heavy_days = set(uniq[counts > thr].tolist())
    return np.array([d in heavy_days for d in days.tolist()], dtype=bool), thr, int(len(uniq))


def overtrading_clusters(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> Finding:
    labels, thr, n_days = heavy_day_labels(trips)
    pnl = np.array([t.net_pnl for t in trips], dtype=float)
    extra = {"day_count_threshold": thr, "active_days": n_days,
             "heavy_days": int(len({t.t_open_ms // DAY_MS for t, h in zip(trips, labels) if h}))}
    if n_days < MIN_ACTIVE_DAYS:
        return Finding("overtrading_clusters", "UNDERPOWERED", int(labels.sum()), int((~labels).sum()), float("nan"),
                       (float("nan"),) * 2, float("nan"),
                       f"needs at least {MIN_ACTIVE_DAYS} active UTC days (has {n_days})", extra)
    return _gap_finding(
        "overtrading_clusters", pnl, labels,
        f"mean net pnl per trip on days with more trips than your own {OVERTRADE_PERCENTILE:.0f}th percentile "
        f"(more than {thr:g} trips) versus other days (within-trader permutation test; trips treated as exchangeable)",
        "heavy-day trips and other trips", n_perm, seed, extra)


# ---------------------------------------------------------------- (b) fee drag

def trip_fills(fills: list[Fill]) -> dict[tuple[str, int, str], list[Fill]]:
    """Segment fills into flat-to-flat trips exactly as ledger.to_round_trips does.

    Keyed by (symbol, t_open_ms, first_order_id), which identifies a RoundTrip.
    """
    by_sym: dict[str, list[Fill]] = defaultdict(list)
    for f in fills:
        by_sym[f.symbol].append(f)
    out: dict[tuple[str, int, str], list[Fill]] = {}
    for sym, fs in by_sym.items():
        fs = sorted(fs, key=lambda x: (x.t_ms, x.exec_id))
        cur: list[Fill] | None = None
        for f in fs:
            signed = f.size if f.side == "buy" else -f.size
            after = f.start_position + signed
            if cur is None:
                if abs(f.start_position) < EPS and f.is_open:
                    cur = [f]
                else:
                    continue
            else:
                cur.append(f)
            if abs(after) < EPS:
                out[(sym, cur[0].t_ms, cur[0].order_id)] = cur
                cur = None
    return out


def trip_fees(fills: list[Fill], trips: list[RoundTrip]) -> np.ndarray:
    """Total fee (positive = cost) of each trip, from its fills. NaN if a trip's fills are not in `fills`."""
    seg = trip_fills(fills)
    out = np.full(len(trips), np.nan)
    for i, t in enumerate(trips):
        fs = seg.get((t.symbol, t.t_open_ms, t.first_order_id))
        if fs is not None:
            out[i] = sum(x.fee for x in fs)
    return out


@dataclass
class FeeDrag:
    status: str                       # DESCRIPTIVE | UNDERPOWERED
    n_trips: int
    total_fees: float
    gross_profit: float               # sum of gross (pre-fee) pnl over trips whose gross pnl is positive
    share: float                      # total_fees / gross_profit
    ci: tuple[float, float]           # bootstrap interval over trips (descriptive, not a test)
    share_of_gross_total: float       # total_fees / sum of all gross pnl, NaN when that sum is not positive
    detail: str = ""
    extra: dict = field(default_factory=dict)


def _share(fees: np.ndarray, gross: np.ndarray) -> float:
    gp = float(np.sum(gross[gross > 0]))
    return float(np.sum(fees) / gp) if gp > 0 else float("nan")


def fee_drag(trips: list[RoundTrip], fees: np.ndarray, n_boot: int = 2000, seed: int = 0) -> FeeDrag:
    """Fees as a share of gross profit, with a bootstrap interval. Descriptive: no p-value.

    gross pnl of a trip = net_pnl + its fees (net_pnl already has every fee taken out).
    Gross profit is the usual definition: the sum of gross pnl over trips that made money
    before fees. Trips whose fees are unknown (NaN) are dropped and counted in extra.
    """
    fees = np.asarray(fees, dtype=float)
    known = ~np.isnan(fees)
    net = np.array([t.net_pnl for t in trips], dtype=float)[known]
    f = fees[known]
    gross = net + f
    n = int(known.sum())
    n_win = int(np.sum(gross > 0))
    extra = {"trips_without_fee_data": int((~known).sum()), "n_gross_winners": n_win}
    total_f = float(np.sum(f))
    gp = float(np.sum(gross[gross > 0]))
    gt = float(np.sum(gross))
    sgt = total_f / gt if gt > 0 else float("nan")
    if n < MIN_TRIPS_FEE_DRAG or n_win < MIN_WINNERS_FEE_DRAG:
        return FeeDrag("UNDERPOWERED", n, total_f, gp, float("nan"), (float("nan"),) * 2, sgt,
                       f"needs at least {MIN_TRIPS_FEE_DRAG} trips with fee data and {MIN_WINNERS_FEE_DRAG} "
                       f"gross winners (has {n} and {n_win})", extra)
    share = _share(f, gross)
    g = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        s = g.integers(0, n, n)
        boots[i] = _share(f[s], gross[s])
    boots = boots[~np.isnan(boots)]
    ci = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
    return FeeDrag("DESCRIPTIVE", n, total_f, gp, share, ci, sgt,
                   "fees paid as a share of gross profit (sum of pre-fee pnl on trips that made money before fees); "
                   "95% bootstrap interval over trips", extra)


# ---------------------------------------------------------------- (c) revenge re-entry

def reentry_labels(trips: list[RoundTrip]) -> tuple[np.ndarray, np.ndarray, float]:
    """Label each trip as a same-symbol re-entry and, among those, as a revenge re-entry.

    re-entry: the most recent trip on the SAME symbol that closed before this one opened
      closed at most REVENGE_WINDOW_MS earlier.
    revenge: a re-entry whose prior same-symbol trip lost money (net_pnl < 0) and whose
      first-order notional is at least REVENGE_SIZE_MULT times the trader's median first-order notional
      (median over the whole history: a descriptive baseline, not a trading signal).
    Returns (is_reentry, is_revenge, median_notional).
    """
    n = len(trips)
    med = float(np.median([t.first_order_notional for t in trips])) if n else float("nan")
    is_re = np.zeros(n, dtype=bool)
    is_rv = np.zeros(n, dtype=bool)
    by_sym: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(trips):
        by_sym[t.symbol].append(i)
    for sym, idx in by_sym.items():
        closes = sorted(idx, key=lambda i: trips[i].t_close_ms)
        close_t = [trips[j].t_close_ms for j in closes]
        for i in idx:
            t = trips[i]
            k = bisect_right(close_t, t.t_open_ms) - 1
            while k >= 0 and closes[k] == i:      # a zero-length trip must not be its own prior
                k -= 1
            if k < 0:
                continue
            prior = closes[k]
            gap = t.t_open_ms - trips[prior].t_close_ms
            if gap <= REVENGE_WINDOW_MS:
                is_re[i] = True
                if trips[prior].net_pnl < 0 and t.first_order_notional >= REVENGE_SIZE_MULT * med:
                    is_rv[i] = True
    return is_re, is_rv, med


def revenge_reentry(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> Finding:
    """Net pnl of revenge re-entries versus the trader's other same-symbol re-entries.

    The test is on dollars per trip, as the user pays them, so a larger revenge size
    is part of the measured cost; extra carries the mean return per unit of opened
    notional of both groups so a reader can see whether the gap is size or decisions.
    """
    is_re, is_rv, med = reentry_labels(trips)
    idx = np.where(is_re)[0]
    pnl = np.array([trips[i].net_pnl for i in idx], dtype=float)
    lab = is_rv[idx]
    ret = np.array([trips[i].net_pnl / trips[i].opened_notional if trips[i].opened_notional > 0 else np.nan
                    for i in idx])
    extra = {"median_first_order_notional": med, "n_reentries": int(len(idx)),
             "mean_return_revenge": float(np.nanmean(ret[lab])) if lab.any() else float("nan"),
             "mean_return_other_reentries": float(np.nanmean(ret[~lab])) if (~lab).any() else float("nan")}
    return _gap_finding(
        "revenge_reentry", pnl, lab,
        f"mean net pnl of same-symbol re-entries within {REVENGE_WINDOW_MS // 60_000} minutes of a losing close "
        f"at {REVENGE_SIZE_MULT}x or more of your median size, versus your other same-symbol re-entries "
        f"(within-trader permutation test)",
        "revenge re-entries and other re-entries", n_perm, seed, extra)


def run_all(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> list[Finding]:
    return [overtrading_clusters(trips, n_perm, seed), revenge_reentry(trips, n_perm, seed)]
