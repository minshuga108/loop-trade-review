"""Rule Gate extras: scenario chips and 'similar past trades'. Labelled facts from the trader's own round trips only:
no forecast, no score. A scenario tag is stored with the logged check; it never changes the verdict by itself."""
from __future__ import annotations

from engine import detectors3, replay

SCENARIOS = {
    "after_loss": {"en": "after a loss", "zh": "亏损之后", "fill_en": "after a loss", "fill_zh": "亏损之后"},
    "bigger": {"en": "bigger than usual", "zh": "比平时更大", "fill_en": "bigger than usual", "fill_zh": "比平时更大"},
    "closed_market": {"en": "in a closed market", "zh": "休市时", "fill_en": "in a closed market", "fill_zh": "休市时"},
    "high_funding": {"en": "at high funding", "zh": "资金费率偏高时", "fill_en": "at high funding", "fill_zh": "资金费率偏高时"},
}
BAND = (0.5, 2.0)       # a 'similar size' trade opened between half and double the idea's notional


def clean_scenarios(raw) -> list[str]:
    return [k for k in (raw or []) if k in SCENARIOS][:4] if isinstance(raw, (list, tuple)) else []


def similar_trades(trips, idea: dict, after_loss: bool, scenario: list[str], median_notional: float, limit: int = 8) -> dict:
    """Past round trips with the same symbol and side, in the same size band; after-loss ones only when the idea is after a loss."""
    ts = replay.ordered(trips)
    tg = replay.tags(ts)
    sym, side, size = idea.get("symbol"), idea.get("side"), idea.get("notional")
    if "bigger" in scenario and median_notional:
        lo, hi = 1.5 * median_notional, float("inf")
        band = {"kind": "above_1.5x_median", "lo": lo, "hi": None}
    elif size:
        lo, hi = size * BAND[0], size * BAND[1]
        band = {"kind": "idea_size_0.5x_to_2x", "lo": lo, "hi": hi}
    else:
        lo, hi, band = 0.0, float("inf"), {"kind": "any_size", "lo": 0, "hi": None}
    closed = "closed_market" in scenario
    notes = []
    if closed:
        notes.append({"en": "In a closed market: only your past trades opened outside the US cash session (Mon-Fri 13:30-21:00 UTC) are listed.",
                      "zh": "休市时：只列出你在美股常规交易时段（周一至周五 13:30-21:00 UTC）之外开仓的过往交易。"})
    if "high_funding" in scenario:
        notes.append({"en": "At high funding: your record has no funding rate per trade, so past trades cannot be filtered by it. The live funding line above is context only.",
                      "zh": "资金费率偏高时：你的记录里没有每笔交易的资金费率，所以无法按它筛选过往交易。上方的实时资金费行只是背景信息。"})
    rows = []
    for i, t in enumerate(ts):
        if sym and t.symbol != sym:
            continue
        if side and t.side != side:
            continue
        if not lo <= t.first_order_notional <= hi:
            continue
        if after_loss and "after_loss" not in tg[i]:
            continue
        if closed and not detectors3.is_off_hours(t.t_open_ms):
            continue
        rows.append({"index": i, "symbol": t.symbol, "side": t.side, "t_open_ms": t.t_open_ms, "hold_ms": t.hold_ms,
                     "notional": round(t.first_order_notional, 2), "net_pnl": round(t.net_pnl, 2), "after_loss": "after_loss" in tg[i]})
    rows.sort(key=lambda r: -r["t_open_ms"])
    total = round(sum(r["net_pnl"] for r in rows), 2)
    return {"filters": {"symbol": sym, "side": side, "size_band": band, "after_loss": bool(after_loss), "closed_market": closed}, "notes": notes, "n": len(rows),
            "net_total": total if rows else None, "wins": sum(1 for r in rows if r["net_pnl"] > 0), "rows": rows[:limit],
            "label": "Facts from your own past round trips that match; not a forecast and not a recommendation."}
