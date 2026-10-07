"""'What do my best trades have in common?': a computed, descriptive answer from the trips already loaded.
Top-10 trades by net P&L versus all trades, counted by symbol, side, weekday and opening hour (UTC).
No test, no p-value: with samples this small it is a description, not a tested habit."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

ASKED = re.compile(r"(best|top|winning|biggest win|most profitable|最好|最赚钱|赚钱最多|盈利最多|赢).{0,25}(in common|common|share|similar|pattern|traits?|characteristics|what do|共同|共通|相同|相似|特点|特征)"
                   r"|(in common|common|共同|共通|相同|相似|特点|特征).{0,25}(best|top|winning|最好|最赚钱|盈利最多)", re.I)
TOP_N = 10
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _dims(t):
    d = datetime.fromtimestamp(t.t_open_ms / 1000, tz=timezone.utc)
    return {"symbol": t.symbol, "side": str(t.side).lower(), "weekday": d.weekday(), "hour": d.hour}


def compute(trips) -> dict | None:
    if len(trips) < TOP_N:
        return None
    top = sorted(trips, key=lambda t: t.net_pnl, reverse=True)[:TOP_N]
    out = {"n": len(trips), "top_total": round(sum(t.net_pnl for t in top), 2), "dims": {}}
    for dim in ("symbol", "side", "weekday", "hour"):
        a = Counter(_dims(t)[dim] for t in top)
        b = Counter(_dims(t)[dim] for t in trips)
        out["dims"][dim] = [(k, c, b[k]) for k, c in sorted(a.items(), key=lambda kv: (-kv[1], str(kv[0])))[:3]]
    return out


def answer(trips, lang: str) -> dict:
    from engine.numberlock import NumberLockError, verify
    zh = lang == "zh"
    r = compute(trips)
    facts: dict[str, float] = {}
    if r is None:
        text = (f"你的记录只有 {len(trips)} 笔完整交易，不足 10 笔，所以我不总结最好交易的共同点。" if zh else
                f"Your record has only {len(trips)} complete trades, fewer than 10, so I will not summarise what the best ones share.")
        facts["n"] = len(trips)
    else:
        n = r["n"]
        facts.update(n=n, top_total=r["top_total"])

        def fmt(dim, k):
            if dim == "weekday":
                return (DAYS_ZH if zh else DAYS_EN)[k]
            if dim == "hour":
                facts[f"hour_{k}"] = k
                return f"{k} 时" if zh else f"hour {k}"
            if dim == "symbol":
                facts.update({f"sym_{x}": float(x) for x in re.findall(r"\d+", str(k))})
            return {"long": "多", "short": "空"}.get(k, k) if zh else k

        names = {"symbol": ("品种", "Symbols"), "side": ("方向", "Side"), "weekday": ("开仓星期", "Opening weekday"), "hour": ("开仓小时（UTC）", "Opening hour (UTC)")}
        parts = []
        for dim, rows in r["dims"].items():
            bits = []
            for k, c, tot in rows:
                facts[f"{dim}_{k}_top"], facts[f"{dim}_{k}_all"] = c, tot
                bits.append((f"{fmt(dim, k)}：最好 10 笔中 {c} 笔，全部 {n} 笔中 {tot} 笔" if zh else f"{fmt(dim, k)}: {c} of the best 10, {tot} of all {n}"))
            parts.append(f"{names[dim][0] if zh else names[dim][1]}：" + "；".join(bits) + "。" if zh else f"{names[dim][1]}: " + "; ".join(bits) + ".")
        head = (f"按净盈亏排名，最好的 10 笔合计 {r['top_total']:,.2f} USDT。下面对比它们和全部 {n} 笔的构成（每项只列最常见的三个）。" if zh else
                f"Your 10 best trades by net P&L add up to {r['top_total']:,.2f} USDT. Here is how they break down against all {n} trades (the three most common in each group).")
        tail = ("样本很小，这只是描述，不是经过检验的习惯，也不能说明因果。" if zh else
                "With samples this small this is descriptive, not a tested habit, and it does not show cause.")
        text = " ".join([head, *parts, tail])
    try:
        verify(text, [float(v) for v in facts.values()], allow=tuple(float(i) for i in range(0, 11)))
        lock = "passed"
    except NumberLockError as e:
        text, lock = (("这个回答包含无法由计算结果支持的数字，已被拒绝。" if zh else "That answer had a number I could not back with a computed fact, so I refused it."), f"refused: {e}")
    from . import llm
    return {"intent": "best_common", "lang": lang, "kind": "text", "text": text, "number_lock": lock, "llm": llm.label(),
            "facts": [{"fact": k, "value": v} for k, v in facts.items()],
            "interpreted": "最好交易的共同点（描述性）" if zh else "what the best trades share (descriptive)"}
