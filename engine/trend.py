"""Trend and drift of a habit over the trader's own history (R11). Pure functions, no I/O.

Per-trip habit score (only information available when the trip opened or closed is used):
  size_after_loss  for each trip that opened after a losing trip:
                   log(first-order size) - median log first-order size of the trader's previous
                   LOCAL_N trips that opened after a win (a local "usual size", so account growth
                   is not mistaken for a habit).
  hold_asymmetry   for each losing trip: log(hold time) - median log hold time of the previous
                   LOCAL_N winning trips that closed before it opened.
exp(median score) is the habit ratio, on the same scale as the detectors (1.0 = no habit).

Walk-forward windows: the trips, in open-time order, are cut into N_WINDOWS consecutive
windows; each window's ratio uses only scores whose baseline came from earlier trips.

Drift alarm: a two-sided tabular CUSUM on the scores standardised by the REFERENCE PERIOD
(the scores of the first REF_FRAC of trips: median and MAD-based robust SD, clipped at Z_CLIP),
with slack K_SD and decision interval h (in reference SDs). h starts at H_SD and is raised to the
95th percentile of the CUSUM maximum over N_SHUFFLE time-order shuffles of the trader's own
scores, so the false-alarm chance on these scores is about 5% (heavy tails included; streaks of
correlated trades are not modelled). Siegmund's run-length approximation for that h is also
reported, computed here, not quoted.

"No change detected" is an answer: the before/after test (Welch, normal approximation)
reports the smallest change it could have detected (80% power, two-sided 5%) and, by the
same power formula, how many more habit trips (and trades, at the trader's own rate) the
next test needs to detect the pre-registered target change. A change is claimed only when
its 95% interval excludes zero.
"""
from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, ConfigDict

from .detectors import after_loss_labels
from .schema import RoundTrip

# --- pre-registered constants (fixed before looking at any demo wallet; never tuned on them) ---
LOCAL_N = 50               # local baseline: the previous 50 comparison trips
MIN_BASELINE = 5           # at least this many earlier comparison trips before a score exists
N_WINDOWS = 4              # walk-forward windows over the history
MIN_WINDOW_SCORES = 8      # a window with fewer scores is UNDERPOWERED
REF_FRAC = 1 / 3           # reference period = first third of the trips (by open time)
MIN_REF_SCORES = 15        # fewer reference scores and no alarm is run
K_SD, H_SD = 0.5, 5.0      # CUSUM slack and decision interval, in reference SDs
N_SHUFFLE = 200            # time-order shuffles used to measure the alarm's false-alarm chance on the trader's own scores
Z_CLIP = 3.0             # standardised scores are clipped at +-3 so one outsized trade cannot ring the alarm alone
ALPHA, POWER = 0.05, 0.80
Z_A, Z_B = 1.959964, 0.841621
TARGET_RATIO = {"size_after_loss": 1.25, "hold_asymmetry": 1.5}   # the detectors' own effect floors
HABITS = ("size_after_loss", "hold_asymmetry")


class Window(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int
    first_ms: int
    last_ms: int
    n_trips: int
    n_scores: int
    status: str                       # MEASURED | UNDERPOWERED
    ratio: float | None
    ci: tuple[float, float] | None


class Cusum(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str                       # ALARM | NO_ALARM | UNDERPOWERED
    reference: dict                   # first_ms, last_ms, n_scores, mean, sd
    k_sd: float
    h_sd: float
    arl0_scores: float | None         # average scores between false alarms when nothing changes
    arl1_scores: float | None         # average scores to alarm after a shift of one reference SD
    false_alarm_shuffled: float | None = None   # share of time-shuffled copies of these scores that also alarm
    upper: list[list[float]]          # [t_ms, C+] after the reference period
    lower: list[list[float]]          # [t_ms, C-]
    alarm_ms: int | None
    alarm_direction: str | None       # "habit grew" | "habit shrank"
    detail: str


class ChangeTest(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str                       # CHANGE_DETECTED | NO_CHANGE_DETECTED | UNDERPOWERED
    n_ref: int
    n_after: int
    ratio_ref: float | None
    ratio_after: float | None
    change_ratio: float | None        # exp(mean after - mean ref)
    change_ci: tuple[float, float] | None
    p: float | None
    mde_ratio: float | None           # smallest change (as a ratio) detectable with 80% power
    target_ratio: float
    more_habit_trips_needed: int | None   # None = target not reachable without a larger reference period
    habit_share: float | None         # share of trips that carry a score (after-loss trips, losing trips)
    more_trades_needed: int | None
    habit_trips_each_needed: int | None = None   # per period, for a fresh equal-sized before/after test
    detail: str


class Trend(BaseModel):
    model_config = ConfigDict(frozen=True)
    habit: str
    n_trips: int
    n_scores: int
    windows: list[Window]
    cusum: Cusum
    test: ChangeTest
    method: str


# ------------------------------------------------------------------ scores
def habit_scores(trips: list[RoundTrip], habit: str) -> list[tuple[int, int, float]]:
    """(trip index in open-time order, t_ms of the trip, score) for every trip that carries the habit."""
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    out: list[tuple[int, int, float]] = []
    if habit == "size_after_loss":
        lab = after_loss_labels(ts)
        calm: list[float] = []
        for i, t in enumerate(ts):
            if t.first_order_notional <= 0:
                continue
            x = math.log(t.first_order_notional)
            if lab[i] == 1 and len(calm) >= MIN_BASELINE:
                out.append((i, t.t_open_ms, x - float(np.median(calm[-LOCAL_N:]))))
            elif lab[i] == 0:
                calm.append(x)
        return out
    if habit == "hold_asymmetry":
        by_close = sorted(range(len(ts)), key=lambda i: ts[i].t_close_ms)
        wins: list[float] = []
        j = 0
        for i, t in enumerate(ts):
            while j < len(by_close) and ts[by_close[j]].t_close_ms < t.t_open_ms:
                w = ts[by_close[j]]
                if w.net_pnl > 0:
                    wins.append(math.log(max(w.hold_ms, 1)))
                j += 1
            if t.net_pnl < 0 and len(wins) >= MIN_BASELINE:
                out.append((i, t.t_close_ms, math.log(max(t.hold_ms, 1)) - float(np.median(wins[-LOCAL_N:]))))
        return out
    raise ValueError(f"unknown habit {habit!r}")


def _boot_median_ci(x: np.ndarray, seed: int = 0, n_boot: int = 600) -> tuple[float, float]:
    g = np.random.default_rng(seed)
    b = np.array([np.median(x[g.integers(0, len(x), len(x))]) for _ in range(n_boot)])
    return float(math.exp(np.quantile(b, 0.025))), float(math.exp(np.quantile(b, 0.975)))


# ------------------------------------------------------------------ CUSUM
def siegmund_arl(shift_sd: float, k: float = K_SD, h: float = H_SD) -> float:
    """Siegmund's approximation of a ONE-sided CUSUM's average run length for a mean shift (in SDs)."""
    d = shift_sd - k
    b = h + 1.166
    if abs(d) < 1e-9:
        return b * b
    return (math.exp(-2 * d * b) + 2 * d * b - 1) / (2 * d * d)


def two_sided_arl(shift_sd: float, k: float = K_SD, h: float = H_SD) -> float:
    return 1.0 / (1.0 / siegmund_arl(shift_sd, k, h) + 1.0 / siegmund_arl(-shift_sd, k, h))


def cusum(times: list[int], z: np.ndarray, k: float = K_SD, h: float = H_SD) -> tuple[list, list, int | None, str | None]:
    """Tabular two-sided CUSUM on standardised values z. Returns (upper, lower, alarm index, direction)."""
    cp = cm = 0.0
    up, lo = [], []
    alarm, direction = None, None
    for i, (t, v) in enumerate(zip(times, z)):
        cp = max(0.0, cp + v - k)
        cm = max(0.0, cm - v - k)
        up.append([t, round(cp, 4)])
        lo.append([t, round(cm, 4)])
        if alarm is None and (cp > h or cm > h):
            alarm, direction = i, ("habit grew" if cp > h else "habit shrank")
    return up, lo, alarm, direction


# ------------------------------------------------------------------ power
def mde(sd_ref: float, n_ref: int, sd_after: float, n_after: int) -> float:
    """Smallest true difference in mean score detectable with POWER at two-sided ALPHA (Welch, normal approx)."""
    return (Z_A + Z_B) * math.sqrt(sd_ref ** 2 / n_ref + sd_after ** 2 / n_after)


def n_after_needed(sd_ref: float, n_ref: int, sd_after: float, target: float) -> int | None:
    """Scores needed AFTER the reference period so that mde(...) <= target. None if the reference alone is too noisy."""
    room = (target / (Z_A + Z_B)) ** 2 - sd_ref ** 2 / n_ref
    if room <= 0:
        return None
    return int(math.ceil(sd_after ** 2 / room))


def n_each_needed(sd_ref: float, sd_after: float, target: float) -> int:
    """Habit trips needed in EACH of two equal periods to detect `target` (log scale) with POWER at ALPHA."""
    return int(math.ceil((Z_A + Z_B) ** 2 * (sd_ref ** 2 + sd_after ** 2) / target ** 2))


def _norm_p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


# ------------------------------------------------------------------ main
def trend(trips: list[RoundTrip], habit: str = "size_after_loss", seed: int = 0) -> Trend:
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    n = len(ts)
    sc = habit_scores(ts, habit)
    idx = np.array([s[0] for s in sc], dtype=int)
    tms = [s[1] for s in sc]
    x = np.array([s[2] for s in sc], dtype=float)

    # walk-forward windows
    windows = []
    edges = np.linspace(0, n, N_WINDOWS + 1).astype(int) if n else np.zeros(N_WINDOWS + 1, dtype=int)
    for w in range(N_WINDOWS):
        lo, hi = int(edges[w]), int(edges[w + 1])
        if hi <= lo:
            continue
        m = (idx >= lo) & (idx < hi)
        xs = x[m]
        ok = len(xs) >= MIN_WINDOW_SCORES
        windows.append(Window(index=w + 1, first_ms=ts[lo].t_open_ms, last_ms=ts[hi - 1].t_open_ms, n_trips=hi - lo,
                              n_scores=int(len(xs)), status="MEASURED" if ok else "UNDERPOWERED",
                              ratio=float(math.exp(np.median(xs))) if ok else None,
                              ci=_boot_median_ci(xs, seed + w) if ok else None))

    # reference period
    cut = int(n * REF_FRAC)
    ref_m = idx < cut
    xr, xa = x[ref_m], x[~ref_m]
    ta = [t for t, m in zip(tms, ref_m) if not m]
    ref = {"first_ms": ts[0].t_open_ms if n else None, "last_ms": ts[cut - 1].t_open_ms if cut else None,
           "n_trips": cut, "n_scores": int(len(xr)), "mean": None, "sd": None}
    target = TARGET_RATIO[habit]
    share = float(len(x) / n) if n else None
    if len(xr) < MIN_REF_SCORES or float(np.std(xr, ddof=1) if len(xr) > 1 else 0) <= 0:
        why = f"the reference period (first third, {cut} trips) has {len(xr)} habit trips; needs {MIN_REF_SCORES}"
        cs = Cusum(status="UNDERPOWERED", reference=ref, k_sd=K_SD, h_sd=H_SD, arl0_scores=None, arl1_scores=None,
                   upper=[], lower=[], alarm_ms=None, alarm_direction=None, detail=why)
        tt = ChangeTest(status="UNDERPOWERED", n_ref=int(len(xr)), n_after=int(len(xa)), ratio_ref=None, ratio_after=None,
                        change_ratio=None, change_ci=None, p=None, mde_ratio=None, target_ratio=target,
                        more_habit_trips_needed=None, habit_share=share, more_trades_needed=None, detail=why)
        return Trend(habit=habit, n_trips=n, n_scores=int(len(x)), windows=windows, cusum=cs, test=tt, method=__doc__.strip())

    mu, sd = float(np.mean(xr)), float(np.std(xr, ddof=1))
    med = float(np.median(xr))
    ref.update(mean=mu, sd=sd, median=med)
    # control limit: H_SD, raised to the 95th percentile of the CUSUM maximum over time-order shuffles of
    # this trader's own scores, so the false-alarm chance on these scores (heavy tails included) is about 5%
    g = np.random.default_rng(seed)
    allx = np.concatenate([xr, xa])
    maxima = []
    for _ in range(N_SHUFFLE if len(xa) else 0):
        s = g.permutation(allx)
        r_, a_ = s[:len(xr)], s[len(xr):]
        m_, sd_ = float(np.median(r_)), float(np.std(r_, ddof=1)) or sd
        u_, l_, _, _ = cusum(ta, np.clip((a_ - m_) / sd_, -Z_CLIP, Z_CLIP), h=float("inf"))
        maxima.append(max(max(p[1] for p in u_), max(p[1] for p in l_)))
    h_used = max(H_SD, float(np.quantile(maxima, 1 - ALPHA))) if maxima else H_SD
    false_alarm = float(np.mean(np.array(maxima) > h_used)) if maxima else None
    up, lo_, al, direction = cusum(ta, np.clip((xa - med) / sd, -Z_CLIP, Z_CLIP), h=h_used)
    arl0, arl1 = two_sided_arl(0.0, h=h_used), two_sided_arl(1.0, h=h_used)
    if len(xa) == 0:
        cs_status, cs_detail = "UNDERPOWERED", "no habit trips after the reference period yet"
    elif al is None:
        cs_status = "NO_ALARM"
        cs_detail = f"no drift alarm over {len(xa)} habit trips after the reference period"
    else:
        cs_status = "ALARM"
        cs_detail = f"drift alarm at habit trip {al + 1} after the reference period: {direction}"
    cs = Cusum(status=cs_status, reference=ref, k_sd=K_SD, h_sd=h_used, arl0_scores=arl0, arl1_scores=arl1,
               false_alarm_shuffled=false_alarm,
               upper=up, lower=lo_, alarm_ms=ta[al] if al is not None else None, alarm_direction=direction, detail=cs_detail)

    # before/after test and power
    if len(xa) < 2:
        tt = ChangeTest(status="UNDERPOWERED", n_ref=int(len(xr)), n_after=int(len(xa)), ratio_ref=math.exp(float(np.median(xr))),
                        ratio_after=None, change_ratio=None, change_ci=None, p=None, mde_ratio=None, target_ratio=target,
                        more_habit_trips_needed=n_after_needed(sd, len(xr), sd, math.log(target)), habit_share=share,
                        more_trades_needed=None, detail="fewer than 2 habit trips after the reference period")
    else:
        sa = float(np.std(xa, ddof=1))
        diff = float(np.mean(xa) - mu)
        se = math.sqrt(sd ** 2 / len(xr) + sa ** 2 / len(xa))
        p = _norm_p_two_sided(diff / se) if se > 0 else 1.0
        ci = (math.exp(diff - Z_A * se), math.exp(diff + Z_A * se))
        m = mde(sd, len(xr), sa, len(xa))
        need_total = n_after_needed(sd, len(xr), sa, math.log(target))
        more = None if need_total is None else max(0, need_total - len(xa))
        more_trades = None if (more is None or not share) else int(math.ceil(more / share))
        detected = ci[0] > 1.0 or ci[1] < 1.0
        if detected:
            status = "CHANGE_DETECTED"
            detail = (f"the habit ratio moved by {math.exp(diff):.2f}x after the reference period; "
                      f"95% interval {ci[0]:.2f}x to {ci[1]:.2f}x excludes no change")
        else:
            status = "NO_CHANGE_DETECTED"
            detail = (f"no change detected. With {len(xr)} reference and {len(xa)} later habit trips this test could only "
                      f"see a change of {math.exp(m):.2f}x or more (80% power, 5% two-sided)")
        tt = ChangeTest(status=status, n_ref=int(len(xr)), n_after=int(len(xa)), ratio_ref=math.exp(float(np.median(xr))),
                        ratio_after=math.exp(float(np.median(xa))), change_ratio=math.exp(diff), change_ci=ci, p=p,
                        mde_ratio=math.exp(m), target_ratio=target, more_habit_trips_needed=more, habit_share=share,
                        more_trades_needed=more_trades, habit_trips_each_needed=n_each_needed(sd, sa, math.log(target)),
                        detail=detail)
    return Trend(habit=habit, n_trips=n, n_scores=int(len(x)), windows=windows, cusum=cs, test=tt, method=__doc__.strip())
