"""Planted-leak and planted-rule fixtures (SIM_PLANTED). Used only to test the engine.

A trader who sizes up by `size_mult` after a loss and, optionally, makes worse
decisions after a loss (`tilt`, a lower mean return per unit of notional).
These histories are never shown as a real person.
"""
from __future__ import annotations

import numpy as np

from .schema import Provenance, RoundTrip


def planted_trader(n: int = 300, size_mult: float = 1.0, tilt: float = 0.0, mu: float = 0.0005,
                   sigma: float = 0.02, base: float = 5000.0, fee_rate: float = 0.0005, seed: int = 0) -> list[RoundTrip]:
    g = np.random.default_rng(seed)
    trips: list[RoundTrip] = []
    t = 1_700_000_000_000
    prev_loss = False
    for i in range(n):
        notional = base * float(np.exp(g.normal(0, 0.4))) * (size_mult if prev_loss else 1.0)
        mean = mu + (tilt if prev_loss else 0.0)
        r = float(g.normal(mean, sigma))
        fee = notional * fee_rate * 2
        net = notional * r - fee
        hold = int(g.integers(5, 240)) * 60_000
        trips.append(RoundTrip(symbol="PLANTED", t_open_ms=t, t_close_ms=t + hold, side="buy",
                               first_order_notional=notional, opened_notional=notional, net_pnl=net,
                               first_order_id=f"p{i}", provenance=Provenance.SIM_PLANTED))
        t += hold + int(g.integers(5, 600)) * 60_000
        prev_loss = net < 0
    return trips
