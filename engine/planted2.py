"""Planted fixtures (SIM_PLANTED) for detectors2, structural_gap, winrate. Used only to test the engine.

Each generator plants one known behaviour (or none, for the null control) so a
test can check the detector finds it and does not find it where it is absent.
These histories are never shown as a real person.
"""
from __future__ import annotations

import numpy as np

from .schema import Fill, Provenance, RoundTrip

T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)   # a UTC midnight
DAY_MS = 86_400_000
MIN_MS = 60_000


def _trip(i: int, sym: str, t_open: int, hold: int, notional: float, net: float) -> RoundTrip:
    return RoundTrip(symbol=sym, t_open_ms=t_open, t_close_ms=t_open + hold, side="buy",
                     first_order_notional=notional, opened_notional=notional, net_pnl=net,
                     first_order_id=f"p{i}", provenance=Provenance.SIM_PLANTED)


def planted_overtrader(n_days: int = 150, normal_rate: float = 3.0, heavy_frac: float = 0.12, heavy_rate: float = 14.0,
                       heavy_tilt: float = 0.0, mu: float = 0.0005, sigma: float = 0.01, base: float = 5000.0,
                       seed: int = 0) -> list[RoundTrip]:
    """Most days have ~normal_rate trips; a heavy_frac of days have ~heavy_rate trips.

    heavy_tilt shifts the mean return per unit notional on heavy days (negative = the planted leak).
    """
    g = np.random.default_rng(seed)
    trips: list[RoundTrip] = []
    i = 0
    for d in range(n_days):
        heavy = g.random() < heavy_frac
        k = 1 + int(g.poisson(heavy_rate if heavy else normal_rate))
        starts = np.sort(g.choice(np.arange(0, 22 * 60), size=k, replace=False))
        for s in starts:
            notional = base * float(np.exp(g.normal(0, 0.3)))
            r = float(g.normal(mu + (heavy_tilt if heavy else 0.0), sigma))
            trips.append(_trip(i, "PLANTED", T0 + d * DAY_MS + int(s) * MIN_MS, int(g.integers(1, 30)) * 1000,
                               notional, notional * r))
            i += 1
    trips.sort(key=lambda t: t.t_open_ms)
    return trips


def planted_revenge_trader(n: int = 700, p_revenge: float = 0.5, p_quick: float = 0.4, size_mult: float = 2.5,
                           tilt: float = 0.0, mu: float = 0.0, sigma: float = 0.01, base: float = 5000.0,
                           symbols: tuple[str, ...] = ("AAA", "BBB", "CCC"), seed: int = 0) -> list[RoundTrip]:
    """After a losing close, with probability p_revenge re-enter the same symbol within 1-14 minutes at
    size_mult times normal size, with mean return shifted by tilt. Otherwise, with probability p_quick,
    re-enter the same symbol quickly at normal size; else wait 30-600 minutes and pick any symbol.
    """
    g = np.random.default_rng(seed)
    trips: list[RoundTrip] = []
    t = T0
    sym = symbols[0]
    prev_loss = False
    for i in range(n):
        u = g.random()
        notional = base * float(np.exp(g.normal(0, 0.2)))
        mean = mu
        if prev_loss and u < p_revenge:
            t += int(g.integers(1, 15)) * MIN_MS
            notional *= size_mult
            mean += tilt
        elif g.random() < p_quick:
            t += int(g.integers(1, 15)) * MIN_MS
        else:
            t += int(g.integers(30, 600)) * MIN_MS
            sym = symbols[int(g.integers(0, len(symbols)))]
        hold = int(g.integers(2, 120)) * MIN_MS
        net = notional * float(g.normal(mean, sigma))
        trips.append(_trip(i, sym, t, hold, notional, net))
        t += hold
        prev_loss = net < 0
    return trips


def planted_fills(n: int = 200, fee_rate: float = 0.0006, mu: float = 0.001, sigma: float = 0.01,
                  base: float = 5000.0, symbol: str = "PLANTED", seed: int = 0) -> list[Fill]:
    """Open + (two partial) close fills per trip with exchange-style fields: fee positive = cost,
    realized_pnl gross of fee on the closing fills, start_position as the venue reports it."""
    g = np.random.default_rng(seed)
    fills: list[Fill] = []
    t = T0
    e = 0

    def add(oid, side, is_open, px, sz, start, pnl):
        nonlocal e
        fills.append(Fill(venue="planted", account="a", exec_id=f"e{e}", order_id=oid, t_ms=t, symbol=symbol,
                          side=side, is_open=is_open, price=px, size=sz, fee=px * sz * fee_rate, realized_pnl=pnl,
                          start_position=start, provenance=Provenance.SIM_PLANTED))
        e += 1

    for i in range(n):
        px = 100.0 * float(np.exp(g.normal(0, 0.05)))
        sz = base * float(np.exp(g.normal(0, 0.3))) / px
        add(f"o{i}", "buy", True, px, sz, 0.0, 0.0)
        t += int(g.integers(1, 60)) * MIN_MS
        exit_px = px * (1 + float(g.normal(mu, sigma)))
        half = sz / 2
        add(f"c{i}", "sell", False, exit_px, half, sz, (exit_px - px) * half)
        t += 1000
        add(f"c{i}", "sell", False, exit_px, sz - half, sz - half, (exit_px - px) * (sz - half))
        t += int(g.integers(5, 300)) * MIN_MS
    return fills


def planted_pnl_trips(net: list[float] | np.ndarray, base: float = 5000.0) -> list[RoundTrip]:
    """Wrap a given sequence of net pnl numbers as time-ordered trips (for win-rate arithmetic tests)."""
    return [_trip(i, "PLANTED", T0 + i * 3_600_000, 600_000, base, float(x)) for i, x in enumerate(net)]
