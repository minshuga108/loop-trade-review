"""Third batch of habit detectors, for Bitget stock perps / rTokens: chasing a big prior move, trading outside
US regular hours, averaging down.

Same contract as detectors2.py: a finding is FLAGGED only when it clears a minimum sample, an effect-size floor and a
within-trader permutation p-value (mean net pnl per trip of the labelled trips versus the trader's other trips).
Each finding also carries its CHANCE BASELINE in `extra` (how often the label would be true for a trader with no such
habit) so a reader can see the behaviour share next to the share chance alone gives. A detector that does not apply to
a trader (no equity symbols, no fills, no usable price series) returns None and is NOT counted in the Holm family.
Nothing here guesses intent or emotion.

Pre-registered constants below were fixed before looking at any demo wallet.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

import numpy as np

from .bitget_context import base_of
from .detectors import Finding
from .detectors2 import _gap_finding, trip_fees, trip_fills
from .schema import Fill, RoundTrip

HOUR_MS = 3_600_000
DAY_MS = 86_400_000
CHASE_HOURS = 4                  # look-back window for the prior move
CHASE_SIGMA = 1.0                # a "large" prior move: at least this many sigma of the symbol's own N-hour moves, in the trade's direction
MIN_SIGMA_OBS = 30               # sigma needs at least this many N-hour moves
OWN_MAX_GAP_H = 24               # own-fill price series: the reference fill must be within this many hours before the window start
# US cash session, widest UTC union of EDT (13:30-20:00) and EST (14:30-21:00), Monday to Friday. "Off hours" = outside it,
# so anything labelled off-hours is certainly outside the regular session whichever DST state applies.
OPEN_MIN, CLOSE_MIN = 13 * 60 + 30, 21 * 60
BASELINE_OFF_SHARE = 1.0 - 5 * (CLOSE_MIN - OPEN_MIN) / (7 * 24 * 60)

STOCKS = frozenset("""AAPL AMAT AMD AMZN ASML AVGO BABA COIN CRCL CXMT DELL EWT EWY GOOGL GOOG HOOD INTC LLY META MRVL MSFT MSTR MU
NBIS NFLX NVDA ORCL PLTR QCOM SKHX SMH SMSN SNDK SPY QQQ TSLA TSM XLE ARM BA DIS JPM WMT UBER SHOP PYPL IBM SOXL TQQQ""".split())
CANDLE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "equity_candles"


def equity_base(symbol: str) -> str | None:
    b = base_of(symbol)
    return b if b in STOCKS else None


def is_off_hours(t_ms: int) -> bool:
    wd = (t_ms // DAY_MS + 3) % 7          # 1970-01-01 was a Thursday; Monday = 0
    if wd >= 5:
        return True
    m = (t_ms % DAY_MS) // 60_000
    return not (OPEN_MIN <= m < CLOSE_MIN)


def load_candles(bases) -> dict[str, list[tuple[int, float]]]:
    """Cached public Bitget 1H closes [(t_open_ms, close)] per equity base; missing files are simply absent."""
    out: dict[str, list[tuple[int, float]]] = {}
    for b in set(bases):
        p = CANDLE_DIR / f"{b}.json"
        if p.exists():
            try:
                rows = json.loads(p.read_text(encoding="utf-8"))["rows"]
                out[b] = [(int(t), float(c)) for t, c in rows]
            except (OSError, ValueError, KeyError):
                continue
    return out


# ---------------------------------------------------------------- (1) chasing a prior move

class _Series:
    def __init__(self, rows: list[tuple[int, float]]):
        self.t = [r[0] for r in rows]
        self.c = np.array([r[1] for r in rows], dtype=float)
        self.idx = {t: i for i, t in enumerate(self.t)}
        w = CHASE_HOURS * HOUR_MS
        # N-hour log moves between candles exactly N hours apart (gaps in the cache are skipped, not bridged)
        moves = [math.log(self.c[i] / self.c[self.idx[t - w]]) for i, t in enumerate(self.t)
                 if (t - w) in self.idx and self.c[i] > 0 and self.c[self.idx[t - w]] > 0]
        self.moves = np.array(moves)
        self.sd = float(np.std(self.moves, ddof=1)) if len(self.moves) >= MIN_SIGMA_OBS else float("nan")

    def z(self, t_ms: int) -> float:
        """z of the N-hour move ending at the close of the last complete hourly candle before t_ms."""
        b = (t_ms // HOUR_MS) * HOUR_MS - HOUR_MS      # open time of the last complete candle
        a = b - CHASE_HOURS * HOUR_MS
        if a not in self.idx or b not in self.idx or not (self.sd > 0):
            return float("nan")
        return math.log(self.c[self.idx[b]] / self.c[self.idx[a]]) / self.sd

    def tail_share(self, direction: int) -> float:
        if not len(self.moves) or not (self.sd > 0):
            return float("nan")
        z = self.moves / self.sd
        return float(np.mean(z >= CHASE_SIGMA) if direction > 0 else np.mean(z <= -CHASE_SIGMA))


def chase_after_move(trips: list[RoundTrip], fills: list[Fill] | None = None,
                     candles: dict[str, list[tuple[int, float]]] | None = None, n_perm: int = 4000, seed: int = 0) -> Finding | None:
    """Entries on an equity perp made in the direction of a prior >= CHASE_SIGMA-sigma move over the previous CHASE_HOURS hours,
    versus the trader's other equity entries (mean net pnl per trip, within-trader permutation).

    Price source, labelled: 'candles' (public Bitget 1H closes, sigma from the symbol's own history) or 'own_fills'
    (the trader's own fill prices as the series: the reference is the latest earlier fill at least CHASE_HOURS before the
    entry and at most OWN_MAX_GAP_H beyond that; sigma pooled over the trader's own moves). Chance baseline: for candles,
    the share of all hours in which a move that large in that direction occurred; for own fills, half the share of
    entries with a move that large in either direction.
    """
    eq = [(i, equity_base(t.symbol)) for i, t in enumerate(trips)]
    eq = [(i, b) for i, b in eq if b]
    if not eq:
        return None
    candles = candles if candles is not None else load_candles(b for _, b in eq)
    series = {b: _Series(candles[b]) for _, b in eq if b in candles and len(candles[b]) > 2 * CHASE_HOURS}
    seg = trip_fills(fills) if fills else {}
    own_px: dict[str, tuple[list[int], list[float]]] = {}
    if fills:
        tmp: dict[str, list[Fill]] = defaultdict(list)
        for f in fills:
            tmp[f.symbol].append(f)
        for s, fs in tmp.items():
            fs.sort(key=lambda x: (x.t_ms, x.exec_id))
            own_px[s] = ([f.t_ms for f in fs], [f.price for f in fs])
    z_c: dict[int, float] = {}
    mv_own: dict[int, float] = {}
    for i, b in eq:
        t = trips[i]
        if b in series:
            z = series[b].z(t.t_open_ms)
            if z == z:
                z_c[i] = z
            continue
        fs = seg.get((t.symbol, t.t_open_ms, t.first_order_id))
        if not fs or t.symbol not in own_px or fs[0].price <= 0:
            continue
        ts, px = own_px[t.symbol]
        k = bisect_right(ts, t.t_open_ms - CHASE_HOURS * HOUR_MS) - 1
        if k >= 0 and (t.t_open_ms - CHASE_HOURS * HOUR_MS - ts[k]) <= OWN_MAX_GAP_H * HOUR_MS and px[k] > 0:
            mv_own[i] = math.log(fs[0].price / px[k])
    own_sd = float(np.std(list(mv_own.values()), ddof=1)) if len(mv_own) >= MIN_SIGMA_OBS else float("nan")
    z_all = dict(z_c)
    if own_sd > 0:
        z_all.update({i: m / own_sd for i, m in mv_own.items()})
    if not z_all:
        return None
    idx = sorted(z_all)
    sgn = np.array([1 if trips[i].side == "buy" else -1 for i in idx])
    aligned = sgn * np.array([z_all[i] for i in idx])
    lab = aligned >= CHASE_SIGMA
    pnl = np.array([trips[i].net_pnl for i in idx], dtype=float)
    shares = [series[equity_base(trips[i].symbol)].tail_share(int(s)) for i, s in zip(idx, sgn) if i in z_c]
    own_z = np.array([z_all[i] for i in idx if i not in z_c])
    n_own = len(own_z)
    if n_own:
        shares += [float(np.mean(np.abs(own_z) >= CHASE_SIGMA)) / 2] * n_own
    chance = float(np.nanmean(shares)) if shares else float("nan")
    source = "candles" if not n_own else ("own_fills" if not z_c else "candles+own_fills")
    extra = {"window_hours": CHASE_HOURS, "sigma": CHASE_SIGMA, "n_candle_entries": len(z_c), "n_own_fill_entries": n_own,
             "price_source": source, "chase_share": float(np.mean(lab)), "chance_share": chance}
    src = {"candles": "public Bitget 1H candles", "own_fills": "your own fill prices as the price series (no candles cached)",
           "candles+own_fills": "public Bitget 1H candles where cached, your own fill prices otherwise"}[source]
    return _gap_finding(
        "chase_after_move", pnl, lab,
        f"mean net pnl per trip of stock-perp entries made in the direction of a move of at least {CHASE_SIGMA:g} sigma over the previous "
        f"{CHASE_HOURS} hours, versus your other stock-perp entries (price source: {src}; "
        f"{extra['chase_share']:.0%} of your entries versus {chance:.0%} expected by chance; within-trader permutation test)",
        "chasing entries and other entries", n_perm, seed, extra)


# ---------------------------------------------------------------- (2) outside regular hours

def off_hours_trading(trips: list[RoundTrip], n_perm: int = 4000, seed: int = 0) -> Finding | None:
    """Stock-perp entries opened outside the US cash session (Mon-Fri 13:30-21:00 UTC) versus inside it."""
    idx = [i for i, t in enumerate(trips) if equity_base(t.symbol)]
    if not idx:
        return None
    lab = np.array([is_off_hours(trips[i].t_open_ms) for i in idx])
    pnl = np.array([trips[i].net_pnl for i in idx], dtype=float)
    extra = {"window_utc": "Mon-Fri 13:30-21:00", "off_share": float(np.mean(lab)), "baseline_off_share_of_hours": BASELINE_OFF_SHARE,
             "n_equity_trips": len(idx)}
    return _gap_finding(
        "off_hours_trading", pnl, lab,
        f"mean net pnl per trip of stock-perp entries opened outside the US cash session (Mon-Fri 13:30-21:00 UTC, so nights, "
        f"weekends and pre/after-market) versus entries inside it; {extra['off_share']:.0%} of your stock-perp entries are outside it, "
        f"{BASELINE_OFF_SHARE:.0%} of all hours are (within-trader permutation test)",
        "outside-hours entries and in-session entries", n_perm, seed, extra)


# ---------------------------------------------------------------- (3) averaging down

def avg_down_labels(fills: list[Fill], trips: list[RoundTrip]) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Per trip: did it add to the position at a price worse than its running average entry (a long adding lower, a short higher)?

    Returns (known, label, adds_total, adds_underwater). `known` is False when a trip's fills are not in `fills`.
    Only information at the moment of the add is used.
    """
    seg = trip_fills(fills)
    known = np.zeros(len(trips), dtype=bool)
    lab = np.zeros(len(trips), dtype=bool)
    adds = under = 0
    for i, t in enumerate(trips):
        fs = seg.get((t.symbol, t.t_open_ms, t.first_order_id))
        if not fs:
            continue
        known[i] = True
        d = 1 if fs[0].side == "buy" else -1
        q = avg = 0.0
        for k, f in enumerate(fs):
            if f.is_open and (f.side == "buy") == (d > 0):
                if k > 0 and q > 0:
                    adds += 1
                    if (f.price - avg) * d < 0:
                        under += 1
                        lab[i] = True
                avg = (avg * q + f.price * f.size) / (q + f.size) if q + f.size > 0 else f.price
                q += f.size
            else:
                q = max(q - f.size, 0.0)
    return known, lab, adds, under


def averaging_down(trips: list[RoundTrip], fills: list[Fill] | None, n_perm: int = 4000, seed: int = 0) -> Finding | None:
    """Trips that added to a position at a worse price than their running average entry, versus all other trips.

    Limitation, stated in the detail: a trip that goes against you early is the one that offers a lower add, so part of any
    gap is the path, not the choice; what is priced is what trips with this habit cost, not a counterfactual.
    """
    if not fills:
        return None
    known, lab, adds, under = avg_down_labels(fills, trips)
    if not known.any():
        return None
    # Fee handling: a trip that adds trades roughly twice the notional, so it pays roughly twice the fees by construction. Testing
    # net pnl would call that mechanical fee difference a habit cost. The test runs on pnl BEFORE fees (net + the trip's own fees);
    # the fee gap is reported separately in extra (fee_gap_per_trip), so it is not hidden.
    fees = trip_fees(fills, trips)
    fee_ok = np.where(np.isnan(fees), 0.0, fees)
    gross = np.array([t.net_pnl for t in trips], dtype=float) + fee_ok
    pnl = gross[known]
    lab = lab[known]
    fk = fee_ok[known]
    extra = {"fee_gap_per_trip": float(np.mean(fk[lab]) - np.mean(fk[~lab])) if lab.any() and (~lab).any() else float("nan"),
             "n_adds": adds, "adds_into_a_loss": under, "share_of_adds_into_a_loss": (under / adds) if adds else float("nan"),
             "share_of_trips": float(np.mean(lab)), "chance_share_of_adds_into_a_loss": 0.5}
    return _gap_finding(
        "averaging_down", pnl, lab,
        f"mean pnl per trip before fees of trips where you added to the position at a worse price than your average entry "
        f"({extra['share_of_trips']:.0%} of trips; {under} of {adds} adds were into a loss, against about half expected if add timing "
        f"were unrelated to being ahead or behind) versus all other trips; part of any gap is the path (a trip that goes against you "
        f"is the one that offers a lower add), so this prices the habit and does not prove the add caused the loss; fees are left out of the test "
        f"because an add trades more size and so pays more fee whatever the decision (the fee gap is reported separately) "
        f"(within-trader permutation test)", "averaging-down trips and other trips", n_perm, seed, extra)


def run_all(trips: list[RoundTrip], fills: list[Fill] | None = None, candles=None, n_perm: int = 4000, seed: int = 0) -> list[Finding]:
    """Applicable detectors only: the Holm family counts exactly these (plus the four in detectors/detectors2)."""
    out = [chase_after_move(trips, fills, candles, n_perm, seed), off_hours_trading(trips, n_perm, seed),
           averaging_down(trips, fills, n_perm, seed)]
    return [f for f in out if f is not None]
