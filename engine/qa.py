"""Typed QUERY layer over a trader's own record: QueryPlan -> executor -> number-locked answer.

Three parts, all deterministic:
  1. QueryPlan: a closed pydantic schema {metric, group_by, filters, compare, period, top_n,
     exclude_best}. Anything outside it is rejected, whoever wrote it (parser or LLM).
  2. execute(plan, trips, fills): every metric computed from the trader's round trips and
     fills; a typed QAResult with value(s), n, a bootstrap interval where that makes sense,
     and honest caveats (small n, data the record cannot give).
  3. parse(text, previous_plan): a deterministic EN / ZH (simplified + traditional) /
     Hinglish / typo-tolerant parser to a QueryPlan, with follow-ups that modify the previous
     plan, an "unsupported but explain" path and a clarifying question on ambiguity.
  4. render(result, lang): one-sentence headline, one small typed card, "how this was
     computed", 3 next chips; every numeral checked by engine.numberlock.

Nothing here places orders or reads the market. Times are UTC. Weekday/hour/day groupings
and period filters use the trip's OPEN time; the drawdown curve uses CLOSE order (realised).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .detectors import after_loss_labels
from .detectors2 import trip_fees
from .numberlock import NumberLockError, verify
from .schema import Fill, RoundTrip

# ---------------------------------------------------------------- closed schema
METRICS = ("trade_count", "wins", "losses", "win_rate", "net_pnl", "avg_pnl", "avg_win", "avg_loss",
           "median_size", "avg_hold", "median_hold", "best_trade", "worst_trade", "total_fees", "fee_share",
           "profit_factor", "expectancy", "max_drawdown", "win_streak", "loss_streak", "trades_per_day",
           "busiest_day", "best_day", "worst_day", "active_days", "time_since_last")
GROUP_BYS = ("weekday", "hour", "symbol", "side", "after_loss", "outcome")
PERIODS = ("all", "last_7d", "last_30d", "last_90d", "first_third", "last_third", "first_half", "second_half", "last_n")
COMPARES = ("none", "first_vs_last_third")
Metric = Literal[METRICS]
GroupBy = Literal[GROUP_BYS]
PeriodKind = Literal[PERIODS]
Compare = Literal[COMPARES]

SMALL_N = 30            # below this every answer carries a small-sample caveat
N_BOOT = 1000           # seeded bootstrap for intervals
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
# metrics with no per-trade bootstrap: counts, extremes, streaks, totals
NO_INTERVAL = {"trade_count", "wins", "losses", "best_trade", "worst_trade", "total_fees", "max_drawdown", "win_streak",
               "loss_streak", "busiest_day", "best_day", "worst_day", "active_days", "time_since_last", "net_pnl"}
UNITS = {"trade_count": "count", "wins": "count", "losses": "count", "win_rate": "pct", "net_pnl": "money", "avg_pnl": "money",
         "avg_win": "money", "avg_loss": "money", "median_size": "money", "avg_hold": "hours", "median_hold": "hours",
         "best_trade": "money", "worst_trade": "money", "total_fees": "money", "fee_share": "pct", "profit_factor": "ratio",
         "expectancy": "money", "max_drawdown": "money", "win_streak": "count", "loss_streak": "count", "trades_per_day": "ratio",
         "busiest_day": "count", "best_day": "money", "worst_day": "money", "active_days": "count", "time_since_last": "days"}


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: Optional[str] = None
    side: Optional[Literal["buy", "sell"]] = None
    weekdays: Optional[list[int]] = None          # 0 = Monday ... 6 = Sunday, UTC
    outcome: Optional[Literal["win", "loss"]] = None
    after_loss: Optional[bool] = None

    @field_validator("weekdays")
    @classmethod
    def _wd(cls, v):
        if v is not None:
            v = sorted(set(v))
            if not v or any(not 0 <= d <= 6 for d in v):
                raise ValueError("weekdays must be 0..6")
        return v

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v):
        if v is not None:
            v = v.strip().upper()
            if not re.fullmatch(r"[A-Z0-9:._-]{1,20}", v):
                raise ValueError("symbol must be a short ticker")
        return v

    def compact(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: PeriodKind = "all"
    n: Optional[int] = Field(default=None, ge=1, le=100_000)

    @field_validator("n")
    @classmethod
    def _n(cls, v, info):
        return v

    def compact(self) -> dict:
        d = {"kind": self.kind}
        if self.kind == "last_n":
            d["n"] = self.n or 20
        return d


class QueryPlan(BaseModel):
    """The only thing a planner (deterministic or LLM) may produce. Closed: unknown keys fail."""
    model_config = ConfigDict(extra="forbid")
    metric: Metric
    group_by: Optional[GroupBy] = None
    filters: Filters = Field(default_factory=Filters)
    compare: Compare = "none"
    period: Period = Field(default_factory=Period)
    top_n: Optional[int] = Field(default=None, ge=1, le=20)
    exclude_best: bool = False

    def compact(self) -> dict:
        """Canonical dict with defaults dropped; used by the eval and the follow-up state."""
        d: dict = {"metric": self.metric}
        if self.group_by:
            d["group_by"] = self.group_by
        f = self.filters.compact()
        if f:
            d["filters"] = f
        if self.compare != "none":
            d["compare"] = self.compare
        if self.period.kind != "all":
            d["period"] = self.period.compact()
        if self.top_n:
            d["top_n"] = self.top_n
        if self.exclude_best:
            d["exclude_best"] = True
        return d


def validate_plan(obj) -> QueryPlan | None:
    """Strict validation of an untrusted plan (e.g. LLM output). None on any violation."""
    if not isinstance(obj, dict):
        return None
    try:
        return QueryPlan.model_validate(obj)
    except ValidationError:
        return None


# ---------------------------------------------------------------- result types
class GroupRow(BaseModel):
    label: str
    key: str
    value: float
    n: int


class QAResult(BaseModel):
    plan: QueryPlan
    value: Optional[float] = None
    unit: str
    n: int                                    # trips the headline number rests on
    n_total: int                              # trips in the whole record
    interval: Optional[tuple[float, float]] = None
    groups: Optional[list[GroupRow]] = None
    rows: Optional[list[dict]] = None         # top-n trade rows
    compare: Optional[dict] = None            # {"first": .., "last": .., "n_first":.., "n_last":..}
    detail: dict = Field(default_factory=dict)
    window: dict = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    facts: dict[str, float] = Field(default_factory=dict)
    available: bool = True                    # False when the record cannot give the metric


# ---------------------------------------------------------------- selection
def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _weekday(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).weekday()


def _hour(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).hour


def symbol_matches(trip_symbol: str, wanted: str) -> bool:
    s, w = trip_symbol.upper(), wanted.upper()
    core = s.split(":")[-1]
    return s == w or core == w or core.startswith(w) and core[len(w):] in ("USDT", "USD", "USDC", "PERP", "-PERP")


def apply_period(trips: list[RoundTrip], period: Period) -> tuple[list[RoundTrip], dict]:
    """Period relative to the record's own last trade (the demo records are historical). Open time."""
    ts = sorted(trips, key=lambda t: (t.t_open_ms, t.t_close_ms))
    if not ts:
        return [], {"kind": period.kind, "label": "no trades"}
    last = max(t.t_close_ms for t in ts)
    k = period.kind
    if k == "all":
        return ts, {"kind": k, "from": _day(ts[0].t_open_ms), "to": _day(last)}
    if k in ("last_7d", "last_30d", "last_90d"):
        days = int(k.split("_")[1][:-1])
        lo = last - days * DAY_MS
        out = [t for t in ts if t.t_open_ms >= lo]
        return out, {"kind": k, "from": _day(lo), "to": _day(last), "anchored_to_last_trade": True}
    if k == "last_n":
        n = period.n or 20
        out = ts[-n:]
        return out, {"kind": k, "n": n, "from": _day(out[0].t_open_ms) if out else None, "to": _day(last)}
    n = len(ts)
    a, b = n // 3, n - n // 3
    h = n // 2
    cut = {"first_third": (0, a), "last_third": (b, n), "first_half": (0, h), "second_half": (h, n)}[k]
    out = ts[cut[0]:cut[1]]
    return out, {"kind": k, "from": _day(out[0].t_open_ms) if out else None, "to": _day(out[-1].t_close_ms) if out else None}


def apply_filters(trips: list[RoundTrip], f: Filters, labels: dict[int, int]) -> list[RoundTrip]:
    out = []
    for t in trips:
        if f.symbol and not symbol_matches(t.symbol, f.symbol):
            continue
        if f.side and t.side != f.side:
            continue
        if f.weekdays and _weekday(t.t_open_ms) not in f.weekdays:
            continue
        if f.outcome == "win" and not t.net_pnl > 0:
            continue
        if f.outcome == "loss" and not t.net_pnl < 0:
            continue
        if f.after_loss is not None:
            lab = labels.get(id(t), -1)
            if lab < 0 or (lab == 1) != f.after_loss:
                continue
        out.append(t)
    return out


def _labels(trips: list[RoundTrip]) -> dict[int, int]:
    """after-a-loss label per trip object (computed on the WHOLE record, before any filter)."""
    if not trips:
        return {}
    lab = after_loss_labels(trips)
    return {id(t): int(l) for t, l in zip(trips, lab)}


# ---------------------------------------------------------------- metric kernels
def _boot(values: np.ndarray, stat, seed: int = 0) -> tuple[float, float] | None:
    n = len(values)
    if n < 8:
        return None
    g = np.random.default_rng(seed)
    out = np.empty(N_BOOT)
    for i in range(N_BOOT):
        out[i] = stat(values[g.integers(0, n, n)])
    out = out[~np.isnan(out)]
    if len(out) == 0:
        return None
    return (float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975)))


def _win_rate(p: np.ndarray) -> float:
    d = int(np.sum(p > 0)) + int(np.sum(p < 0))
    return float(np.sum(p > 0) / d) if d else float("nan")


def _profit_factor(p: np.ndarray) -> float:
    gp, gl = float(np.sum(p[p > 0])), float(-np.sum(p[p < 0]))
    return gp / gl if gl > 0 else float("nan")


def _drawdown(trips: list[RoundTrip]) -> tuple[float, dict]:
    ts = sorted(trips, key=lambda t: t.t_close_ms)
    cum = peak = 0.0
    dd = 0.0
    peak_i = trough_i = None
    for t in ts:
        cum += t.net_pnl
        if cum > peak:
            peak, peak_i = cum, t
        if peak - cum > dd:
            dd, trough_i = peak - cum, t
    return dd, {"peak_day": _day(peak_i.t_close_ms) if peak_i else None, "trough_day": _day(trough_i.t_close_ms) if trough_i else None}


def _streak(trips: list[RoundTrip], win: bool) -> int:
    best = cur = 0
    for t in sorted(trips, key=lambda t: t.t_close_ms):
        hit = t.net_pnl > 0 if win else t.net_pnl < 0
        cur = cur + 1 if hit else 0
        best = max(best, cur)
    return best


def _by_day(trips: list[RoundTrip]) -> dict[str, list[RoundTrip]]:
    d: dict[str, list[RoundTrip]] = {}
    for t in trips:
        d.setdefault(_day(t.t_open_ms), []).append(t)
    return d


def _scalar(metric: str, trips: list[RoundTrip], fees: np.ndarray | None, now_ms: int | None) -> tuple[float | None, dict, tuple | None, bool]:
    """(value, detail, interval, available) for one metric on an already selected trip list."""
    p = np.array([t.net_pnl for t in trips], dtype=float)
    n = len(trips)
    det: dict = {}
    if metric == "trade_count":
        return float(n), det, None, True
    if metric == "active_days":
        return float(len(_by_day(trips))), det, None, True
    if n == 0:
        return None, det, None, True
    if metric == "wins":
        return float(np.sum(p > 0)), det, None, True
    if metric == "losses":
        return float(np.sum(p < 0)), det, None, True
    if metric == "win_rate":
        det = {"wins": int(np.sum(p > 0)), "losses": int(np.sum(p < 0))}
        return _win_rate(p), det, _boot(p, _win_rate), True
    if metric == "net_pnl":
        return float(np.sum(p)), det, None, True
    if metric in ("avg_pnl", "expectancy"):
        w, l = p[p > 0], p[p < 0]
        det = {"avg_win": float(np.mean(w)) if len(w) else None, "avg_loss": float(-np.mean(l)) if len(l) else None,
               "win_rate": _win_rate(p)}
        return float(np.mean(p)), det, _boot(p, np.mean), True
    if metric == "avg_win":
        w = p[p > 0]
        return (float(np.mean(w)) if len(w) else None), {"n_wins": int(len(w))}, _boot(w, np.mean), True
    if metric == "avg_loss":
        l = -p[p < 0]
        return (float(np.mean(l)) if len(l) else None), {"n_losses": int(len(l))}, _boot(l, np.mean), True
    if metric == "median_size":
        s = np.array([t.first_order_notional for t in trips], dtype=float)
        return float(np.median(s)), det, _boot(s, np.median), True
    if metric in ("avg_hold", "median_hold"):
        h = np.array([t.hold_ms for t in trips], dtype=float) / HOUR_MS
        fn = np.mean if metric == "avg_hold" else np.median
        return float(fn(h)), det, _boot(h, fn), True
    if metric == "best_trade":
        t = max(trips, key=lambda t: t.net_pnl)
        return t.net_pnl, {"symbol": t.symbol, "day": _day(t.t_open_ms), "side": t.side, "size": t.first_order_notional}, None, True
    if metric == "worst_trade":
        t = min(trips, key=lambda t: t.net_pnl)
        return t.net_pnl, {"symbol": t.symbol, "day": _day(t.t_open_ms), "side": t.side, "size": t.first_order_notional}, None, True
    if metric in ("total_fees", "fee_share"):
        if fees is None or np.all(np.isnan(fees)):
            return None, {"reason": "no fee data"}, None, False
        known = ~np.isnan(fees)
        f = fees[known]
        det = {"trips_with_fee_data": int(known.sum()), "trips_without": int((~known).sum())}
        if metric == "total_fees":
            return float(np.sum(f)), det, None, True
        gross = p[known] + f
        gp = float(np.sum(gross[gross > 0]))
        det["gross_profit"] = gp
        det["total_fees"] = float(np.sum(f))
        if gp <= 0:
            return None, {**det, "reason": "no gross profit"}, None, False

        def share(idx):
            g = gross[idx]
            s = float(np.sum(g[g > 0]))
            return float(np.sum(f[idx]) / s) if s > 0 else float("nan")
        return float(np.sum(f) / gp), det, _boot(np.arange(len(f)), share), True
    if metric == "profit_factor":
        det = {"gross_profit": float(np.sum(p[p > 0])), "gross_loss": float(-np.sum(p[p < 0]))}
        v = _profit_factor(p)
        return (None if math.isnan(v) else v), det, _boot(p, _profit_factor), not math.isnan(v)
    if metric == "max_drawdown":
        dd, det = _drawdown(trips)
        return dd, det, None, True
    if metric == "win_streak":
        return float(_streak(trips, True)), det, None, True
    if metric == "loss_streak":
        return float(_streak(trips, False)), det, None, True
    if metric == "trades_per_day":
        days = _by_day(trips)
        c = np.array([len(v) for v in days.values()], dtype=float)
        return float(np.mean(c)), {"active_days": len(days), "median_per_day": float(np.median(c))}, _boot(c, np.mean), True
    if metric in ("busiest_day", "best_day", "worst_day"):
        days = _by_day(trips)
        if metric == "busiest_day":
            k, v = max(days.items(), key=lambda kv: (len(kv[1]), kv[0]))
            return float(len(v)), {"day": k, "pnl_that_day": float(sum(t.net_pnl for t in v)), "active_days": len(days)}, None, True
        sums = {k: float(sum(t.net_pnl for t in v)) for k, v in days.items()}
        k = (max if metric == "best_day" else min)(sums, key=lambda k: (sums[k], k))
        return sums[k], {"day": k, "trades_that_day": len(days[k]), "active_days": len(days)}, None, True
    if metric == "time_since_last":
        last = max(t.t_close_ms for t in trips)
        now = now_ms if now_ms is not None else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        return (now - last) / DAY_MS, {"last_day": _day(last), "last_symbol": max(trips, key=lambda t: t.t_close_ms).symbol}, None, True
    raise ValueError(metric)


# ---------------------------------------------------------------- executor
GROUP_LABEL_EN = {"weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "side": {"buy": "longs", "sell": "shorts"},
                  "after_loss": {"1": "after a loss", "0": "after a win"}, "outcome": {"win": "winners", "loss": "losers"}}
GROUP_LABEL_ZH = {"weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"], "side": {"buy": "多单", "sell": "空单"},
                  "after_loss": {"1": "亏损后", "0": "盈利后"}, "outcome": {"win": "盈利单", "loss": "亏损单"}}


def _group_key(t: RoundTrip, g: str, labels: dict[int, int]) -> str | None:
    if g == "weekday":
        return str(_weekday(t.t_open_ms))
    if g == "hour":
        return f"{_hour(t.t_open_ms):02d}"
    if g == "symbol":
        return t.symbol
    if g == "side":
        return t.side
    if g == "outcome":
        return "win" if t.net_pnl > 0 else ("loss" if t.net_pnl < 0 else None)
    if g == "after_loss":
        lab = labels.get(id(t), -1)
        return None if lab < 0 else str(lab)
    raise ValueError(g)


def group_label(g: str, key: str, lang: str = "en") -> str:
    tab = GROUP_LABEL_ZH if lang == "zh" else GROUP_LABEL_EN
    if g == "weekday":
        return tab["weekday"][int(key)]
    if g == "hour":
        return f"{key}:00 UTC"
    if g in tab:
        return tab[g].get(key, key)
    return key


def execute(plan: QueryPlan, trips: list[RoundTrip], fills: list[Fill] | None = None, now_ms: int | None = None) -> QAResult:
    """Run a validated plan. Every number in the result is computed here from trips/fills."""
    n_total = len(trips)
    labels = _labels(trips)
    fee_by_id: dict[int, float] = {}
    has_fees = bool(fills)
    if has_fees:
        fv = trip_fees(fills, trips)
        fee_by_id = {id(t): float(f) for t, f in zip(trips, fv)}
    caveats: list[str] = []
    sel, window = apply_period(trips, plan.period)
    sel = apply_filters(sel, plan.filters, labels)
    excluded = None
    if plan.exclude_best and sel:
        best = max(sel, key=lambda t: t.net_pnl)
        excluded = {"symbol": best.symbol, "day": _day(best.t_open_ms), "net_pnl": best.net_pnl}
        sel = [t for t in sel if t is not best]

    def fees_of(ts):
        if not has_fees:
            return None
        return np.array([fee_by_id.get(id(t), np.nan) for t in ts], dtype=float)

    facts: dict[str, float] = {}
    res = QAResult(plan=plan, unit=UNITS[plan.metric], n=len(sel), n_total=n_total, window=window)
    if plan.filters.symbol and not sel and n_total:
        syms = sorted({t.symbol for t in trips})
        res.detail["symbols_traded"] = syms[:8]
        caveats.append("no_symbol_match")
    if plan.compare == "first_vs_last_third":
        ts = sorted(sel, key=lambda t: t.t_open_ms)
        n = len(ts)
        first, last = ts[: n // 3], ts[n - n // 3:]
        v1, d1, i1, a1 = _scalar(plan.metric, first, fees_of(first), now_ms)
        v2, d2, i2, a2 = _scalar(plan.metric, last, fees_of(last), now_ms)
        res.available = a1 and a2
        res.compare = {"first": v1, "last": v2, "n_first": len(first), "n_last": len(last),
                       "first_from": _day(first[0].t_open_ms) if first else None, "last_from": _day(last[0].t_open_ms) if last else None,
                       "interval_first": i1, "interval_last": i2}
        if v1 is not None and v2 is not None:
            res.value = v2 - v1
            facts["delta"] = v2 - v1
            facts["first"], facts["last"] = v1, v2
        if n < 3 * 10:
            caveats.append("thirds_small")
    elif plan.group_by:
        buckets: dict[str, list[RoundTrip]] = {}
        dropped = 0
        for t in sel:
            k = _group_key(t, plan.group_by, labels)
            if k is None:
                dropped += 1
                continue
            buckets.setdefault(k, []).append(t)
        rows = []
        for k, ts in buckets.items():
            v, d, _, ok = _scalar(plan.metric, ts, fees_of(ts), now_ms)
            if v is None or not ok:
                continue
            rows.append(GroupRow(label=group_label(plan.group_by, k, "en"), key=k, value=v, n=len(ts)))
        if plan.group_by in ("weekday", "hour"):
            rows.sort(key=lambda r: r.key)
        else:
            rows.sort(key=lambda r: -r.value if UNITS[plan.metric] != "count" else -r.n)
        if plan.top_n and plan.group_by not in ("weekday", "hour"):
            rows = rows[: plan.top_n]
        res.groups = rows
        res.detail["dropped_unlabelled"] = dropped
        if dropped:
            caveats.append("after_loss_first_trade_dropped" if plan.group_by == "after_loss" else "zero_pnl_dropped")
        res.available = bool(rows)
        if rows:
            top = max(rows, key=lambda r: r.value)
            bottom = min(rows, key=lambda r: r.value)
            res.value = top.value
            res.detail["top"] = {"label": top.label, "key": top.key, "value": top.value, "n": top.n}
            res.detail["bottom"] = {"label": bottom.label, "key": bottom.key, "value": bottom.value, "n": bottom.n}
            for r in rows:
                facts[f"g.{r.key}"] = r.value
                facts[f"g.{r.key}.n"] = r.n
            if any(r.n < 10 for r in rows):
                caveats.append("thin_groups")
    else:
        v, det, iv, ok = _scalar(plan.metric, sel, fees_of(sel), now_ms)
        res.value, res.detail, res.interval, res.available = v, {**res.detail, **det}, (None if plan.metric in NO_INTERVAL else iv), ok
        if plan.top_n and plan.metric in ("best_trade", "worst_trade") and sel:
            order = sorted(sel, key=lambda t: t.net_pnl, reverse=plan.metric == "best_trade")[: plan.top_n]
            res.rows = [{"day": _day(t.t_open_ms), "symbol": t.symbol, "side": t.side, "size": t.first_order_notional, "net_pnl": t.net_pnl} for t in order]
            for i, r in enumerate(res.rows):
                facts[f"row{i}.pnl"], facts[f"row{i}.size"] = r["net_pnl"], r["size"]
        if v is not None:
            facts["value"] = v
        if iv and plan.metric not in NO_INTERVAL:
            facts["lo"], facts["hi"] = iv
        for k, x in det.items():
            if isinstance(x, (int, float)) and not isinstance(x, bool) and x is not None and not (isinstance(x, float) and math.isnan(x)):
                facts[f"d.{k}"] = float(x)
    if excluded:
        res.detail["excluded_best"] = excluded
        facts["excluded.pnl"] = excluded["net_pnl"]
    if plan.metric in ("total_fees", "fee_share") and not has_fees:
        caveats.append("no_fee_data")
    if plan.metric == "time_since_last":
        caveats.append("record_end")
    if 0 < res.n < SMALL_N:
        caveats.append("small_n")
    if res.n == 0:
        caveats.append("empty")
    if plan.exclude_best and res.n == 0 and excluded:
        caveats.append("only_one_trade")
    facts["n"] = res.n
    facts["n_total"] = n_total
    res.facts = {k: float(v) for k, v in facts.items() if v is not None and not (isinstance(v, float) and math.isnan(v))}
    res.caveats = caveats
    return res


# ================================================================ deterministic parser
_T2S_PAIRS = ("續续 費费 勝胜 虧亏 損损 筆笔 幾几 週周 長长 連连 撤撤 後后 盤盘 單单 個个 這这 麼么 時时 間间 數数 總总 計计 們们 "
              "開开 倉仓 買买 賣卖 錢钱 賺赚 點点 鐘钟 種种 類类 嗎吗 還还 沒没 過过 來来 給给 說说 對对 為为 爲为 於于 與与 "
              "交交 淨净 盈盈 統统 業业 歷历 紀纪 錄录 讓让 樣样 會会 兩两 萬万 億亿 幣币 種种 漲涨 跌跌 價价 場场 機机 從从 "
              "較较 比比 內内 外外 頭头 當当 麽么 準准 確确 結结 果果 應应 該该 現现 經经 驗验 檢检 習习 慣惯 規规 則则 報报 復复 "
              "據据 實实 擬拟 戶户 帳账 賬账 線线 線线 動动 華华 遠远 近近 週周 末末 掉掉 除除 選选 擇择 間间 關关 門门 並并 幫帮")
_T2S = {p[0]: p[1] for p in _T2S_PAIRS.split() if len(p) == 2 and p[0] != p[1]}
_T2S_TABLE = str.maketrans(_T2S)
CJK_RX = re.compile(r"[一-鿿]")

SHORTHAND = {"wat": "what", "wht": "what", "whats": "what is", "hw": "how", "u": "you", "ur": "your", "avg": "average", "w/o": "without",
             "pls": "please", "plz": "please", "abt": "about", "wk": "week", "mcuh": "much", "winrate": "win rate", "pnl": "pnl",
             "p&l": "pnl", "p/l": "pnl", "tiem": "time", "bigest": "biggest", "loosing": "losing", "rn": "right now", "ytd": "year to date"}
VOCAB = ("fees fee commission commissions trades trade count many much biggest largest smallest worst best loss losses losing win wins winning "
         "winner winners loser losers rate average median hold holding time size position drawdown streak profit factor expectancy "
         "weekday weekdays weekend weekends monday tuesday wednesday thursday friday saturday sunday symbol symbols coin coins longs shorts "
         "without excluding exclude compare compared recent early last first third half week month days active busiest hour hours "
         "total net result money made lose lost share percent gross after before since when").split()
_VOCAB = set(VOCAB)
_COMMON = set("what that this then than them they there their these those when where which while with will would week weak well sell "
              "sold tell told test best rest last past post mine more most much must make made many mean real read ready rely rule rules "
              "rate rates date data part card cars case cash cast cost costs host lost lose loss lots look book took good gold hold held "
              "help home hope have gave give live love long song some same sale save safe size side site time fine line nine find kind "
              "sure user used fill fills full fall call came come done gone none note open over ever even every very many deal dear near "
              "sort short shot spot stop step team term trade trades trend price plan play days ways says sign month north worth world "
              "words works worse worst first list lift left less mass miss must just trust lean lead load loan loud bear been seen keen "
              "kept only into about from your mera meri kya hai tha kitna kitne kiye maine laga sabse bada kaunsa".split())


def _dl(a: str, b: str, cap: int = 2) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _repair(tok: str) -> str:
    if tok in SHORTHAND:
        return SHORTHAND[tok]
    if len(tok) < 4 or tok in _VOCAB or tok in _COMMON or not tok.isalpha():
        return tok
    cap = 1 if len(tok) < 8 else 2
    for w in VOCAB:
        if w[0] == tok[0] and abs(len(w) - len(tok)) <= cap and _dl(tok, w, cap) <= cap:
            return w
    return tok


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_T2S_TABLE).lower()
    t = t.replace("’", "'").replace("w/o", "without").replace("p&l", "pnl").replace("p/l", "pnl")
    t = re.sub(r"(?<=[一-鿿])(?=[a-z0-9$])|(?<=[a-z0-9%])(?=[一-鿿])", " ", t)
    t = re.sub(r"[a-z][a-z']*", lambda m: _repair(m.group(0)), t)
    return re.sub(r"\s+", " ", t).strip()


def detect_lang(text: str) -> str:
    return "zh" if CJK_RX.search(text or "") else "en"


# ---- patterns. Order matters: the first metric pattern that matches wins.
NONE_RX = re.compile(r"\bhabits?\b|\bcostly\b|\bwhat if\b|\bhad i\b|\bif i had\b|\bhalt\b|\brule\s*\d|\bthe .{0,10}rule\b|\bweekly review\b|\breview\b|\brecap\b|"
                     r"\bweekly report\b|^(hi|hello|hey|yo|thanks|thank you|ok|okay|help)\b|\bplace (an? )?order\b|\bexecute\b|\bbuy \d|\bsell \d|"
                     r"习惯|毛病|如果|假如|规则|复盘|周报|^(你好|您好|谢谢|帮助)|帮我(买|卖|下单)|下单")
UNSUPPORTED = [
    ("mae_mfe", re.compile(r"\bm[af]e\b|max(imum)? (adverse|favou?rable) excursion|最大(不利|有利)")),
    ("market_why", re.compile(r"\bwhy\b.{0,30}\b(price|market|it|btc|eth|coin|stock)\b.{0,20}\b(move|moved|drop|dropped|fall|fell|dump|pump|crash|rally|go|went)|"
                              r"why did (the )?(price|market)|为什么.{0,6}(价格|行情|币价|市场)|价格.{0,4}为什么|为什么.{0,6}(涨|跌)")),
    ("advice", re.compile(r"\bshould i (buy|sell|long|short|enter|exit|hold|add)\b|\bis (it|now) a good time\b|该买|该卖|要不要(买|卖)|现在.{0,4}买.{0,4}吗")),
    ("intent", re.compile(r"\bintent\b|\bintention\b|\bthesis before\b|\bwhy did i (enter|take|open)\b|下单前的(想法|意图)|意图")),
    ("funding", re.compile(r"\bfunding\b|资金费")),
    ("slippage", re.compile(r"\bslippage\b|滑点")),
    ("sharpe", re.compile(r"\bsharpe\b|\bsortino\b|\bcalmar\b|\bvolatil\w*|\bstandard deviation\b|\bvalue at risk\b|夏普|索提诺|波动率")),
    ("session", re.compile(r"\b(morning|afternoon|evening|overnight|at night|asian session|london session|us session|new york session)\b|早上|上午|下午|晚上|夜里|凌晨|亚洲盘|欧洲盘|美盘")),
    ("unrealised", re.compile(r"\bunreali[sz]ed\b|\bopen positions?\b|\bfloating\b|浮动|未实现|持仓盈亏")),
]
FOLLOWUP_RX = re.compile(r"^(and|so|what about|how about|then|but|also|ok|okay|now|only|just|same|again)\b|^(那|这|还有|再|换成|改成|只看|只|去掉)|呢[?？]?$")
WEEKDAY_WORDS = {0: r"mondays?|\bmon\b|周一|星期一|礼拜一", 1: r"tuesdays?|\btue\b|\btues\b|周二|星期二|礼拜二", 2: r"wednesdays?|\bwed\b|周三|星期三|礼拜三",
                 3: r"thursdays?|\bthu\b|\bthurs\b|周四|星期四|礼拜四", 4: r"fridays?|\bfri\b|周五|星期五|礼拜五", 5: r"saturdays?|\bsat\b|周六|星期六|礼拜六",
                 6: r"sundays?|\bsun\b|周日|周天|星期日|星期天|礼拜天|礼拜日"}
_WD = {d: re.compile(rx) for d, rx in WEEKDAY_WORDS.items()}
WEEKEND_RX = re.compile(r"weekends?|周末")
SYMBOL_ALIASES = {"btc": "BTC", "bitcoin": "BTC", "比特币": "BTC", "大饼": "BTC", "eth": "ETH", "ethereum": "ETH", "ether": "ETH", "以太坊": "ETH", "以太": "ETH",
                  "sol": "SOL", "solana": "SOL", "doge": "DOGE", "dogecoin": "DOGE", "狗狗币": "DOGE", "xrp": "XRP", "bnb": "BNB", "tsla": "TSLA", "tesla": "TSLA",
                  "特斯拉": "TSLA", "nvda": "NVDA", "nvidia": "NVDA", "英伟达": "NVDA", "aapl": "AAPL", "apple": "AAPL", "苹果": "AAPL", "googl": "GOOGL",
                  "google": "GOOGL", "谷歌": "GOOGL", "msft": "MSFT", "microsoft": "MSFT", "amzn": "AMZN", "amazon": "AMZN", "meta": "META", "hype": "HYPE",
                  "pump": "PUMP", "aster": "ASTER", "tao": "TAO", "ltc": "LTC", "ada": "ADA", "avax": "AVAX", "link": "LINK", "sui": "SUI", "pepe": "PEPE",
                  "wif": "WIF", "ena": "ENA", "arb": "ARB", "op": "OP", "mu": "MU", "orcl": "ORCL", "crcl": "CRCL", "coin": None}
_TICKER_STOP = {"PNL", "MAE", "MFE", "USD", "USDT", "UTC", "OK", "AI", "BTW", "FYI", "ASAP", "IMO", "LOL", "ATH", "ROI", "API", "CSV", "ETA", "YTD", "EOD"}
_PERIOD_RX = [
    ("last_7d", re.compile(r"\b(last|past|this|previous) week\b|\b(last|past) (7|seven) days\b|上周|上一周|这周|本周|最近一周|最近(7|七)天|过去(7|七)天|pichle hafte|is hafte")),
    ("last_30d", re.compile(r"\b(last|past|this|previous) month\b|\b(last|past) (30|thirty) days\b|上个月|上月|这个月|本月|最近(30|三十)天|最近一个月|过去(30|三十)天|pichle mahine")),
    ("last_90d", re.compile(r"\b(last|past) (90|ninety) days\b|\b(last|past|this) quarter\b|\b(last|past) (3|three) months\b|最近(90|九十)天|最近三个月|最近一个季度")),
    ("first_third", re.compile(r"\b(first|earliest|opening) third\b|最早三分之一|前三分之一|第一个三分之一")),
    ("last_third", re.compile(r"\b(last|most recent|recent|latest|final) third\b|最近三分之一|最后三分之一|后三分之一")),
    ("first_half", re.compile(r"\bfirst half\b|前半|前一半")),
    ("second_half", re.compile(r"\b(second|last|latter) half\b|后半|后一半")),
]
_LAST_N_RX = re.compile(r"\b(last|past|recent|latest) (\d{1,5}) (trades|trips|round trips)\b|最近\s*(\d{1,5})\s*笔")
_ALL_RX = re.compile(r"\b(whole|entire|full|all) (history|record|time|period)\b|\ball[- ]time\b|\boverall\b|\bever\b|全部|所有|整个|全部历史|所有交易|一直以来")
_COMPARE_RX = re.compile(r"\b(compare|compared|comparison|versus|vs\.?)\b.{0,40}\b(third|early|earlier|first|recent|later|latest)\b|"
                         r"\b(third|early|earlier|first|recent|later)\b.{0,40}\b(compare|compared|versus|vs\.?)\b|\b(getting|got) (better|worse)\b|\bimprov(e|ed|ing)\b|"
                         r"\bfirst third\b.{0,30}\blast third\b|\blast third\b.{0,30}\bfirst third\b|三分之一.{0,12}(比|相比|对比)|有进步|进步了吗|变好了吗|越来越")
_EXCL_RX = re.compile(r"\b(without|excluding|exclude|minus|drop|dropping|remove|removing|ignoring|ignore|not counting|take out|leave out)\b.{0,20}\b(single )?(best|biggest|largest|top) (trade|win|winner|one|trip)?|"
                      r"\bwithout (my |the )?(single )?best\b|去掉最好|不算最好|除去最好|扣掉最好|去掉最大的(一笔)?(盈利|赢)|不计最好")
_INCL_RX = re.compile(r"\b(back in|put it back|include it|with it back|including (my |the )?best|add it back)\b|加回|算上最好|包括最好")
_TOPN_RX = re.compile(r"\b(top|best|worst|biggest|largest|smallest|my) (\d{1,2})\b|\b(\d{1,2}) (biggest|largest|worst|best|top)\b|最大的\s*([一二两三四五六七八九十\d]+)\s*笔|前\s*([一二两三四五六七八九十\d]+)|top\s*([一二两三四五六七八九十\d]+)")
_ZH_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_GROUP_RX = [
    ("after_loss", re.compile(r"after (a |an? )?(loss|losing|losing trade|red trade|loser)\b.{0,25}\b(vs\.?|versus|compared|or|against|than)\b.{0,25}\b(win|winning|winner|green)|"
                              r"after a win.{0,30}after a loss|size (up|down|bigger|larger) after|亏损(之)?后.{0,10}(还是|和|与|对比|比).{0,10}(盈利|赢|赚)|亏损(之)?后.{0,6}(仓位|加仓).{0,6}(会|变|吗)")),
    ("weekday", re.compile(r"\b(by|per|each|every|which|what) (week)?day of (the )?week\b|\bby weekdays?\b|\bper weekday\b|\bwhich weekday\b|\bweekday breakdown\b|\bwhat day of the week\b|"
                           r"\b(best|worst|lowest|highest|weakest|strongest|top|bottom) (week)?days? of the week\b|\b(best|worst|lowest|highest|weakest|strongest|top|bottom) weekdays?\b|"
                           r"按星期|按周几|星期几|周几|每个星期")),
    ("hour", re.compile(r"\b(by|per|each|which|what) hour\b|\bhour of (the )?day\b|\btime of day\b|\bwhat time\b|\bby time\b|\bhourly\b|几点|按小时|什么时间段|哪个时段|时段")),
    ("symbol", re.compile(r"\b(by|per|each|which|what) (symbol|symbols|coin|coins|token|tokens|market|markets|ticker|tickers|pair|pairs|asset|assets|stock|stocks|instrument)\b|"
                          r"\btop \d{1,2} (symbols|coins|tokens|markets|pairs)\b|\b(symbol|coin|token|market|pair) breakdown\b|\bwhich (coin|symbol|token|market|pair)\b|"
                          r"按品种|按币种|按币|按标的|哪个币|哪个品种|哪些币|分品种|每个品种|每个币")),
    ("side", re.compile(r"\blongs? (vs\.?|versus|or|and|against) shorts?\b|\bshorts? (vs\.?|versus|or|and|against) longs?\b|\bby side\b|\bby direction\b|\blong(s)? or short(s)?\b|"
                        r"多单和空单|空单和多单|多空|多单还是空单|做多还是做空|按方向")),
    ("outcome", re.compile(r"\blosers? (longer|shorter|more|less) than winners?\b|\bwinners? (longer|shorter|more|less) than losers?\b|\bwinners? (vs\.?|versus|and|or) losers?\b|"
                           r"\blosers? (vs\.?|versus|and|or) winners?\b|\bby outcome\b|亏损单(比|和|与|还是)盈利单|盈利单(比|和|与|还是)亏损单|按输赢")),
]
_SIDE_SELL_RX = re.compile(r"\bshorts\b|\bshort (trades|positions|side|only)\b|\b(on|for|only|my) shorts?\b|\bshort trades\b|空单|做空|空头|只看空")
_SIDE_BUY_RX = re.compile(r"\blongs\b|\blong (trades|positions|side|only)\b|\b(on|for|only|my) longs\b|多单|做多|多头|只看多")
_OUT_LOSS_RX = re.compile(r"\b(losers|losing trades|losing positions|red trades|my losses)\b|\bof my losers\b|\bfor losers\b|亏损单|亏的单|亏损的交易|亏损交易")
_OUT_WIN_RX = re.compile(r"\b(winners|winning trades|winning positions|green trades)\b|\bfor winners\b|盈利单|赢的单|盈利的交易|赚钱的交易")
_AFTER_LOSS_RX = re.compile(r"\bafter (a |an? |my |some |the )?(losses|loss|losing|losing trades?|red trades?|losers?)\b|\bpost[- ]loss\b|\bfollowing a loss\b|亏损(之)?后|亏了(之)?后|输了(之)?后|亏损以后")
_AFTER_WIN_RX = re.compile(r"\bafter (a |an? )?(win|winning|winning trade|green trade|winner)\b|盈利(之)?后|赢了(之)?后|赚了(之)?后")
_METRIC_RX = [
    ("fee_share", re.compile(r"\bfees?\b.{0,30}\b(share|percent|percentage|proportion|fraction|ratio|%)\b|\b(share|percent|percentage|proportion|fraction)\b.{0,20}\bfees?\b|"
                             r"\bfees?\b.{0,20}\bof (my |the )?(gross )?(profit|profits|gains|winnings)\b|\b(profit|profits|gains)\b.{0,20}\b(went|go|goes|lost) to fees\b|"
                             r"手续费.{0,6}(占|比例|比重|百分比)|手续费.{0,4}利润")),
    ("total_fees", re.compile(r"\bfees?\b|\bcommissions?\b|\btrading costs?\b|手续费|佣金|交易费|费用")),
    ("win_rate", re.compile(r"\bwin ?rate\b|\bhit ?rate\b|\bstrike rate\b|\bhow often do i win\b|\bpercent(age)? of (trades )?(won|winners|wins)\b|\baccuracy\b|胜率|赢率|正确率|准确率|jeetne ka rate")),
    ("profit_factor", re.compile(r"\bprofit factor\b|盈利因子|获利因子|盈亏比|利润因子")),
    ("expectancy", re.compile(r"\bexpectancy\b|\bexpected (value|pnl|profit)( per trade)?\b|\bev per trade\b|期望值|每笔期望|期望")),
    ("avg_win", re.compile(r"\b(average|mean|typical) (winning trade|win|winner|gain)\b|\bavg winner\b|\bhow much do i (make|win) (when|on) (a |my )?(win|winner|winning)|平均每笔赢|平均盈利|平均赢|平均每笔赚")),
    ("avg_loss", re.compile(r"\b(average|mean|typical) (losing trade|loss|loser)\b|\bavg loser\b|\bhow much do i lose (when|on) (a |my )?(loss|loser|losing)|平均每笔亏|平均亏损|平均亏")),
    ("max_drawdown", re.compile(r"\bdrawdowns?\b|\bdraw downs?\b|\bpeak[- ]to[- ]trough\b|\bworst (losing )?run\b|回撤|最大回落")),
    ("win_streak", re.compile(r"\bwinning streak\b|\bwin streak\b|\bwins in a row\b|\bconsecutive (wins|winners|winning)\b|\bstreak of wins\b|连胜|连续(盈利|赢|赚)|连赢")),
    ("loss_streak", re.compile(r"\blosing streak\b|\bloss streak\b|\blosses in a row\b|\blosing trades in a row\b|\bconsecutive (losses|losers|losing)\b|\bstreak of losses\b|\bstreak\b|"
                               r"连亏|连续亏损|连续亏|连输|连败|连续.{0,3}(亏|输)")),
    ("busiest_day", re.compile(r"\bbusiest\b|\bmost (active|busy) day\b|\bday with (the )?most trades\b|\bmost trades in (a|one) day\b|\bwhich day (did|do) i trade (the )?most\b|"
                               r"哪天交易最多|交易最多的一天|哪一天.{0,4}(交易|做)最多|最忙的一天|最忙")),
    ("best_day", re.compile(r"\bbest day\b|\bmost profitable day\b|\bbiggest (winning|green|up) day\b|\bbest (trading )?(day|session)\b|最赚钱的一天|赚得最多的一天|赚最多的一天|最好的一天|盈利最多的一天|最好的那天|哪(一)?天.{0,3}(赚|盈利).{0,3}(最多|最好)|which day (did|do) i (make|earn|win) (the )?most\b")),
    ("worst_day", re.compile(r"\bworst day\b|\bbiggest (losing|red|down) day\b|\bworst (trading )?(day|session)\b|\bmost (i|i've) lost in (a|one) day\b|亏得最多的一天|亏最多的一天|最差的一天|亏损最多的一天|最差的那天|哪(一)?天.{0,3}亏.{0,3}(最多|最狠|最惨)|亏(得)?最(多|狠|惨)的(是)?哪(一)?天|which day (did|do) i lose (the )?most\b|what day (did|do) i lose (the )?most\b")),
    ("trades_per_day", re.compile(r"\btrades? (per|a|each|every) (day|session)\b|\bper day\b|\bdaily trade count\b|\bhow many trades (do i|a day|per day|daily)\b|\bhow often do i trade\b|"
                                  r"每天.{0,6}(几笔|多少笔|交易)|平均每天|一天.{0,4}(几笔|多少笔)|日均")),
    ("active_days", re.compile(r"\bactive days\b|\btrading days\b|\bdays (did|have|do) i trade\b|\bhow many days\b|\bdays (with|of) trad(es|ing)\b|交易了多少天|交易天数|多少个交易日|活跃天数|做了多少天")),
    ("time_since_last", re.compile(r"\bsince (my |the )?last trade\b|\blast trade\b|\bwhen did i last\b|\blast time i traded\b|\bhow long ago\b|\bmost recent trade\b|\bwhen was my last\b|"
                                   r"上次交易|上一次交易|最后一次交易|最近一次交易|多久没(交易|做)|最后一笔")),
    ("median_size", re.compile(r"\b(median|average|typical|usual|mean|normal) (position |order |opening |trade )?size\b|\bposition size\b|\bsize (up|down|bigger|larger|smaller)\b|\bsizing\b|"
                               r"\bhow big (are|is) my (trades|positions|orders|size)\b|\bnotional\b|\bsize after\b|\btrade size\b|\border size\b|仓位|头寸|下单金额|单笔金额|开仓大小|仓位大小")),
    ("hold", re.compile(r"\bhold(ing)? (time|times|period|periods|duration)\b|\bhow long do i (usually |typically |normally )?(hold|stay in|keep)\b|\bhold (losers|winners|trades|positions)\b|"
                        r"\bheld\b|\bduration\b|\btime in (trade|market|position)\b|\bhow long (do|did) (my )?(trades|positions|losers|winners) last\b|持仓时间|持有时间|拿多久|持仓多久|拿多长时间|持仓.{0,4}(时长|多长)|多久平仓|持有多久|拿得")),
    ("best_trade", re.compile(r"\bbest (single )?(trade|trip|win|winner|position)\b|\b(biggest|largest|greatest|top) (single )?(win|winner|winning trade|gain|profit)\b|\btop \d{1,2} (trades|winners|wins)\b|"
                              r"\bbiggest profit\b|\bmost profitable trade\b|最好的一笔|最好的交易|最大的盈利|最大盈利|赚最多的一笔|赚得最多的一笔|最赚钱的一笔|最大的一笔盈利|最大赢|前\s*[一二两三四五六七八九十\d]+\s*笔")),
    ("worst_trade", re.compile(r"\bworst (single )?(trade|trip|loss|loser|position)\b|\b(biggest|largest|greatest|single largest|max|maximum) (single )?(loss|losses|loser|losing trade|drawn?)\b|"
                               r"\btop \d{1,2} (losses|losers)\b|\b\d{1,2} (biggest|largest|worst) (losses|losers|losing trades)\b|\bmost i lost (on|in) (a|one) trade\b|"
                               r"最大的亏损|最大亏损|亏最多的一笔|亏得最多的一笔|最差的一笔|最差的交易|最大的一笔亏损|最大的.{0,3}笔亏损|最大的损失|sabse bada (loss|nuksan|nuqsan)")),
    ("wins", re.compile(r"\bhow many (trades )?(wins|winners|winning trades|did i win|have i won|green trades)\b|\bnumber of (wins|winners|winning trades)\b|\bcount (of )?(wins|winners)\b|"
                        r"\bwins count\b|赢了多少笔|赢了几笔|多少笔盈利|盈利.{0,3}(几笔|多少笔)|几笔(盈利|赢|赚)|多少笔赚|kitne (trades )?jeete")),
    ("losses", re.compile(r"\bhow many (trades )?(losses|losers|losing trades|did i lose|have i lost|red trades)\b|\bnumber of (losses|losers|losing trades)\b|\bcount (of )?(losses|losers)\b|"
                          r"\blosses count\b|亏了多少笔|亏了几笔|多少笔亏损|亏损.{0,3}(几笔|多少笔)|几笔(亏损|亏|输)|多少笔亏|kitne (trades )?haare")),
    ("trade_count", re.compile(r"\bhow many (trades|trips|round trips|positions|times|shorts|longs|short trades|long trades|entries)\b|\bnumber of (trades|trips|round trips)\b|\btrade count\b|\bcount of trades\b|\btrades (did|have) i (make|made|take|taken|do|done|place|placed)\b|"
                               r"\btrades (made|taken|placed)\b|\bhow many (did i|have i) (trade|make)\b|\bhow much did i trade\b|\bhow many\b.{0,15}\btrades\b|多少笔|几笔|多少次|几次|交易次数|交易笔数|kitne trades|kitni trades")),
    ("avg_pnl", re.compile(r"\b(average|mean|avg|typical) (pnl|profit|result|return|outcome|trade)( per trade)?\b|\bpnl per trade\b|\bper trade\b|\bper[- ]trade (pnl|profit|result)\b|"
                           r"平均每笔盈亏|平均盈亏|每笔平均|平均每笔|每笔.{0,4}平均")),
    ("net_pnl", re.compile(r"\bnet (pnl|profit|result|gain|loss|return)\b|\bpnl\b|\bprofit\b|\bprofits\b|\bprofitable\b|\bhow much (money )?(did|have) i (make|made|lose|lost|earn|earned|win|won)\b|"
                           r"\bmade me (the )?(most|least) money\b|\b(most|least) money\b|\bmoney\b|\bresult\b|\bgains?\b|\breturns?\b|\bbottom line\b|\blose the most\b|\blost the most\b|"
                           r"\bearn(ed|ings)?\b|\bdo (i|better) (better|worse)\b|盈亏|净利|净收益|赚了多少|亏了多少|赚多少|亏多少|赚钱|亏钱|收益|利润|哪个赚|亏得最多|赚得最多|亏得|赚得|kitna (kamaya|profit|loss|nuksan)")),
]
_CLARIFY_BARE = re.compile(r"^(my |the |what('s| is| was) my |show (me )?my )?(best|biggest|largest|worst|top|greatest|smallest)( one| trade)?\??$|^最好的$|^最大的$|^最差的$|^最好$|^最大$")
_CLARIFY_LONG = re.compile(r"^(how long|how long\?|多久|多长时间|多长时间\?)$")


class ParseResult(BaseModel):
    kind: Literal["plan", "unsupported", "clarify", "none", "unparsed"]
    plan: Optional[QueryPlan] = None
    reason: Optional[str] = None             # unsupported: which family; clarify: what is missing
    options: list[dict] = Field(default_factory=list)   # clarify: candidate compact plans with labels
    lang: str = "en"
    followup: bool = False
    slots: dict = Field(default_factory=dict)


def _zh_num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if s in _ZH_NUM:
        return _ZH_NUM[s]
    if len(s) == 2 and s[0] == "十":
        return 10 + _ZH_NUM.get(s[1], 0)
    if len(s) == 2 and s[1] == "十":
        return _ZH_NUM.get(s[0], 0) * 10
    return None


def _find_symbol(raw: str, t: str) -> str | None:
    for m in re.finditer(r"(?<![A-Za-z])[A-Z][A-Z0-9]{1,6}(?![A-Za-z])", unicodedata.normalize("NFKC", raw or "")):
        tok = m.group(0)
        if tok not in _TICKER_STOP and not tok.isdigit():
            return tok
    for word in re.findall(r"[a-z]{2,10}|[一-鿿]{2,4}", t):
        if word in SYMBOL_ALIASES and SYMBOL_ALIASES[word]:
            return SYMBOL_ALIASES[word]
    return None


def _slots(raw: str, t: str) -> dict:
    s: dict = {}
    wd = sorted({d for d, rx in _WD.items() if rx.search(t)})
    if WEEKEND_RX.search(t):
        wd = sorted(set(wd) | {5, 6})
    if wd:
        s["weekdays"] = wd
    if _SIDE_SELL_RX.search(t) and not re.search(r"\bshort(ly|er|est)?\b(?! trades| positions| side| only)(?<!for short)(?<!my short)(?<!on short)", t) or re.search(r"\bshorts\b|空单|做空|只看空", t):
        s["side"] = "sell"
    elif _SIDE_BUY_RX.search(t):
        s["side"] = "buy"
    if _OUT_LOSS_RX.search(t):
        s["outcome"] = "loss"
    elif _OUT_WIN_RX.search(t):
        s["outcome"] = "win"
    if _AFTER_LOSS_RX.search(t):
        s["after_loss"] = True
    elif _AFTER_WIN_RX.search(t):
        s["after_loss"] = False
    sym = _find_symbol(raw, t)
    if sym:
        s["symbol"] = sym
    for kind, rx in _PERIOD_RX:
        if rx.search(t):
            s["period"] = {"kind": kind}
            break
    m = _LAST_N_RX.search(t)
    if m:
        s["period"] = {"kind": "last_n", "n": int(m.group(2) or m.group(4))}
    if "period" not in s and _ALL_RX.search(t):
        s["period"] = {"kind": "all"}
    if _COMPARE_RX.search(t):
        s["compare"] = "first_vs_last_third"
        s.pop("period", None)
    if _INCL_RX.search(t):
        s["exclude_best"] = False
    elif _EXCL_RX.search(t):
        s["exclude_best"] = True
    m = _TOPN_RX.search(t)
    if m:
        n = next((v for v in (_zh_num(x) for x in m.groups() if x) if v), None)
        if n and 1 <= n <= 20:
            s["top_n"] = n
    for g, rx in _GROUP_RX:
        if rx.search(t):
            s["group_by"] = g
            break
    return s


def _metric(t: str) -> str | None:
    for name, rx in _METRIC_RX:
        if rx.search(t):
            if name == "hold":
                if re.search(r"\b(average|mean|avg)\b|平均", t):
                    return "avg_hold"
                return "median_hold"
            return name
    return None


def _parse_raw(text: str, previous: QueryPlan | dict | None = None) -> ParseResult:
    """Deterministic question -> ParseResult. `previous` lets a short follow-up modify the last plan."""
    raw = (text or "")[:500]
    t = normalise(raw)
    lang = detect_lang(raw)
    prev = previous if isinstance(previous, QueryPlan) else (validate_plan(previous) if previous else None)
    if not t:
        return ParseResult(kind="none", lang=lang)
    for reason, rx in UNSUPPORTED:
        if rx.search(t) or rx.search(raw.lower()):      # the typo repair turns "sharpe" into "share": test the raw words too
            return ParseResult(kind="unsupported", reason=reason, lang=lang)
    metric = _metric(_EXCL_RX.sub(" ", _INCL_RX.sub(" ", t)))      # "without my best trade" is a modifier, not the metric
    if metric is None and re.search(r"\bhow many\b|\bkitne\b|\bkitni\b|多少|几笔|几次", t):
        metric = "trade_count"
    slots = _slots(raw, t)
    if NONE_RX.search(t) and (metric is None or re.search(r"\bhabit|习惯|下单|place (an? )?order|\bbuy \d|\bsell \d", t)):
        return ParseResult(kind="none", lang=lang)
    # a follow-up inherits the previous plan only when the turn is marked as one ("and ...", "what about",
    # "那...呢") or names no metric of its own; a fresh question with its own metric starts clean
    followup = prev is not None and (bool(FOLLOWUP_RX.search(t)) or metric is None)
    # size + after-a-loss is a comparison question ("do I size up after a loss?")
    if metric == "median_size" and slots.get("after_loss") is not None and "group_by" not in slots:
        slots["group_by"] = "after_loss"
    if "group_by" in slots and slots["group_by"] == "after_loss":
        slots.pop("after_loss", None)
    if "group_by" in slots and slots["group_by"] == "outcome":
        slots.pop("outcome", None)
    if "group_by" in slots and slots["group_by"] == "side":
        slots.pop("side", None)
    if "group_by" in slots and slots["group_by"] == "weekday":
        slots.pop("weekdays", None)
    if "group_by" in slots and slots["group_by"] == "symbol":
        slots.pop("symbol", None)
    # a bare "best"/"how long" with nothing to anchor it
    if metric is None and not followup:
        if _CLARIFY_BARE.search(t):
            zh = lang == "zh"
            loss = re.search(r"worst|最差", t)
            opts = ([{"label": "最差的一笔" if zh else "worst trade", "plan": {"metric": "worst_trade"}},
                     {"label": "最差的一天" if zh else "worst day", "plan": {"metric": "worst_day"}}] if loss else
                    [{"label": "最好的一笔" if zh else "best trade", "plan": {"metric": "best_trade"}},
                     {"label": "最赚钱的一天" if zh else "best day", "plan": {"metric": "best_day"}},
                     {"label": "最大的亏损" if zh else "biggest loss", "plan": {"metric": "worst_trade"}}])
            return ParseResult(kind="clarify", reason="which_extreme", options=opts, lang=lang)
        if _CLARIFY_LONG.search(t):
            zh = lang == "zh"
            return ParseResult(kind="clarify", reason="which_duration", lang=lang, options=[
                {"label": "一般拿多久（中位持仓时间）" if zh else "typical hold time", "plan": {"metric": "median_hold"}},
                {"label": "上次交易是什么时候" if zh else "time since my last trade", "plan": {"metric": "time_since_last"}}])
        filt = {k: v for k, v in slots.items() if k in ("symbol", "weekdays", "side", "outcome", "after_loss")}
        if filt or "period" in slots:
            zh = lang == "zh"
            base = {"filters": filt} if filt else {}
            if "period" in slots:
                base["period"] = slots["period"]
            return ParseResult(kind="clarify", reason="which_metric", lang=lang, slots=slots, options=[
                {"label": "多少笔" if zh else "how many trades", "plan": {"metric": "trade_count", **base}},
                {"label": "净盈亏" if zh else "net P&L", "plan": {"metric": "net_pnl", **base}},
                {"label": "胜率" if zh else "win rate", "plan": {"metric": "win_rate", **base}}])
        if "group_by" in slots or "compare" in slots or "exclude_best" in slots or "top_n" in slots:
            metric = "net_pnl"
        else:
            return ParseResult(kind="none", lang=lang)
    if metric is None and followup:
        if "group_by" in slots or "compare" in slots or "exclude_best" in slots or "top_n" in slots or any(k in slots for k in ("symbol", "weekdays", "side", "outcome", "after_loss", "period")):
            metric = prev.metric
        elif re.search(r"\bbest\b|最好", t):
            metric = {"worst_trade": "best_trade", "worst_day": "best_day", "losses": "wins", "loss_streak": "win_streak", "avg_loss": "avg_win"}.get(prev.metric, "best_trade")
        elif re.search(r"\bworst\b|最差", t):
            metric = {"best_trade": "worst_trade", "best_day": "worst_day", "wins": "losses", "win_streak": "loss_streak", "avg_win": "avg_loss"}.get(prev.metric, "worst_trade")
        else:
            return ParseResult(kind="none", lang=lang)
    base = prev.compact() if (followup and prev is not None) else {}
    if base and slots.get("group_by"):
        # a question that names its own grouping must not inherit a filter on that same dimension ("and on fridays?" then
        # "which weekday is my worst"), and a fresh (not marked) question starts without any inherited filters
        dim = {"weekday": "weekdays", "symbol": "symbol", "side": "side", "outcome": "outcome", "after_loss": "after_loss"}.get(slots["group_by"])
        flt = dict(base.get("filters", {}))
        if not FOLLOWUP_RX.search(t):
            flt = {}
        flt.pop(dim, None)
        base = {**base, "filters": flt}
    if base and base.get("group_by") and not slots.get("group_by"):
        # "and on fridays?" after a by-weekday answer: the named slice replaces the grouping instead of leaving one group
        gdim = {"weekday": "weekdays", "symbol": "symbol", "side": "side", "outcome": "outcome", "after_loss": "after_loss"}.get(base["group_by"])
        if gdim in slots:
            base = {**base, "group_by": None}
    if followup and prev is not None and metric != prev.metric and ("group_by" in base) and "group_by" not in slots:
        pass                                              # "and the win rate?" after "pnl by weekday": keep the grouping
    plan_d: dict = {"metric": metric, "filters": dict(base.get("filters", {})), "period": dict(base.get("period", {"kind": "all"})),
                    "group_by": base.get("group_by"), "compare": base.get("compare", "none"), "top_n": base.get("top_n"),
                    "exclude_best": base.get("exclude_best", False)}
    for k in ("symbol", "weekdays", "side", "outcome", "after_loss"):
        if k in slots:
            plan_d["filters"][k] = slots[k]
    if "period" in slots:
        plan_d["period"] = slots["period"]
    if "compare" in slots:
        plan_d["compare"] = slots["compare"]
    if "group_by" in slots:
        plan_d["group_by"] = slots["group_by"]
        if slots["group_by"] == "after_loss":
            plan_d["filters"].pop("after_loss", None)
    if "exclude_best" in slots:
        plan_d["exclude_best"] = slots["exclude_best"]
    if "top_n" in slots:
        plan_d["top_n"] = slots["top_n"]
    if metric in ("best_trade", "worst_trade", "best_day", "worst_day", "busiest_day") and plan_d["group_by"] in ("after_loss", "outcome"):
        plan_d["group_by"] = None
    plan = validate_plan(plan_d)
    if plan is None:
        return ParseResult(kind="none", lang=lang)
    return ParseResult(kind="plan", plan=plan, lang=lang, followup=bool(followup and prev is not None), slots=slots)


# ---------------------------------------------------------------- hardening of the raw parse
_ALL_DAYS = set(range(7))
_NEG_RX = re.compile(r"\b(except|excluding|exclude|other than|apart from|besides|not counting|ignoring|ignore|skipping|but not|not on|without|minus)\b(?P<tail>[^,.?;]{0,40})")
_WEEKDAYS_WORD = re.compile(r"\bweekdays\b")
_GROUP_WD = re.compile(r"\b(by|per|each|which|what|every) (week ?)?days?\b|\bby weekdays?\b|\bper weekday\b|\bbest weekday\b|\bworst weekday\b|\bweekday breakdown\b")
_NEG_SIDE = re.compile(r"\b(not counting|excluding|exclude|except|without|ignoring|ignore|other than|minus|no|not)\s+(my\s+)?(shorts?|longs?)\b")
_NON_WIN = re.compile(r"\bnon[- ]?(winning|winners?|profitable)\b|\bnot (winning|profitable)\b|\bunprofitable\b|\bdidn'?t win\b")
_NON_LOSS = re.compile(r"\bnon[- ]?(losing|losers?)\b|\bnot losing\b|\bdidn'?t lose\b")
_TIMES_LOSE = re.compile(r"\bhow many (times? )?(did|have|do) i (lose|lost)\b")
_TIMES_WIN = re.compile(r"\bhow many times? (did|have|do) i (win|won)\b")
_WHAT_LOSE = re.compile(r"\bwhat (did|have|do) i (lose|lost|make|made|earn|earned|win|won)\b")
_NUMW = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
_WINDOW = re.compile(r"\b(last|past|previous)\s+(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s+(day|days|week|weeks|month|months|year|years)\b")
_WINDOW_OK = {7, 30, 90}
_OTHER_WINDOW = re.compile(r"\b(yesterday|today|tonight|this year|last year|year to date)\b|\b(in|during|since|before|from|after) (january|february|march|april|may|june|july|august|september|october|november|december)\b|"
                           r"\b(since|before|after|from) \d{4}-\d{2}|\b(after|before|at|around) \d{1,2} ?(am|pm|:\d\d)\b|\bbetween \d{1,2} ?(am|pm|:\d\d)?\b.{0,6}\band \d")
_MONTHS = r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?)"
_ORD = r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d{1,2}(st|nd|rd|th))"
_DATE_RX = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b|\b" + _MONTHS + r"\.? \d{1,2}(st|nd|rd|th)?\b|\b\d{1,2}(st|nd|rd|th)? (of )?" + _MONTHS + r"\b|"
                      r"\b" + _ORD + r" of (the month|" + _MONTHS + r")\b|\bon the \d{1,2}(st|nd|rd|th)\b|\bon (the )?" + _ORD + r" of\b|\d{1,2}月\d{1,2}[日号]?")
_DAYS_OUTCOME = re.compile(r"\bhow many days\b.{0,25}\b(lose|lost|win|won|profit|green|red|make|made)\b")
UNPARSED_EN = {"window": "I could not parse that time window: I can only slice the record by the last week, month or quarter, by thirds or halves, or by the last N trades.",
             "day_outcome": "I could not parse that: I can count trades and active days, but not how many days ended green or red.",
             "empty_days": "I could not parse that day filter: the days it names cancel each other out.",
             "date": "I could not parse that: I can't filter the record to one calendar date, so I will not quote a total as if it were that day. I can name your best or worst day, or slice by weekday."}
UNPARSED_ZH = {"window": "我没能读懂这个时间范围：我只能按最近一周、一个月、一个季度、三分之一、一半，或最近 N 笔来切分记录。",
             "day_outcome": "我没能读懂这个问题：我能数交易笔数和交易天数，但数不了有几天盈利或亏损。",
             "empty_days": "我没能读懂这个星期过滤条件：它们互相抵消了。",
             "date": "我没能读懂这个问题：我不能把记录限定到某个具体日期，所以不会拿总数当作那一天的数字。我可以告诉你最好或最差的一天，或按星期几拆分。"}


def _days_in(t: str) -> set[int]:
    d = {k for k, rx in _WD.items() if rx.search(t)}
    if WEEKEND_RX.search(t):
        d |= {5, 6}
    if _WEEKDAYS_WORD.search(t):
        d |= {0, 1, 2, 3, 4}
    return d


def unparseable(t: str) -> str | None:
    """A reason when the question needs something the closed schema cannot express (answering anyway = wrong number)."""
    m = _WINDOW.search(t)
    if m:
        n = int(m.group(2)) if m.group(2).isdigit() else _NUMW[m.group(2)]
        days = n * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group(3).rstrip("s")]
        if days not in _WINDOW_OK:
            return "window"
    if _OTHER_WINDOW.search(t):
        return "window"
    if _DAYS_OUTCOME.search(t):
        return "day_outcome"
    if _DATE_RX.search(t):
        return "date"
    return None


def rewrite_plan(t: str, d: dict) -> str | None:
    """Apply clean fixes to a plan dict in place. Returns a refusal reason or None."""
    f = d.setdefault("filters", {})
    if d.get("group_by") != "weekday" and not _GROUP_WD.search(t):
        neg_days: set[int] = set()
        stripped = t
        for m in _NEG_RX.finditer(t):
            nd = _days_in(m.group("tail"))
            if nd:
                neg_days |= nd
                stripped = stripped.replace(m.group(0), " ")
        pos = _days_in(stripped)
        if neg_days:
            final = (pos or _ALL_DAYS) - neg_days
            if not final:
                return "empty_days"
            f["weekdays"] = sorted(final)
        elif pos and pos != set(f.get("weekdays", [])):
            f["weekdays"] = sorted(pos)
    m = _NEG_SIDE.search(t)
    if m:
        f["side"] = "buy" if m.group(3).startswith("short") else "sell"
    if _NON_WIN.search(t):
        f["outcome"] = "loss"
    elif _NON_LOSS.search(t):
        f["outcome"] = "win"
    if d.get("metric") == "trade_count":
        if _TIMES_LOSE.search(t):
            d["metric"] = "losses"
        elif _TIMES_WIN.search(t):
            d["metric"] = "wins"
    if not f:
        d.pop("filters", None)
    return None


def _harden(raw: str, pr: "ParseResult") -> "ParseResult":
    """Post-process a parse: rewrite negation / 'weekdays' / 'how many times did I lose' into the closed schema, or return
    kind='unparsed' when the question needs something the schema cannot express. Never yields a plan for a different question."""
    if pr.kind not in ("plan", "clarify"):
        return pr
    t = normalise(raw)
    reason = unparseable(t)
    if reason:
        return ParseResult(kind="unparsed", reason=reason, lang=pr.lang)
    if pr.kind == "clarify":
        if pr.reason != "which_metric" or not _WHAT_LOSE.search(t):
            return pr
        d = json.loads(json.dumps(pr.options[1]["plan"]))      # the net-P&L option, with the filters the parser found
        base = ParseResult(kind="plan", lang=pr.lang, slots=pr.slots)
    else:
        d = pr.plan.compact()
        base = pr
    reason = rewrite_plan(t, d)
    if reason:
        return ParseResult(kind="unparsed", reason=reason, lang=pr.lang)
    plan = validate_plan(d)
    if plan is None:
        return pr
    return base.model_copy(update={"kind": "plan", "plan": plan})


def parse(text: str, previous: QueryPlan | dict | None = None) -> ParseResult:
    """Deterministic question -> ParseResult (see _parse_raw), then hardened against negation and unsupported windows."""
    return _harden((text or "")[:500], _parse_raw(text, previous))


# ================================================================ rendering (number-locked)
METRIC_NAME = {
    "trade_count": ("trades", "交易笔数"), "wins": ("winning trades", "盈利笔数"), "losses": ("losing trades", "亏损笔数"), "win_rate": ("win rate", "胜率"),
    "net_pnl": ("net P&L", "净盈亏"), "avg_pnl": ("average P&L per trade", "平均每笔盈亏"), "avg_win": ("average winning trade", "平均盈利单"),
    "avg_loss": ("average losing trade", "平均亏损单"), "median_size": ("median opening size", "中位开仓金额"), "avg_hold": ("average hold time", "平均持仓时间"),
    "median_hold": ("median hold time", "中位持仓时间"), "best_trade": ("best trade", "最好的一笔"), "worst_trade": ("largest loss", "最大的一笔亏损"),
    "total_fees": ("total fees", "手续费总额"), "fee_share": ("fees as a share of gross profit", "手续费占毛利润的比例"), "profit_factor": ("profit factor", "盈利因子"),
    "expectancy": ("expectancy per trade", "每笔期望值"), "max_drawdown": ("max drawdown of the realised curve", "已实现曲线的最大回撤"),
    "win_streak": ("longest winning streak", "最长连胜"), "loss_streak": ("longest losing streak", "最长连亏"), "trades_per_day": ("trades per active day", "每个交易日的笔数"),
    "busiest_day": ("busiest day", "交易最多的一天"), "best_day": ("best day", "最赚钱的一天"), "worst_day": ("worst day", "亏得最多的一天"),
    "active_days": ("active days", "交易天数"), "time_since_last": ("time since the last trade", "距上次交易"),
}
PERIOD_NAME = {"all": ("whole record", "全部记录"), "last_7d": ("last 7 days of the record", "记录最后 7 天"), "last_30d": ("last 30 days of the record", "记录最后 30 天"),
               "last_90d": ("last 90 days of the record", "记录最后 90 天"), "first_third": ("first third", "最早三分之一"), "last_third": ("most recent third", "最近三分之一"),
               "first_half": ("first half", "前一半"), "second_half": ("second half", "后一半"), "last_n": ("last {n} trades", "最近 {n} 笔")}
CAVEAT_TEXT = {
    "small_n": ("Only {n} trades: read this as a description, not a measured pattern.", "只有 {n} 笔：这是描述，不是经过检验的模式。"),
    "empty": ("No trades match, so there is nothing to compute.", "没有符合条件的交易，无法计算。"),
    "no_symbol_match": ("No trades on that symbol in your record; symbols traded: {syms}.", "记录里没有这个品种的交易；交易过的品种：{syms}。"),
    "no_fee_data": ("This record has no per-fill fee data, so fees cannot be computed.", "这份记录没有逐笔手续费数据，无法计算手续费。"),
    "thin_groups": ("Some groups have fewer than 10 trades; their numbers are fragile.", "有些分组少于 10 笔，数字不稳定。"),
    "after_loss_first_trade_dropped": ("The first trade has no earlier result, so it is left out.", "第一笔之前没有结果，已排除。"),
    "zero_pnl_dropped": ("Trades with exactly zero P&L are neither wins nor losses and are left out.", "盈亏恰好为零的交易既不算赢也不算亏，已排除。"),
    "thirds_small": ("Fewer than 10 trades per third; the comparison is weak.", "每个三分之一不足 10 笔，比较说服力弱。"),
    "record_end": ("Measured to now from the last trade in the record; this demo record is historical.", "从记录中最后一笔算到现在；演示记录是历史数据。"),
    "only_one_trade": ("Only one trade matched, and it was the one excluded.", "只有一笔符合条件，而且正是被排除的那笔。"),
}
UNSUPPORTED_TEXT = {
    "mae_mfe": ("MAE/MFE (how far a trade went against or for you while open) needs price paths during each trade; this record has fills only.",
                "MAE/MFE（持仓期间最大不利/有利波动）需要每笔交易期间的价格路径；这份记录只有成交。"),
    "market_why": ("I only read your own fills. I cannot say why a price moved; there is no market or news data here.", "我只读你自己的成交记录，无法解释价格为什么动；这里没有行情或新闻数据。"),
    "advice": ("I don't give buy or sell advice. I can show how your own similar trades turned out.", "我不做买卖建议。我可以给你看你自己类似交易的结果。"),
    "intent": ("No pre-trade intent is stamped on these trades, so grading intent would be hindsight.", "这些交易没有事前记录的意图，评判意图只会是事后诸葛。"),
    "funding": ("Funding payments are not in this record, so they cannot be counted.", "这份记录里没有资金费，无法统计。"),
    "slippage": ("Slippage needs the intended price per order; the record has fill prices only.", "滑点需要每笔的意图价格；记录里只有成交价。"),
    "sharpe": ("I do not compute Sharpe, Sortino or volatility. A Sharpe ratio needs an equity series with a time base; per-trade results are not one. I can give expectancy, profit factor and drawdown.",
               "我不计算夏普、索提诺或波动率。夏普比率需要带时间基准的权益序列，逐笔结果不是；我可以给期望值、盈利因子和回撤。"),
    "session": ("Sessions like morning or night depend on a time zone I do not know; the record has UTC timestamps only. I can rank your hours of the day in UTC, for example: what was my best time of day?",
                "早上、晚上这类时段取决于你所在的时区，我不知道；记录里只有 UTC 时间戳。我可以按 UTC 小时给你排名，例如：我什么时候交易最赚钱？"),
    "unrealised": ("Only closed round trips are in the record; open positions are not.", "记录里只有已平仓的完整交易，没有持仓。"),
}
CHIP_POOL = [("net_pnl", "What is my net P&L?", "我的净盈亏是多少？"), ("win_rate", "What is my win rate?", "我的胜率是多少？"),
             ("total_fees", "How much did fees cost me?", "手续费一共花了多少？"), ("worst_trade", "What was my biggest loss?", "我最大的一笔亏损是什么？"),
             ("max_drawdown", "What was my max drawdown?", "最大回撤是多少？"), ("median_hold", "How long do I usually hold?", "我一般拿多久？"),
             ("trades_per_day", "How many trades per day?", "平均每天交易几笔？"), ("profit_factor", "What is my profit factor?", "我的盈利因子是多少？"),
             ("loss_streak", "What is my longest losing streak?", "最长连亏多少笔？"), ("best_day", "What was my best day?", "最赚钱的一天是哪天？")]


def fmt_num(v: float, unit: str, lang: str = "en") -> tuple[str, list[float]]:
    """Formatted text and the numerals a number-lock must find in it."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ("n/a" if lang == "en" else "无"), []
    if unit == "money":
        s = (f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}") + " USDT"
        return s, [round(v, 2) if abs(v) < 1000 else float(round(v))]
    if unit == "pct":
        return f"{100 * v:.1f}%", [round(100 * v, 1)]
    if unit == "count":
        return f"{int(round(v)):,}", [float(int(round(v)))]
    if unit == "ratio":
        return f"{v:.2f}", [round(v, 2)]
    if unit == "hours":
        if v < 1:
            m = int(round(v * 60))
            return (f"{m} min" if lang == "en" else f"{m} 分钟"), [float(m)]
        if v >= 48:
            d = round(v / 24, 1)
            return (f"{d} days" if lang == "en" else f"{d} 天"), [d]
        return (f"{v:.1f} h" if lang == "en" else f"{v:.1f} 小时"), [round(v, 1)]
    if unit == "days":
        if v < 1:
            h = round(v * 24, 1)
            return (f"{h} hours" if lang == "en" else f"{h} 小时"), [h]
        return (f"{v:.1f} days" if lang == "en" else f"{v:.1f} 天"), [round(v, 1)]
    return f"{v:.2f}", [round(v, 2)]


def scope_clause(res: "QAResult", lang: str = "en") -> tuple[str, list[float]]:
    """One sentence saying which slice of the record a filtered answer covers (never answer a slice as if it were the whole record)."""
    plan = res.plan
    f = plan.filters
    if not (f.symbol or f.side or f.weekdays or f.outcome or f.after_loss is not None or plan.period.kind != "all") or res.groups or res.compare:
        return "", []
    desc = describe_plan(plan, lang, scope_only=True)
    if not desc:
        return "", []
    nums = [float(res.n), float(res.n_total)] + [float(x) for x in re.findall(r"[0-9]+", desc)]
    if lang == "zh":
        return f"范围：{desc}（记录共 {res.n_total} 笔里的 {res.n} 笔）。", nums
    return f" Scope: {desc}, {res.n} trades out of {res.n_total} in the record.", nums


def describe_plan(plan: QueryPlan, lang: str = "en", scope_only: bool = False) -> str:
    zh = lang == "zh"
    parts = [] if scope_only else [METRIC_NAME[plan.metric][1 if zh else 0]]
    f = plan.filters
    if f.symbol:
        parts.append(f"只看 {f.symbol}" if zh else f"{f.symbol} only")
    if f.side:
        parts.append(group_label("side", f.side, lang))
    if f.weekdays:
        days = [group_label("weekday", str(d), lang) for d in f.weekdays]
        parts.append("、".join(days) if zh else "/".join(days) + " only")
    if f.outcome:
        parts.append(group_label("outcome", f.outcome, lang))
    if f.after_loss is not None:
        parts.append(group_label("after_loss", "1" if f.after_loss else "0", lang))
    if plan.group_by and not scope_only:
        g = {"weekday": ("by weekday", "按星期几"), "hour": ("by hour (UTC)", "按小时（UTC）"), "symbol": ("by symbol", "按品种"), "side": ("longs vs shorts", "多单对空单"),
             "after_loss": ("after a loss vs after a win", "亏损后对盈利后"), "outcome": ("winners vs losers", "盈利单对亏损单")}[plan.group_by]
        parts.append(g[1 if zh else 0])
    if plan.compare != "none" and not scope_only:
        parts.append("最早三分之一对最近三分之一" if zh else "first third vs last third")
    if plan.period.kind != "all":
        parts.append(PERIOD_NAME[plan.period.kind][1 if zh else 0].format(n=plan.period.n or 20))
    if plan.top_n and not scope_only:
        parts.append(f"前 {plan.top_n}" if zh else f"top {plan.top_n}")
    if plan.exclude_best and not scope_only:
        parts.append("去掉最好的一笔" if zh else "without your single best trade")
    return "，".join(parts) if zh else ", ".join(parts)


def _headline(res: QAResult, lang: str) -> tuple[str, list[float]]:
    zh = lang == "zh"
    m = res.plan.metric
    nums: list[float] = [float(res.n)]
    n = res.n
    d = res.detail

    def F(v, unit=None):
        s, ns = fmt_num(v, unit or res.unit, lang)
        nums.extend(ns)
        return s

    def IV():
        if not res.interval:
            return ""
        a, b = F(res.interval[0]), F(res.interval[1])
        return f"（95% 区间 {a} 到 {b}）" if zh else f" (95% interval {a} to {b})"
    if not res.available or (res.value is None and not res.groups and not res.compare):
        if "no_symbol_match" in res.caveats:
            return (f"记录里没有 {res.plan.filters.symbol} 的交易。" if zh else f"No trades on {res.plan.filters.symbol} in your record."), nums
        if m in ("total_fees", "fee_share") and "no_fee_data" in res.caveats:
            return CAVEAT_TEXT["no_fee_data"][1 if zh else 0], nums
        if m == "fee_share" and d.get("reason") == "no gross profit":
            return ("没有毛利润（扣费前也没有盈利的交易），所以手续费占比没有意义。" if zh else "No gross profit (no trade made money before fees), so a fee share is not defined."), nums
        if m == "profit_factor":
            return ("没有亏损的交易，盈利因子没有定义。" if zh else "No losing trades, so the profit factor is not defined."), nums
        nums.append(float(res.n_total))
        return (f"没有符合条件的交易（记录共 {res.n_total} 笔）。" if zh else f"No trades match ({n} of {res.n_total})."), nums
    if res.compare:
        c = res.compare
        a, b = F(c["first"]), F(c["last"])
        nums.extend([float(c["n_first"]), float(c["n_last"])])
        name = METRIC_NAME[m][1 if zh else 0]
        return ((f"{name}：最早三分之一（{c['n_first']} 笔）是 {a}，最近三分之一（{c['n_last']} 笔）是 {b}。" if zh else
                 f"{name[0].upper() + name[1:]}: {a} in your first third ({c['n_first']} trades) versus {b} in your most recent third ({c['n_last']} trades)."), nums)
    if res.groups:
        top, bot = d["top"], d["bottom"]
        g = res.plan.group_by
        thick = [x for x in res.groups if x.n >= 2]
        thin = [x for x in res.groups if x.n < 2]
        if thin and len(res.groups) > 1:       # a one-trade group is an anecdote: never rank or compare it
            name = METRIC_NAME[m][1 if zh else 0]
            tn = ", ".join(f"{group_label(g, x.key, lang)} {F(x.value)}" for x in thin)
            nums.extend(float(x.n) for x in thin)
            if len(thick) >= 2:
                hi, lo = max(thick, key=lambda x: x.value), min(thick, key=lambda x: x.value)
                a, b = F(hi.value), F(lo.value)
                nums.extend([float(hi.n), float(lo.n)])
                prep = "on " if g in ("weekday", "hour") else "for "
                return (f"{name}最高的是{group_label(g, hi.key, lang)}：{a}（{hi.n} 笔）；最低的是{group_label(g, lo.key, lang)}：{b}（{lo.n} 笔）。只有 1 笔的分组（{tn}）不参与比较。" if zh else
                        f"{name[0].upper() + name[1:]} is highest {prep}{group_label(g, hi.key, lang)}: {a} ({hi.n} trades) and lowest {prep}{group_label(g, lo.key, lang)}: {b} ({lo.n} trades). "
                        f"Left out of the comparison because it has only 1 trade: {tn}."), nums
            if len(thick) == 1:
                x = thick[0]
                nums.append(float(x.n))
                return (f"{name}：只有{group_label(g, x.key, lang)}有多于 1 笔：{F(x.value)}（{x.n} 笔）。其余分组只有 1 笔（{tn}），样本太少，不做比较。" if zh else
                        f"{name[0].upper() + name[1:]}: only {group_label(g, x.key, lang)} has more than 1 trade: {F(x.value)} ({x.n} trades). "
                        f"The rest have 1 trade each ({tn}), too few to compare."), nums
        lt, lb = group_label(g, top["key"], lang), group_label(g, bot["key"], lang)
        vt, vb = F(top["value"]), F(bot["value"])
        nums.extend([float(top["n"]), float(bot["n"])])
        name = METRIC_NAME[m][1 if zh else 0]
        if len(res.groups) == 1:
            return (f"{name}只有一组：{lt} {vt}（{top['n']} 笔）。" if zh else f"Only one group for {name}: {lt} {vt} ({top['n']} trades)."), nums
        if zh:
            return f"{name}最高的是{lt}：{vt}（{top['n']} 笔）；最低的是{lb}：{vb}（{bot['n']} 笔）。", nums
        prep = "on " if g in ("weekday", "hour") else "for "
        return f"{name[0].upper() + name[1:]} is highest {prep}{lt}: {vt} ({top['n']} trades) and lowest {prep}{lb}: {vb} ({bot['n']} trades).", nums
    v = res.value
    if m == "trade_count":
        return (f"符合条件的完整交易有 {F(v)} 笔。" if zh else f"{F(v)} complete trades match."), nums
    if m in ("wins", "losses"):
        return ((f"{n} 笔里有 {F(v)} 笔{'盈利' if m == 'wins' else '亏损'}。") if zh else f"{F(v)} of {n} trades were {'winners' if m == 'wins' else 'losers'}."), nums
    if m == "win_rate":
        w, l = d.get("wins", 0), d.get("losses", 0)
        nums.extend([float(w), float(l)])
        s = F(v)
        return (f"胜率 {s}：{w} 笔盈利，{l} 笔亏损{IV()}。" if zh else f"Win rate {s}: {w} winners and {l} losers{IV()}."), nums
    if m == "net_pnl":
        ex = d.get("excluded_best")
        if ex:
            exs = F(ex["net_pnl"], "money")
            return (f"去掉最好的一笔（{exs}）后，{n} 笔的净盈亏是 {F(v)}。" if zh else f"Without your single best trade ({exs}), net P&L over {n} trades is {F(v)}."), nums
        return (f"{n} 笔交易的净盈亏是 {F(v)}（已扣手续费）。" if zh else f"Net P&L over {n} trades is {F(v)}, after fees."), nums
    if m in ("avg_pnl", "expectancy"):
        s = F(v)
        return (f"平均每笔盈亏 {s}{IV()}，共 {n} 笔。" if zh else f"Average result per trade is {s}{IV()} over {n} trades."), nums
    if m in ("avg_win", "avg_loss"):
        k = d.get("n_wins", d.get("n_losses", 0))
        nums.append(float(k))
        return ((f"{'平均盈利单' if m == 'avg_win' else '平均亏损单'} {F(v)}（{k} 笔）。") if zh else
                f"Your average {'winner made' if m == 'avg_win' else 'loser lost'} {F(v)} ({k} trades)."), nums
    if m == "median_size":
        return (f"中位开仓金额 {F(v)}（{n} 笔）。" if zh else f"Median opening size is {F(v)} over {n} trades."), nums
    if m in ("avg_hold", "median_hold"):
        s = F(v)
        return ((f"{'平均' if m == 'avg_hold' else '中位'}持仓时间 {s}（{n} 笔）。") if zh else
                f"{'Average' if m == 'avg_hold' else 'Median'} hold time is {s} over {n} trades."), nums
    if m in ("best_trade", "worst_trade"):
        s = F(v)
        if res.rows and len(res.rows) > 1:
            k = len(res.rows)
            tot = F(sum(r["net_pnl"] for r in res.rows), "money")
            nums.append(float(k))
            return ((f"你{'最好' if m == 'best_trade' else '最大亏损'}的 {k} 笔合计 {tot}；{'最好' if m == 'best_trade' else '最大'}的一笔是 {d['symbol']}（{d['day']}）：{s}。") if zh else
                    f"Your {k} {'best trades' if m == 'best_trade' else 'largest losses'} add up to {tot}; the {'best' if m == 'best_trade' else 'largest'} was {d['symbol']} on {d['day']}: {s}."), nums
        return ((f"{'最好的一笔' if m == 'best_trade' else '最大的一笔亏损'}是 {d['symbol']}（{d['day']}）：{s}。") if zh else
                f"Your {'best trade' if m == 'best_trade' else 'largest loss'} was {d['symbol']} on {d['day']}: {s}."), nums
    if m == "total_fees":
        return (f"{n} 笔交易共付手续费 {F(v)}。" if zh else f"Fees over {n} trades came to {F(v)}."), nums
    if m == "fee_share":
        s = F(v)
        gp, tf = F(d["gross_profit"], "money"), F(d["total_fees"], "money")
        return (f"手续费 {tf} 占毛利润 {gp} 的 {s}{IV()}。" if zh else f"Fees of {tf} took {s} of your gross profit of {gp}{IV()}."), nums
    if m == "profit_factor":
        return (f"盈利因子 {F(v)}：总盈利 {F(d['gross_profit'], 'money')}，总亏损 {F(d['gross_loss'], 'money')}。" if zh else
                f"Profit factor {F(v)}: gross profit {F(d['gross_profit'], 'money')} against gross loss {F(d['gross_loss'], 'money')}."), nums
    if m == "max_drawdown":
        return (f"已实现盈亏曲线的最大回撤是 {F(v)}（{n} 笔）。" if zh else f"The realised P&L curve's largest peak-to-trough drop was {F(v)} over {n} trades."), nums
    if m in ("win_streak", "loss_streak"):
        return ((f"最长{'连胜' if m == 'win_streak' else '连亏'} {F(v)} 笔。") if zh else f"Longest {'winning' if m == 'win_streak' else 'losing'} streak: {F(v)} trades in a row."), nums
    if m == "trades_per_day":
        nums.append(float(d["active_days"]))
        return (f"平均每个交易日 {F(v)} 笔，共 {d['active_days']} 个交易日。" if zh else f"{F(v)} trades per active day across {d['active_days']} active days."), nums
    if m == "busiest_day":
        return (f"交易最多的一天是 {d['day']}：{F(v)} 笔。" if zh else f"Your busiest day was {d['day']} with {F(v)} trades."), nums
    if m in ("best_day", "worst_day"):
        nums.append(float(d["trades_that_day"]))
        return ((f"{'最赚钱' if m == 'best_day' else '亏得最多'}的一天是 {d['day']}：{F(v)}（{d['trades_that_day']} 笔）。") if zh else
                f"Your {'best' if m == 'best_day' else 'worst'} day was {d['day']}: {F(v)} over {d['trades_that_day']} trades."), nums
    if m == "active_days":
        return (f"有交易的天数：{F(v)} 天。" if zh else f"You traded on {F(v)} days."), nums
    if m == "time_since_last":
        return (f"上次交易是 {d['last_day']}（{d['last_symbol']}），距今 {F(v)}。" if zh else f"Your last trade closed on {d['last_day']} ({d['last_symbol']}), {F(v)} ago."), nums
    return F(v), nums


def _card(res: QAResult, lang: str) -> dict:
    zh = lang == "zh"
    m = res.plan.metric
    if res.compare:
        c = res.compare
        return {"type": "tiles", "tiles": [
            {"label": "最早三分之一" if zh else "first third", "value": fmt_num(c["first"], res.unit, lang)[0], "raw": c["first"], "n": c["n_first"]},
            {"label": "最近三分之一" if zh else "most recent third", "value": fmt_num(c["last"], res.unit, lang)[0], "raw": c["last"], "n": c["n_last"]},
            {"label": "变化" if zh else "change", "value": fmt_num(res.value, res.unit, lang)[0], "raw": res.value}]}
    if res.groups:
        return {"type": "bars", "unit": res.unit, "items": [{"label": group_label(res.plan.group_by, g.key, lang), "key": g.key, "value": g.value,
                                                             "text": fmt_num(g.value, res.unit, lang)[0], "n": g.n} for g in res.groups]}
    if res.rows:
        cols = ["日期", "品种", "方向", "开仓金额", "净盈亏"] if zh else ["day", "symbol", "side", "size", "net P&L"]
        return {"type": "table", "columns": cols, "rows": [[r["day"], r["symbol"], group_label("side", r["side"], lang), fmt_num(r["size"], "money", lang)[0],
                                                              fmt_num(r["net_pnl"], "money", lang)[0]] for r in res.rows]}
    tiles = [{"label": METRIC_NAME[m][1 if zh else 0], "value": fmt_num(res.value, res.unit, lang)[0], "raw": res.value}]
    if res.interval:
        tiles.append({"label": "95% 区间" if zh else "95% interval", "value": f"{fmt_num(res.interval[0], res.unit, lang)[0]} – {fmt_num(res.interval[1], res.unit, lang)[0]}",
                      "raw": list(res.interval)})
    d = res.detail
    extra = {"avg_win": ("平均盈利单", "avg winner", "money"), "avg_loss": ("平均亏损单", "avg loser", "money"), "gross_profit": ("总盈利", "gross profit", "money"),
             "gross_loss": ("总亏损", "gross loss", "money"), "total_fees": ("手续费", "fees", "money"), "active_days": ("交易日", "active days", "count"),
             "median_per_day": ("每日中位数", "median per day", "ratio"), "wins": ("盈利", "winners", "count"), "losses": ("亏损", "losers", "count"),
             "size": ("开仓金额", "size", "money"), "pnl_that_day": ("当日盈亏", "P&L that day", "money"), "trades_that_day": ("当日笔数", "trades that day", "count")}
    for k, (lz, le, u) in extra.items():
        if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool):
            tiles.append({"label": lz if zh else le, "value": fmt_num(float(d[k]), u, lang)[0], "raw": float(d[k])})
    for k in ("symbol", "day", "last_day"):
        if k in d:
            tiles.append({"label": {"symbol": ("品种", "symbol"), "day": ("日期", "day"), "last_day": ("最后交易日", "last trade")}[k][0 if zh else 1], "value": str(d[k])})
    if m != "trade_count":                       # the metric tile already is the trade count
        tiles.append({"label": "笔数" if zh else "trades", "value": f"{res.n:,}", "raw": float(res.n)})
    seen: set = set()
    tiles = [t for t in tiles if not ((t["label"], t["value"]) in seen or seen.add((t["label"], t["value"])))]
    return {"type": "tiles", "tiles": tiles[:6]}


def _how(res: QAResult, lang: str) -> dict:
    zh = lang == "zh"
    p = res.plan
    w = res.window
    win = PERIOD_NAME[p.period.kind][1 if zh else 0].format(n=p.period.n or 20)
    if w.get("from") and w.get("to"):
        win += f"（{w['from']} 至 {w['to']}）" if zh else f" ({w['from']} to {w['to']})"
    method = ("由你的完整交易计算（按品种从空仓到空仓，已扣除该笔全部手续费）。时间为 UTC；星期几/小时按开仓时间；回撤按平仓顺序。区间为按笔抽样的 bootstrap（是量的区间，不是概率）。" if zh else
              "Computed from your round trips (flat-to-flat per symbol, net of every fee in the trip). Times are UTC; weekday/hour use the trade's open time; "
              "the drawdown uses close order. Intervals are a seeded bootstrap over trades (an interval for the quantity, not a probability).")
    cav = []
    syms = ", ".join(res.detail.get("symbols_traded", [])[:6])
    for c in res.caveats:
        if c in CAVEAT_TEXT:
            cav.append(CAVEAT_TEXT[c][1 if zh else 0].format(n=res.n, syms=syms))
    if p.exclude_best and res.detail.get("excluded_best"):
        ex = res.detail["excluded_best"]
        cav.append((f"排除的是 {ex['symbol']}（{ex['day']}）这一笔。" if zh else f"Excluded: {ex['symbol']} on {ex['day']}."))
    return {"n": res.n, "n_total": res.n_total, "window": win, "method": method, "caveats": cav}


def _chips(plan: QueryPlan, lang: str) -> list[str]:
    zh = lang == "zh"
    out: list[str] = []
    money = plan.metric in ("net_pnl", "avg_pnl", "expectancy", "win_rate", "profit_factor", "fee_share")
    if money and not plan.exclude_best:
        out.append("去掉最好的一笔呢？" if zh else "And without my best trade?")
    if plan.group_by is None and plan.compare == "none" and plan.metric not in ("time_since_last", "busiest_day", "best_day", "worst_day", "active_days"):
        out.append("按星期几看呢？" if zh else "What about by weekday?")
    if plan.metric in ("net_pnl", "win_rate", "avg_pnl") and plan.compare == "none":
        out.append("最近三分之一和最早三分之一比呢？" if zh else "Compare my first third with my last third")
    for m, en, cn in CHIP_POOL:
        if len(out) >= 3:
            break
        if m != plan.metric:
            out.append(cn if zh else en)
    return out[:3]


def _singular(text: str) -> str:
    """'1 trades' -> '1 trade' (English only; the numeral is unchanged, so the number-lock is unaffected)."""
    text = re.sub(r"(?<![\d.,])1 complete trades match\b", "1 complete trade matches", text)
    return re.sub(r"(?<![\d.,])1 (trade|winner|loser|day|trip)s\b", r"1 \1", text)


def render(res: QAResult, lang: str = "en") -> dict:
    """Headline + card + how-computed + chips; the headline is number-locked against the result's facts."""
    text, nums = _headline(res, lang)
    sc, scn = scope_clause(res, lang)
    if sc and "Scope:" not in text and "范围：" not in text:
        text, nums = text + sc, nums + scn
    text = _singular(text)
    facts = sorted(set(list(res.facts.values()) + nums))
    checked = re.sub(r"\d{4}-\d{2}-\d{2}|\b\d{2}:00\b", "", text)
    try:
        verify(checked, facts, allow=(0.0, 1.0, 95.0))
        lock = "passed"
    except NumberLockError as e:
        text = ("这个回答里有一个无法由计算结果支持的数字，已拒绝。" if lang == "zh" else "That answer had a number I could not back with a computed fact, so I refused it.")
        lock = f"refused: {e}"
    return {"text": text, "card": _card(res, lang), "computed": _how(res, lang), "next": _chips(res.plan, lang), "number_lock": lock,
            "facts": [{"fact": k, "value": v} for k, v in res.facts.items()], "interpreted": describe_plan(res.plan, lang)}


def render_unsupported(reason: str, lang: str = "en") -> dict:
    zh = lang == "zh"
    cannot = UNSUPPORTED_TEXT.get(reason, UNSUPPORTED_TEXT["market_why"])[1 if zh else 0]
    can = [cn if zh else en for _, en, cn in CHIP_POOL[:3]]
    lead = "我能回答的例如：" if zh else "Three things I can answer: "
    return {"text": cannot + " " + lead + ("；".join(can) if zh else "; ".join(can)) + ("。" if zh else "."),
            "card": {"type": "unsupported", "reason": reason, "cannot": cannot, "can": can},
            "computed": {"n": 0, "window": None, "method": None, "caveats": []}, "next": can, "number_lock": "passed", "facts": [],
            "interpreted": ("无法从记录计算的问题" if zh else "a question this record cannot answer")}


def render_clarify(pr: ParseResult, lang: str = "en") -> dict:
    zh = lang == "zh"
    q = {"which_extreme": ("你是指哪一个？", "Which one do you mean?"), "which_duration": ("你是指哪个时间？", "Which time do you mean?"),
         "which_metric": ("要看哪个数字？", "Which number do you want for that?")}.get(pr.reason, ("你是指？", "Which do you mean?"))[0 if zh else 1]
    labels = [o["label"] for o in pr.options]
    return {"text": q + " " + ("、".join(labels) if zh else " / ".join(labels)), "card": {"type": "clarify", "question": q, "options": pr.options},
            "computed": {"n": 0, "window": None, "method": None, "caveats": []}, "next": labels[:3], "number_lock": "passed", "facts": [],
            "interpreted": ("需要澄清" if zh else "needs one clarification")}
