"""Planted fixtures (SIM_PLANTED) for detectors3: chasing a prior move, off-hours trading, averaging down.

Each generator plants one known behaviour (or none, for the null control). Prices, candles and fills are synthetic.
These histories are never shown as a real person.
"""
from __future__ import annotations

import numpy as np

from . import ledger
from .detectors3 import CHASE_HOURS, CHASE_SIGMA, HOUR_MS, is_off_hours
from .schema import Fill, Provenance, RoundTrip

# a Monday 00:00 UTC (2026-01-05)
MON0 = 1_767_571_200_000
MIN_MS = 60_000


def _fill(e, oid, t, sym, side, is_open, px, sz, start, pnl=0.0, fee_rate=0.0005) -> Fill:
    return Fill(venue="planted", account="a", exec_id=f"e{e}", order_id=oid, t_ms=t, symbol=sym, side=side, is_open=is_open,
                price=px, size=sz, fee=px * sz * fee_rate, realized_pnl=pnl, start_position=start, provenance=Provenance.SIM_PLANTED)


def _trip_fills(e0, i, sym, t, side, px, notional, ret, hold_min, add_px=None):
    """Open (and optionally add once) then close at px*(1+ret) (sign-flipped for a short): returns fills, next exec index."""
    d = 1 if side == "buy" else -1
    close_side = "sell" if side == "buy" else "buy"
    sz = notional / px
    fs = [_fill(e0, f"o{i}", t, sym, side, True, px, sz, 0.0)]
    pos = sz
    avg = px
    e = e0 + 1
    if add_px is not None:
        fs.append(_fill(e, f"a{i}", t + 60_000, sym, side, True, add_px, sz, d * pos))
        avg = (px * pos + add_px * sz) / (pos + sz)
        pos += sz
        e += 1
    exit_px = avg * (1 + d * ret)
    fs.append(_fill(e, f"c{i}", t + hold_min * MIN_MS, sym, close_side, False, exit_px, pos, d * pos, (exit_px - avg) * d * pos))
    return fs, e + 1


def planted_candles(n_hours: int = 24 * 120, sd: float = 0.004, seed: int = 0, t0: int = MON0 - 24 * HOUR_MS) -> list[tuple[int, float]]:
    g = np.random.default_rng(seed)
    c = 100.0 * np.exp(np.cumsum(g.normal(0, sd, n_hours)))
    return [(t0 + k * HOUR_MS, float(x)) for k, x in enumerate(c)]


def planted_chase_trader(n: int = 300, p_chase: float = 0.5, tilt: float = 0.0, mu: float = 0.0, sigma: float = 0.01, base: float = 5000.0,
                         symbol: str = "NVDA", seed: int = 0):
    """Entries in the direction of a >= CHASE_SIGMA-sigma prior 4h move with probability p_chase (mean return shifted by tilt),
    otherwise at a random hour and side. Returns (trips, fills, candles) for the symbol; candles are the synthetic price path
    the entries are made against (entry prices are taken from it, so the own-fill source sees the same moves)."""
    g = np.random.default_rng(seed)
    candles = planted_candles(24 * 150, seed=seed + 7)
    c = np.array([x[1] for x in candles])
    w = CHASE_HOURS
    mv = np.log(c[w:] / c[:-w])
    sd = float(np.std(mv, ddof=1))
    hours_up = [k + w for k in range(len(mv)) if mv[k] / sd >= CHASE_SIGMA]       # candle index k+w: move ends at its close
    hours_dn = [k + w for k in range(len(mv)) if mv[k] / sd <= -CHASE_SIGMA]
    used: set[int] = set()
    fills: list[Fill] = []
    e = 0
    picks = []
    for i in range(n):
        chase = g.random() < p_chase
        for _ in range(50):
            if chase:
                up = g.random() < 0.5
                pool = hours_up if up else hours_dn
                k = int(pool[int(g.integers(0, len(pool)))]) + 1                    # enter in the hour after the move's last candle
                side = "buy" if up else "sell"
            else:
                k = int(g.integers(w + 2, len(c) - 2))
                side = "buy" if g.random() < 0.5 else "sell"
            if k not in used and k < len(c) - 1:
                used.add(k)
                break
        picks.append((k, side, chase))
    picks.sort()
    for i, (k, side, chase) in enumerate(picks):
        t = candles[k][0] + 5 * MIN_MS
        px = float(c[k - 1])                                                       # last close known at entry
        r = float(g.normal(mu + (tilt if chase else 0.0), sigma))
        fs, e = _trip_fills(e, i, symbol, t, side, px, base * float(np.exp(g.normal(0, 0.3))), r, int(g.integers(5, 40)))
        fills.extend(fs)
    return ledger.to_round_trips(fills), fills, {symbol: candles}


def planted_offhours_trader(n: int = 300, p_off: float = 0.4, tilt: float = 0.0, mu: float = 0.0, sigma: float = 0.01,
                            base: float = 5000.0, symbol: str = "TSLA", seed: int = 0) -> list[RoundTrip]:
    """Equity-perp trips; a fraction p_off opened outside the US cash session, with mean return shifted by tilt."""
    g = np.random.default_rng(seed)
    trips: list[RoundTrip] = []
    for i in range(n):
        for _ in range(500):
            t = MON0 + int(g.integers(0, 140 * 24 * 60)) * MIN_MS
            if is_off_hours(t) == (g.random() < p_off):
                break
        off = is_off_hours(t)
        notional = base * float(np.exp(g.normal(0, 0.3)))
        net = notional * float(g.normal(mu + (tilt if off else 0.0), sigma))
        trips.append(RoundTrip(symbol=symbol, t_open_ms=t, t_close_ms=t + int(g.integers(5, 60)) * MIN_MS, side="buy",
                               first_order_notional=notional, opened_notional=notional, net_pnl=net, first_order_id=f"p{i}",
                               provenance=Provenance.SIM_PLANTED))
    trips.sort(key=lambda x: x.t_open_ms)
    return trips


def planted_avgdown_trader(n: int = 250, p_avg: float = 0.35, tilt: float = 0.0, mu: float = 0.0, sigma: float = 0.01,
                           base: float = 5000.0, symbol: str = "PLANTED", seed: int = 0):
    """Each trip is a long; with probability p_avg it adds at a worse price (1-3 percent lower) with mean return shifted by tilt;
    with probability 0.25 it adds at a better price (a pyramid, not averaging down). Returns (trips, fills)."""
    g = np.random.default_rng(seed)
    fills: list[Fill] = []
    e = 0
    t = MON0
    for i in range(n):
        px = 100.0 * float(np.exp(g.normal(0, 0.05)))
        u = g.random()
        add = None
        shift = 0.0
        if u < p_avg:
            add, shift = px * (1 - float(g.uniform(0.01, 0.03))), tilt
        elif u < p_avg + 0.25:
            add = px * (1 + float(g.uniform(0.01, 0.03)))
        fs, e = _trip_fills(e, i, symbol, t, "buy", px, base * float(np.exp(g.normal(0, 0.3))), float(g.normal(mu + shift, sigma)),
                            int(g.integers(5, 120)), add)
        fills.extend(fs)
        t += int(g.integers(130, 600)) * MIN_MS
    return ledger.to_round_trips(fills), fills
