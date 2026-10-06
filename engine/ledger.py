"""Fills to orders to round trips.

Round trips are flat-to-flat per symbol. A trip that starts while a position
is already open (history window cut) is skipped, never guessed.
"""
from __future__ import annotations

from collections import defaultdict

from .schema import Fill, Order, Provenance, RoundTrip

EPS = 1e-9


def dedupe(fills: list[Fill]) -> list[Fill]:
    seen: set[tuple[str, str]] = set()
    out = []
    for f in sorted(fills, key=lambda x: (x.t_ms, x.exec_id)):
        key = (f.account, f.exec_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def to_orders(fills: list[Fill]) -> list[Order]:
    groups: dict[tuple[str, str, bool], list[Fill]] = defaultdict(list)
    for f in fills:
        groups[(f.order_id, f.symbol, f.is_open)].append(f)
    orders = []
    for (oid, sym, is_open), fs in groups.items():
        fs.sort(key=lambda x: x.t_ms)
        orders.append(
            Order(
                order_id=oid,
                symbol=sym,
                t_first_ms=fs[0].t_ms,
                t_last_ms=fs[-1].t_ms,
                side=fs[0].side,
                is_open=is_open,
                notional=sum(x.price * x.size for x in fs),
                fee=sum(x.fee for x in fs),
                realized_pnl=sum(x.realized_pnl for x in fs),
                provenance=fs[0].provenance,
            )
        )
    orders.sort(key=lambda o: (o.t_last_ms, o.order_id))
    return orders


def to_round_trips(fills: list[Fill]) -> list[RoundTrip]:
    """Flat-to-flat trips per symbol, using the venue's start_position."""
    by_sym: dict[str, list[Fill]] = defaultdict(list)
    for f in fills:
        by_sym[f.symbol].append(f)
    trips: list[RoundTrip] = []
    for sym, fs in by_sym.items():
        fs.sort(key=lambda x: (x.t_ms, x.exec_id))
        cur: list[Fill] | None = None
        for f in fs:
            signed = f.size if f.side == "buy" else -f.size
            after = f.start_position + signed
            if cur is None:
                if abs(f.start_position) < EPS and f.is_open:
                    cur = [f]
                else:
                    continue  # mid-position start: skipped, never guessed
            else:
                cur.append(f)
            if abs(after) < EPS:
                trips.append(_close(sym, cur))
                cur = None
        # an unfinished trip at the end of the window is ignored
    trips.sort(key=lambda t: t.t_open_ms)
    return trips


def _close(sym: str, cur: list[Fill]) -> RoundTrip:
    first_oid = cur[0].order_id
    first_notional = sum(x.price * x.size for x in cur if x.order_id == first_oid and x.is_open)
    opened = sum(x.price * x.size for x in cur if x.is_open)
    net = sum(x.realized_pnl for x in cur) - sum(x.fee for x in cur)
    return RoundTrip(
        symbol=sym,
        t_open_ms=cur[0].t_ms,
        t_close_ms=cur[-1].t_ms,
        side=cur[0].side,
        first_order_notional=first_notional,
        opened_notional=opened,
        net_pnl=net,
        first_order_id=first_oid,
        provenance=cur[0].provenance,
    )
