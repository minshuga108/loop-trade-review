"""Trade replay (R3): list round trips with the findings they belong to, and the fills of one trip.

Membership uses exactly the labels the detectors test, so "open the trades" behind a finding shows
the trades that finding was computed from:
  after_loss    detectors.after_loss_labels == 1      (size_after_loss)
  losing        net pnl < 0                           (hold_asymmetry: the losing group)
  busiest_day   detectors2.heavy_day_labels            (overtrading_clusters)
  reentry       detectors2.reentry_labels is_reentry   (revenge_reentry: the tested group is re-entries)
  revenge       ... and is_revenge                     (the labelled sub-group)
A price path is drawn only from candles stored offline (no network); without them the chart is
omitted and MAE/MFE are not computed. With candles they are labelled approximate, because a candle's
high and low are not known to fall inside the trip's exact window.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .detectors import after_loss_labels
from .detectors2 import heavy_day_labels, reentry_labels, trip_fills
from .schema import Fill, RoundTrip

FINDING_TAGS = {"size_after_loss": "after_loss", "hold_asymmetry": "losing", "overtrading_clusters": "busiest_day",
                "revenge_reentry": "reentry"}


def ordered(trips: list[RoundTrip]) -> list[RoundTrip]:
    return sorted(trips, key=lambda t: (t.t_open_ms, t.symbol, t.first_order_id))


def tags(trips: list[RoundTrip]) -> list[list[str]]:
    """Tags per trip, for trips already in `ordered` order."""
    lab = after_loss_labels(trips)
    heavy, _, _ = heavy_day_labels(trips)
    is_re, is_rv, _ = reentry_labels(trips)
    out = []
    for i, t in enumerate(trips):
        tg = []
        if lab[i] == 1:
            tg.append("after_loss")
        if t.net_pnl < 0:
            tg.append("losing")
        if len(heavy) and heavy[i]:
            tg.append("busiest_day")
        if is_re[i]:
            tg.append("reentry")
        if is_rv[i]:
            tg.append("revenge")
        out.append(tg)
    return out


def trip_rows(trips: list[RoundTrip]) -> list[dict]:
    ts = ordered(trips)
    tg = tags(ts)
    return [{"index": i, "symbol": t.symbol, "t_open_ms": t.t_open_ms, "t_close_ms": t.t_close_ms, "side": t.side,
             "first_order_notional": round(t.first_order_notional, 2), "net_pnl": round(t.net_pnl, 2),
             "hold_ms": t.hold_ms, "tags": tg[i], "provenance": t.provenance.value} for i, t in enumerate(ts)]


def candles_dir() -> Path:
    env = os.environ.get("LOOP_CANDLES_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "data" / "candles"


def load_candles(symbol: str) -> tuple[list[list[float]], str | None]:
    """Offline candles for a symbol: file <dir>/<symbol>.json = {"interval_ms": int, "rows": [[ts, o, h, l, c], ...]}."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in symbol)
    p = candles_dir() / f"{safe}.json"
    if not p.exists():
        return [], None
    d = json.loads(p.read_text(encoding="utf-8"))
    return sorted([[float(x) for x in r[:5]] for r in d.get("rows", [])], key=lambda r: r[0]), str(d.get("interval_ms"))


def trip_detail(trips: list[RoundTrip], fills: list[Fill], index: int) -> dict:
    ts = ordered(trips)
    if not 0 <= index < len(ts):
        raise IndexError("no trip with that index")
    t = ts[index]
    seg = trip_fills(fills).get((t.symbol, t.t_open_ms, t.first_order_id)) if fills else None
    fl = [{"t_ms": f.t_ms, "side": f.side, "is_open": f.is_open, "price": f.price, "size": f.size,
           "notional": round(f.price * f.size, 2), "fee": f.fee, "realized_pnl": f.realized_pnl} for f in (seg or [])]
    out = {"index": index, "trip": trip_rows(trips)[index], "fills": fl,
           "fills_note": None if seg else "This trader has no fill records (simulated round trips only), so there is nothing to replay fill by fill."}
    rows, interval = load_candles(t.symbol)
    inside = [r for r in rows if t.t_open_ms - (int(interval or 0)) < r[0] <= t.t_close_ms]
    if not inside:
        out["candles"] = None
        out["candles_note"] = (f"No candles for {t.symbol} are stored offline, so no price path is drawn and MAE/MFE are not computed. "
                               "Nothing is fetched or guessed.")
        return out
    long = t.side == "buy"
    entry = fl[0]["price"] if fl else None
    hi, lo = max(r[2] for r in inside), min(r[3] for r in inside)
    mae = mfe = None
    if entry:
        mfe = (hi - entry) / entry if long else (entry - lo) / entry
        mae = (entry - lo) / entry if long else (hi - entry) / entry
    out["candles"] = {"interval_ms": int(interval or 0), "rows": inside}
    out["mae_frac"], out["mfe_frac"] = mae, mfe
    out["candles_note"] = (f"MAE and MFE are approximate: from {int(interval or 0) // 60000}-minute candle highs and lows, which may "
                           "include prices just outside the trip's window.")
    return out
