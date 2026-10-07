"""Personal trading thesis: a short, bilingual summary assembled ONLY from engine facts.

Nothing here invents a number. `build_facts` reads a finished review dict (habit tests, court verdicts,
priced rule) plus the trader's round trips; `render` turns those facts into plain sentences (EN and 中文);
`thesis_hash` freezes facts + date; `diff` compares two frozen key sets; `score` checks a frozen prediction
against trips that arrived later. Underpowered cases say so instead of guessing.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

import numpy as np

from .court import _baseline
from .detectors import after_loss_labels

MIN_NEW_TRIPS = 30          # same floor the court uses for unseen trades
MIN_NEW_AFTER_LOSS = 10     # and the same floor for trades a rule must touch
_RANK = {"FLAGGED": 3, "SUGGESTIVE": 2, "NOT_FLAGGED": 1, "UNDERPOWERED": 0, None: 0}


def _i(x) -> int | None:
    return None if x is None else int(round(float(x)))


def _style_label(med_hold_h: float) -> tuple[str, str]:
    if med_hold_h < 1:
        return "scalper (median hold under 1 hour)", "超短线（持仓中位数不到 1 小时）"
    if med_hold_h < 24:
        return "intraday trader (median hold 1 to 24 hours)", "日内交易者（持仓中位数 1 到 24 小时）"
    return "swing trader (median hold over 24 hours)", "波段交易者（持仓中位数超过 24 小时）"


def size_ratio(trips) -> float | None:
    """Median opening size after a loss divided by median opening size otherwise (None if either group is empty)."""
    lab = after_loss_labels(trips)
    a = [t.first_order_notional for t, l in zip(trips, lab) if l == 1]
    b = [t.first_order_notional for t, l in zip(trips, lab) if l == 0]
    if not a or not b or float(np.median(b)) <= 0:
        return None
    return float(np.median(a)) / float(np.median(b))


def build_facts(review: dict, trips) -> dict:
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    n = len(ts)
    holds = [t.hold_ms / 3.6e6 for t in ts]
    span_days = max((max(t.t_close_ms for t in ts) - ts[0].t_open_ms) / 8.64e7, 1.0)
    sym = Counter(t.symbol for t in ts)
    top, top_n = sym.most_common(1)[0]
    med_hold = round(float(np.median(holds)), 1)
    en, zh = _style_label(med_hold)
    style = {"label_en": en, "label_zh": zh, "n_trips": n, "med_hold_h": med_hold,
             "med_notional": _i(np.median([t.first_order_notional for t in ts])), "trips_per_day": round(n / span_days, 1),
             "swing_h": 24, "top_symbol": top, "top_share_pct": _i(100 * top_n / n), "n_symbols": len(sym),
             "long_pct": _i(100 * sum(t.side == "buy" for t in ts) / n),
             "win_pct": _i(100 * sum(t.net_pnl > 0 for t in ts) / n), "net_pnl": _i(sum(t.net_pnl for t in ts))}
    h = review["headline"]
    pr = h["priced"]
    sal = next((f for f in review["findings"] if f["detector"] == "size_after_loss"), None)
    ratio = size_ratio(ts)
    habit = {"status": sal["status"] if sal else None, "size_ratio": None if ratio is None else round(ratio, 2),
             "cap_multiple": 1.5, "ci_pct": 95, "effect": _i(pr["all_history_effect"]),
             "lo": _i(pr["all_history_ci"][0]), "hi": _i(pr["all_history_ci"][1]),
             "held_out": _i(pr["held_out_effect"]), "rule_status": pr["status"]}
    vs = review["court"]["verdicts"]
    court = {"tested": len(vs), "accepted": sum(v["status"] == "ACCEPTED" for v in vs),
             "rejected": sum(v["status"] == "REJECTED" for v in vs),
             "underpowered": sum(v["status"] == "UNDERPOWERED" for v in vs), "test_trips": vs[0]["test_trips"] if vs else 0}
    acc = [v for v in vs if v["status"] == "ACCEPTED"]
    if acc:
        b = max(acc, key=lambda v: v["held_out_effect"])
        rule = {"armable": True, "multiple": b["multiple"], "held_out": _i(b["held_out_effect"]), "affected": b["affected"],
                "test_trips": b["test_trips"]}
    else:
        rule = {"armable": False, "multiple": None, "held_out": None, "affected": None, "test_trips": court["test_trips"],
                "underpowered": bool(vs) and court["underpowered"] == len(vs)}
    needed = max(MIN_NEW_TRIPS - court["test_trips"], 0) if rule.get("underpowered") else MIN_NEW_TRIPS
    change = {"min_new_trips": MIN_NEW_TRIPS, "min_new_after_loss": MIN_NEW_AFTER_LOSS, "trips_needed": needed}
    return {"style": style, "habit": habit, "court": court, "rule": rule, "change": change}


def key_of(facts: dict) -> dict:
    """The small set of numbers a later version is compared against."""
    return {"n_trips": facts["style"]["n_trips"], "habit_status": facts["habit"]["status"], "habit_effect": facts["habit"]["effect"],
            "habit_lo": facts["habit"]["lo"], "habit_hi": facts["habit"]["hi"], "accepted": facts["court"]["accepted"],
            "rule_multiple": facts["rule"]["multiple"], "rule_held_out": facts["rule"]["held_out"]}


def thesis_hash(facts: dict, day: str) -> str:
    return hashlib.sha256(json.dumps({"facts": facts, "date": day}, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def prediction_of(facts: dict, trips) -> dict:
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    mult = facts["rule"]["multiple"] or facts["habit"]["cap_multiple"]
    ratio = facts["habit"]["size_ratio"]
    return {"as_of_ms": max(t.t_close_ms for t in ts), "cap_multiple": mult, "baseline": round(_baseline(ts), 2),
            "size_ratio": ratio, "predicts_habit_persists": bool(ratio is not None and ratio > 1.0),
            "predicts_rule_saves": bool(facts["rule"]["armable"]), "rule_armable": bool(facts["rule"]["armable"])}


def score(prediction: dict, trips) -> dict:
    """Compare a frozen prediction with trips that opened after it was frozen. Never scores a thin tail."""
    allt = sorted(trips, key=lambda t: t.t_open_ms)
    lab = after_loss_labels(allt)
    idx = [i for i, t in enumerate(allt) if t.t_open_ms > prediction["as_of_ms"]]
    new = [allt[i] for i in idx]
    after = [i for i in idx if lab[i] == 1]
    cap = prediction["cap_multiple"] * prediction["baseline"]
    touched = [i for i in after if allt[i].first_order_notional > cap > 0]
    effect = sum(allt[i].net_pnl * (cap / allt[i].first_order_notional - 1.0) for i in touched)
    r = size_ratio_in(allt, lab, idx)
    out = {"n_new": len(new), "n_new_after_loss": len(after), "n_touched": len(touched), "effect": _i(effect),
           "size_ratio_new": None if r is None else round(r, 2), "size_ratio_frozen": prediction["size_ratio"],
           "testable": len(new) >= MIN_NEW_TRIPS and len(after) >= MIN_NEW_AFTER_LOSS}
    if not out["testable"]:
        out.update(habit="NOT_TESTABLE", rule="NOT_TESTABLE")
        return out
    out["habit"] = "NA" if prediction["size_ratio"] is None or r is None else (
        "CONFIRMED" if (r > 1.0) == prediction["predicts_habit_persists"] else "MISSED")
    out["rule"] = ("CONFIRMED" if effect > 0 else "MISSED") if prediction["predicts_rule_saves"] else "NA"
    return out


def size_ratio_in(allt, lab, idx) -> float | None:
    a = [allt[i].first_order_notional for i in idx if lab[i] == 1]
    b = [allt[i].first_order_notional for i in idx if lab[i] == 0]
    if not a or not b or float(np.median(b)) <= 0:
        return None
    return float(np.median(a)) / float(np.median(b))


def diff(prev: dict, cur: dict, version: int) -> list[dict]:
    """Plain sentences on what moved between two frozen key sets (empty list = nothing moved)."""
    out = []
    v = f"thesis v{version}"
    if cur["habit_effect"] is not None and prev["habit_effect"] is not None and cur["habit_effect"] != prev["habit_effect"]:
        up = cur["habit_effect"] > prev["habit_effect"]
        out.append({"en": f"{v}: size-after-loss habit {'strengthened' if up else 'weakened'} since v1 (a 1.5x cap's effect went from ${prev['habit_effect']:,} to ${cur['habit_effect']:,})",
                    "zh": f"{v}：亏损后加仓这个习惯{'增强' if up else '减弱'}了（1.5 倍上限的效果从 ${prev['habit_effect']:,} 变为 ${cur['habit_effect']:,}）"})
    if _RANK.get(cur["habit_status"], 0) != _RANK.get(prev["habit_status"], 0):
        out.append({"en": f"{v}: habit test status changed from {prev['habit_status']} to {cur['habit_status']}",
                    "zh": f"{v}：习惯检验状态从 {prev['habit_status']} 变为 {cur['habit_status']}"})
    if cur["accepted"] != prev["accepted"]:
        out.append({"en": f"{v}: rules accepted by the court went from {prev['accepted']} to {cur['accepted']}",
                    "zh": f"{v}：法庭通过的规则从 {prev['accepted']} 条变为 {cur['accepted']} 条"})
    if cur["n_trips"] != prev["n_trips"]:
        out.append({"en": f"{v}: built on {cur['n_trips']} trips (v1 had {prev['n_trips']})", "zh": f"{v}：基于 {cur['n_trips']} 笔交易（v1 为 {prev['n_trips']} 笔）"})
    return out


def _usd(x: int) -> str:
    return ("-$" if x < 0 else "$") + f"{abs(x):,}"


def render(facts: dict) -> dict:
    """{"en": [lines], "zh": [lines]}; each line is one sentence group. Every numeral comes from `facts`."""
    s, h, c, r, ch = facts["style"], facts["habit"], facts["court"], facts["rule"], facts["change"]
    en, zh = [], []
    en.append(f"Who you are in numbers: a {s['label_en']}, {s['n_trips']} trips, median opening size ${s['med_notional']:,}, "
              f"{s['trips_per_day']} trips a day, {s['top_share_pct']}% of them in {s['top_symbol']} ({s['n_symbols']} symbols), "
              f"{s['long_pct']}% long, {s['win_pct']}% winners, net {_usd(s['net_pnl'])}.")
    zh.append(f"数字里的你：{s['label_zh']}，共 {s['n_trips']} 笔，开仓大小中位数 ${s['med_notional']:,}，每天 {s['trips_per_day']} 笔，"
              f"其中 {s['top_share_pct']}% 在 {s['top_symbol']}（共 {s['n_symbols']} 个品种），{s['long_pct']}% 做多，{s['win_pct']}% 盈利，净 {_usd(s['net_pnl'])}。")
    if h["effect"] is None:
        en.append("Costliest habit: not measured, there is not enough history to price a size cap.")
        zh.append("最贵的习惯：没有测出来，历史太短，无法给大小上限定价。")
    elif h["effect"] > 0 and h["lo"] > 0:
        en.append(f"Costliest habit: sizing up after a loss. A 1.5x cap would have saved about {_usd(h['effect'])} (95% range {_usd(h['lo'])} to {_usd(h['hi'])}).")
        zh.append(f"最贵的习惯：亏损后加大仓位。1.5 倍上限本可省下约 {_usd(h['effect'])}（95% 范围 {_usd(h['lo'])} 到 {_usd(h['hi'])}）。")
    elif h["effect"] > 0:
        en.append(f"Costliest habit candidate: sizing up after a loss, about {_usd(h['effect'])} but the 95% range {_usd(h['lo'])} to {_usd(h['hi'])} includes zero, so it is not established.")
        zh.append(f"最贵习惯的候选：亏损后加大仓位，约 {_usd(h['effect'])}，但 95% 范围 {_usd(h['lo'])} 到 {_usd(h['hi'])} 包含零，所以没有被证实。")
    else:
        en.append(f"Costliest habit: none priced. A 1.5x cap after a loss would have changed your result by {_usd(h['effect'])} (range {_usd(h['lo'])} to {_usd(h['hi'])}), so there is no money-losing size habit here.")
        zh.append(f"最贵的习惯：没有定价出来。亏损后设 1.5 倍上限只会让结果变化 {_usd(h['effect'])}（范围 {_usd(h['lo'])} 到 {_usd(h['hi'])}），所以这里没有赔钱的加仓习惯。")
    en.append(f"What the court said: {c['accepted']} accepted, {c['rejected']} rejected, {c['underpowered']} underpowered, out of {c['tested']} size caps tested on unseen trades.")
    zh.append(f"法庭怎么说：在没见过的交易上测试了 {c['tested']} 个大小上限，通过 {c['accepted']} 个，未通过 {c['rejected']} 个，样本不足 {c['underpowered']} 个。")
    if r["armable"]:
        en.append(f"Rule to arm: cap opening size at {r['multiple']}x your median after a loss. On unseen trades it would have changed {_usd(r['held_out'])}, touching {r['affected']} of {r['test_trips']} trades.")
        zh.append(f"建议启用的规则：亏损后开仓大小上限为你中位数的 {r['multiple']} 倍。在没见过的交易上效果 {_usd(r['held_out'])}，触及 {r['affected']} / {r['test_trips']} 笔。")
    elif r.get("underpowered"):
        en.append(f"Rule to arm: none yet, underpowered (n={r['test_trips']} unseen trades; the court needs {ch['min_new_trips']}).")
        zh.append(f"建议启用的规则：暂无，样本不足（没见过的交易 n={r['test_trips']}；法庭至少需要 {ch['min_new_trips']} 笔）。")
    else:
        en.append("Rule to arm: none. The court accepted no cap on this history, so nothing is recommended.")
        zh.append("建议启用的规则：无。法庭没有通过任何上限，所以不推荐。")
    en.append(f"What would change this: confirmed if at least {ch['trips_needed']} more trips (with at least {ch['min_new_after_loss']} after a loss) show the same after-loss sizing and the cap would still have saved money; "
              f"killed if the sizing pattern disappears or the cap would not have saved money.")
    zh.append(f"什么会改变这个结论：再来至少 {ch['trips_needed']} 笔交易（其中至少 {ch['min_new_after_loss']} 笔在亏损之后）仍显示同样的亏损后仓位，且上限仍能省钱，则被证实；"
              f"如果这个仓位模式消失，或上限没有省钱，则被推翻。")
    return {"en": en, "zh": zh}


def numeric_facts(facts: dict) -> list[float]:
    """Every number in the facts (for the chat number-lock), skipping text."""
    out: list[float] = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            out.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
    walk(facts)
    return out


def score_lines(sc: dict, label: str) -> dict:
    """Plain sentences for a score result; `label` is shown first ("replay" or "forward")."""
    en_label = {"replay": "REPLAY on a held-back tail of your own history (a deterministic demo, not live)",
                "forward": "FORWARD check on trips that arrived after the freeze"}[label]
    zh_label = {"replay": "回放：用你自己历史中留出的末段（确定性演示，不是实时）", "forward": "前向检验：冻结之后新出现的交易"}[label]
    if not sc["testable"]:
        return {"en": f"{en_label}: not testable yet, {sc['n_new']} new trips and {sc['n_new_after_loss']} after a loss (need {MIN_NEW_TRIPS} and {MIN_NEW_AFTER_LOSS}).",
                "zh": f"{zh_label}：暂时无法检验，新交易 {sc['n_new']} 笔，其中亏损之后 {sc['n_new_after_loss']} 笔（需要 {MIN_NEW_TRIPS} 笔和 {MIN_NEW_AFTER_LOSS} 笔）。"}
    hv = {"CONFIRMED": ("habit prediction held", "习惯预测成立"), "MISSED": ("habit prediction missed", "习惯预测落空"), "NA": ("no habit was predicted", "没有做习惯预测")}[sc["habit"]]
    rv = {"CONFIRMED": ("the cap would have saved", "上限本可省下"), "MISSED": ("the cap would have lost", "上限本会亏掉"), "NA": ("no rule was predicted; the cap would have changed", "没有做规则预测；上限会改变")}[sc["rule"]]
    ratio = "" if sc["size_ratio_new"] is None else f" (after-loss size ratio {sc['size_ratio_new']} vs {sc['size_ratio_frozen']} frozen)"
    ratio_zh = "" if sc["size_ratio_new"] is None else f"（亏损后仓位比 {sc['size_ratio_new']}，冻结时为 {sc['size_ratio_frozen']}）"
    amt = _usd(abs(sc["effect"])) if sc["rule"] != "NA" else _usd(sc["effect"])
    return {"en": f"{en_label}: {sc['n_new']} new trips; {hv[0]}{ratio}; {rv[0]} {amt}, touching {sc['n_touched']} trades.",
            "zh": f"{zh_label}：新交易 {sc['n_new']} 笔；{hv[1]}{ratio_zh}；{rv[1]} {amt}，触及 {sc['n_touched']} 笔。"}
