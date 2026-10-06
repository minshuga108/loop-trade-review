"""Weekly review report in the fupan (复盘) template, built only from computed facts.

Sections: what happened; the priority finding; what would make it wrong; what the
rule court did; tomorrow's plan; what changed since the last review. Numbers are
placeholders filled from the facts payload and checked by the number-lock.
"""
from __future__ import annotations

import json
import math
from statistics import NormalDist
from datetime import datetime, timezone
from pathlib import Path

from .numberlock import verify

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
DETECTOR_EN = {"size_after_loss": "opening size after a loss", "hold_asymmetry": "holding losers longer than winners",
               "overtrading_clusters": "trading more on your busiest days", "revenge_reentry": "re-entering the same symbol soon after a loss"}
DETECTOR_ZH = {"size_after_loss": "亏损后加大开仓", "hold_asymmetry": "亏损单比盈利单拿得更久",
               "overtrading_clusters": "最忙的那几天交易过多", "revenge_reentry": "亏损后很快在同一品种再次进场"}


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def facts_of(review: dict) -> dict:
    """Flat facts payload: key -> number. Everything the report may quote."""
    s, c = review["summary"], review["court"]
    f: dict[str, float] = {
        "trips": s["n_trips"], "wins": s["wins"], "losses": s["losses"], "net": s["net_pnl"],
        "win_rate_pct": round(100 * s["wins"] / max(s["n_trips"], 1), 1),
        "proposed": c["proposed"], "tested": c["tested"], "accepted": c["accepted"],
    }
    for x in review["findings"]:
        d = x["detector"]
        for k in ("ratio", "p", "p_adj", "n_a", "n_b"):
            if x.get(k) is not None:
                f[f"{d}.{k}"] = x[k]
        if x["status"] == "SUGGESTIVE" and (tn := trips_needed(x)):
            f[f"{d}.n_now"], f[f"{d}.n_needed"], f["alpha"] = tn["n_now"], tn["n_needed"], tn["alpha"]
        if x.get("ci"):
            f[f"{d}.lo"], f[f"{d}.hi"] = x["ci"]
    for i, v in enumerate(c["verdicts"], 1):
        f[f"rule{i}.multiple"] = v["multiple"]
        f[f"rule{i}.held_out"] = v["held_out_effect"]
        f[f"rule{i}.affected"], f[f"rule{i}.test_trips"] = v["affected"], v["test_trips"]
        if v["p"] is not None:
            f[f"rule{i}.p"] = v["p"]
        f[f"rule{i}.threshold"] = v["threshold"]
    return f


def trips_needed(x: dict) -> dict | None:
    """Rough projection for a SUGGESTIVE finding: how many trips in total would put its corrected p under 0.05 IF the same
    effect keeps showing up. Uses only the finding's own numbers: z = the normal score of its raw p, which grows with the
    square root of the sample; the bar is 0.05 divided by the correction factor (p_adj over p) the finding was held to.
    Returns None when those numbers cannot support the projection."""
    p, pa = x.get("p"), x.get("p_adj")
    if p is None or pa is None or not 0 < p < 1 or pa <= 0:
        return None
    k = pa / p                                    # the Holm multiplier this finding was held to (>= 1)
    if k < 1:
        return None
    nd = NormalDist()
    z_now, z_need = nd.inv_cdf(1 - p), nd.inv_cdf(1 - 0.05 / k)
    if z_now <= 0 or z_need <= 0:
        return None
    n_now = x["n_a"] + x["n_b"]
    return {"n_now": n_now, "n_needed": int(math.ceil(n_now * (z_need / z_now) ** 2)), "alpha": 0.05}


def build(review: dict, previous: dict | None = None, lang: str = "en") -> dict:
    s, c = review["summary"], review["court"]
    f = facts_of(review)
    det = DETECTOR_ZH if lang == "zh" else DETECTOR_EN
    flagged = [x for x in review["findings"] if x["status"] == "FLAGGED"]
    lines: list[str] = []
    zh = lang == "zh"
    lines.append(f"# {'复盘报告' if zh else 'Weekly review'}: wallet {review['trader']['id']}")
    lines.append(f"_{review['trader']['label']} ({review['trader']['provenance']})_")
    lines.append("")
    lines.append(f"## 1. {'发生了什么' if zh else 'What happened'}")
    if zh:
        lines.append(f"- {_day(s['first_ms'])} 至 {_day(s['last_ms'])}，共 {s['n_trips']} 笔完整交易，盈利 {s['wins']} 笔，亏损 {s['losses']} 笔，胜率 {f['win_rate_pct']}%。净盈亏 {s['net_pnl']:,.2f}（已扣手续费）。")
    else:
        lines.append(f"- {_day(s['first_ms'])} to {_day(s['last_ms'])}: {s['n_trips']} complete trades, {s['wins']} wins and {s['losses']} losses (win rate {f['win_rate_pct']}%). Net result {s['net_pnl']:,.2f} after fees.")
    lines.append("")
    lines.append(f"## 2. {'最重要的发现' if zh else 'Priority finding'}")
    if flagged:
        x = flagged[0]
        d = x["detector"]
        if zh:
            lines.append(f"- {det[d]}：差异 {x['ratio']}倍（范围 {x['ci'][0]} 到 {x['ci'][1]}，p={x['p']}，两组分别 {x['n_a']} 和 {x['n_b']} 笔）。这是数据里的模式，不是对人的评价。")
        else:
            lines.append(f"- {det[d].capitalize()}: {x['ratio']}x (range {x['ci'][0]} to {x['ci'][1]}, p={x['p']}, groups of {x['n_a']} and {x['n_b']} trades). This is a pattern in the data, not a judgement of the person.")
    elif any(x["status"] == "SUGGESTIVE" for x in review["findings"]):
        x = next(x for x in review["findings"] if x["status"] == "SUGGESTIVE")
        d = x["detector"]
        if zh:
            lines.append(f"- 有提示但经多重检验校正后不成立：{det[d]}，{x['ratio']}倍（p={x['p']}，校正后 p={x['p_adj']}）。不能当作已证实的习惯。")
        else:
            lines.append(f"- Suggestive, not proven: {det[d]}, {x['ratio']}x (p={x['p']}, adjusted p={x['p_adj']} after correcting for the habit tests run). It does not survive the correction, so it is not called a habit.")
    else:
        under = [x for x in review["findings"] if x["status"] == "UNDERPOWERED"]
        lines.append(("- 没有发现可以确认的习惯。" if zh else "- No habit was found that passes the test.") +
                     ((" 有些检查样本不足。" if zh else " Some checks do not have enough trades yet.") if under else ""))
    lines.append("")
    lines.append(f"## 3. {'什么情况下这个发现是错的' if zh else 'What would make this finding wrong'}")
    if flagged:
        x = flagged[0]
        if x["ci"][0] <= 1.0:
            lines.append((f"- 范围下限 {x['ci'][0]} 没有排除“没有这个习惯”的解释。" if zh else f"- The range reaches down to {x['ci'][0]}x, so a no-habit explanation is not ruled out."))
        lines.append(("- 如果只用最后三分之一的交易，差异消失，这个发现就不可靠。" if zh else "- If the gap disappears when only the most recent third of trades is used, the finding is not reliable."))
    elif any(x["status"] == "SUGGESTIVE" for x in review["findings"]):
        x = next(x for x in review["findings"] if x["status"] == "SUGGESTIVE")
        d, tn = x["detector"], trips_needed(x)
        if zh:
            lines.append(f"- 确认条件：校正后 p（现在 {x['p_adj']}）降到 0.05 以下。杀死条件：新增交易里差异回到 1.0 倍附近，校正后 p 就会继续升高。")
            lines.append((f"- 粗略估计：若同样的差异持续出现，总共约需 {tn['n_needed']} 笔交易（现在 {tn['n_now']} 笔）。这是按样本量的平方根外推，不是保证。" if tn else
                          "- 无法诚实地估算还需要多少笔交易（现有数字不足以外推）。"))
        else:
            lines.append(f"- What would confirm it: the adjusted p (now {x['p_adj']}) falling below 0.05. What would kill it: new trades where the gap goes back to about 1.0x, which pushes the adjusted p up instead.")
            lines.append((f"- Rough projection: if the same gap keeps showing up, about {tn['n_needed']} trades in total (now {tn['n_now']}) would be needed. This scales the current test score with the square root of the sample; it is a projection, not a promise, and noise would never get there." if tn else
                          "- I cannot honestly estimate how many more trades are needed from the numbers on hand, so no figure is given."))
    else:
        lines.append("- 没有需要反驳的发现。" if zh else "- There is no finding to disprove.")
    lines.append("")
    lines.append(f"## 4. {'规则法庭' if zh else 'Rule court'}")
    lines.append((f"- 提出 {c['proposed']} 条规则，测试 {c['tested']} 条，通过 {c['accepted']} 条。每条规则都计入，所以通过的门槛随尝试次数提高。" if zh else
                  f"- {c['proposed']} rules proposed, {c['tested']} tested, {c['accepted']} accepted. Every proposal is counted, so the bar rises with each rule tried."))
    for i, v in enumerate(c["verdicts"], 1):
        lines.append(f"  - {v['rule']}: **{v['status']}**, " + (f"未见过的交易上的效果 {v['held_out_effect']:,.0f}，触及 {v['affected']}/{v['test_trips']} 笔" if zh else
                     f"effect on unseen trades {v['held_out_effect']:,.0f}, touched {v['affected']} of {v['test_trips']} trades"))
    lines.append("")
    lines.append(f"## 5. {'明天的计划' if zh else 'Tomorrow\'s plan'}")
    acc = [v for v in c["verdicts"] if v["status"] == "ACCEPTED"]
    if acc:
        lines.append((f"- 有 {len(acc)} 条规则通过测试，等你确认后才会启用：{acc[0]['rule']}。" if zh else
                      f"- {len(acc)} rule(s) passed the test and wait for your click before arming: {acc[0]['rule']}."))
    else:
        lines.append("- 目前没有规则值得启用。继续记录交易；法庭至少需要 30 笔未见过的交易，其中规则触及至少 10 笔。" if zh else
                     "- No rule has earned arming. Keep logging trades; the court needs at least 30 unseen trades and a rule that touches at least 10 of them.")
    lines.append("")
    lines.append(f"## 6. {'与上次相比' if zh else 'What changed since the last review'}")
    if previous is None:
        lines.append("- 这是第一份报告，没有可比较的内容。" if zh else "- This is the first review, so there is nothing to compare yet.")
    else:
        pf = previous.get("facts", {})
        changes = [(k, pf[k], f[k]) for k in f if k in pf and pf[k] != f[k] and not k.endswith(".p")]
        if not changes:
            lines.append("- 没有变化。" if zh else "- Nothing changed.")
        for k, a, b in changes[:8]:
            lines.append(f"- {k}: {a} → {b}")
    lines.append("")
    lines.append(f"## 7. {'假设与缺失' if zh else 'Assumed and missing'}")
    if zh:
        lines.append("- 假设：基准大小取你自己的中位数；反事实按仓位大小线性缩放盈亏（缩小仓位不会让冲击变差）；手续费按成交记录。")
        lines.append("- 缺失：下单前的意图（没有事前记录）、交易时段、资金费率（此数据里没有）。所以没有计算意图差距或校准。")
    else:
        lines.append("- Assumed: the baseline size is your own median; counterfactuals scale profit and loss linearly with size (a smaller order cannot have worse impact); fees are as recorded in the fills.")
        lines.append("- Missing: your intent before each order (no pre-trade stamp exists), trading session, funding (not in this data). So no intent-gap or calibration figures are shown.")
    text = "\n".join(lines)
    import re
    checked = re.sub(r"\d{4}-\d{2}-\d{2}", "", text)          # dates are not claims
    prev_vals = list((previous or {}).get("facts", {}).values())          # old values quoted in the diff are facts too
    verify(checked, list(f.values()) + prev_vals, allow=tuple(float(i) for i in range(0, 11)) + (30.0, 10.0, 1.5, 2.0, 3.0))
    return {"markdown": text, "facts": f, "lang": lang}


def previous_snapshot(tid: str) -> dict | None:
    p = SNAP / f"{tid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_snapshot(tid: str, facts: dict) -> None:
    SNAP.mkdir(parents=True, exist_ok=True)
    (SNAP / f"{tid}.json").write_text(json.dumps({"facts": facts, "saved": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
