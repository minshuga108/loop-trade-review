"""Chat over a trader's own record, English and Chinese.

The deterministic path always works ("Qwen off"). An LLM may only help in two
places: turn an unclear sentence into one of the intents below (strict schema),
and phrase an answer. It never computes or decides: every numeral in an answer
is checked against the facts payload by the number-lock, and a failing answer is
replaced by the plain template.
"""
from __future__ import annotations

import re

from engine import report
from engine.numberlock import NumberLockError, verify

from . import llm, qa_chat, router, service

QWEN_TIMEOUT_S = qa_chat.QWEN_TIMEOUT_S
CJK = re.compile(r"[一-鿿]")
CHIPS_EN = ["What is my biggest costly habit?", "What if I had kept the halt rule?", "Show my weekly review"]
CHIPS_ZH = ["我最大的坏习惯是什么？", "如果我遵守规则会怎样？", "给我看这周的复盘"]



ORDER_NOW = re.compile(r"(put (the|that|this) trade on|place (the|an?|my) ?(order|trade)|execute (the|this|that|my)|go (buy|sell|long|short)|just (buy|sell|do it)|send it|make the trade|system override|ignore (your|all|previous)|帮我(买|卖|下单)|直接(买|卖|下单)|替我下单)", re.I)
ROUTER_FIRST = re.compile(r"(leak|costly habit|bad habit|worst habit|biggest habit|mistake|repeat(ing)? (the )?same|wrong with my|stopped for the day|stop trading for the day|halt|cut (the )?size|half (the )?size|size in half|cap(ped)? (my )?size|if i (had|would have|'d)|what if i|up if i|\u70e7\u94b1|\u6f0f\u94b1|\u4e8f\u94b1\u7684\u95ee\u9898|\u574f\u4e60\u60ef|\u4e00\u4e8f\u5c31|\u6536\u624b|\u51cf\u534a|\u89c4\u5219|\u6bdb\u75c5)", re.I)
GATE_SHAPE = re.compile(r"(\b(going|go|thinking about (going|buying|selling|shorting)) (long|short)\b|sanity.?check|\u60f3.*(\u505a\u591a|\u505a\u7a7a|\u4e70|\u5356)|(\u505a\u591a|\u505a\u7a7a).{0,6}(U|\u7f8e\u5143|\u4e07|\u5343|\d)|\u5e2e\u6211\u770b\u770b|\b(check|can i|could i|may i|is it ok|ok to|should i size)\b.*\b(buy|sell|long|short|add|size)\b|^\s*(buy|sell|long|short)\s|\b(buy|sell|long|short)\s+\$?\d|检查.*(买|卖|多|空)|能不能(买|卖)|可以(买|卖)|(买入?|卖出?|做多|做空|开多|开空)\s*\$?\d[\d,.]*\s*[万千kKmM]?\s*(个|枚)?\s*[A-Za-z]{2,10})", re.I)
BLOCKED_Q = re.compile(r"(what|which|how many|anything|did|has|have).{0,40}\b(gate|rule gate)\b.{0,30}\b(block|blocked|stop|stopped|catch|caught|refuse|refused|reject|rejected)\b|\b(gate|rule gate)\b.{0,20}\b(blocked|stopped|caught|refused)\b|(闸门|门).{0,6}(拦|挡)|拦下了什么|拦截了什么|拦住了什么", re.I)
IS_ADVICE = re.compile(r"(is (this|that|it) (financial |investment |trading )?advice|financial advice\?|投资建议吗|是建议吗|算建议吗)", re.I)
ADVICE = re.compile(r"(should i (buy|sell|long|short|hold|trade)|do you think i should|what should i (buy|sell|trade)|is (it|this) a good (buy|time|trade)|该买|该卖|要不要买|要不要卖|买入还是|值得买)", re.I)
FALSIFY = re.compile(r"(luck|lucky|by chance|disprove|prove (it )?wrong|could (this|that) be wrong|what would make (this|it|that) wrong|how sure|is it real|运气|会不会是|什么情况下.{0,4}错|可靠吗|真的吗|怎么才算错)", re.I)
DIFF = re.compile(r"(since (last|the last|my last)|what changed|changed since|compared (to|with) (last|before)|和上次|与上次|有什么变化|变化)", re.I)
NEXT_EN = {"habit": ["What would make this wrong?", "What if I had kept rule 2?", "Check an order idea: Buy $20k rNVDA"],
           "rule": ["Which rules were tested?", "Show my checklist", "What would make this wrong?"],
           "court": ["What is my biggest costly habit?", "Show my weekly review"],
           "report": ["What changed since my last review?", "Check an order idea: Buy $20k rNVDA"],
           "gate": ["Show my checklist", "What would make this wrong?"],
           "checklist": ["Check an order idea: Buy $20k rNVDA", "Show my weekly review"],
           "falsify": ["Which rules were tested?", "Show my weekly review"],
           "diff": ["Show my weekly review", "What is my biggest costly habit?"],
           "gate_log": ["Check an order idea: Buy $20k rNVDA", "Show my checklist"]}
NEXT_ZH = {"habit": ["什么情况下这个发现是错的？", "如果我遵守规则 2 会怎样？", "检查一个下单想法：买 2万 rNVDA"],
           "rule": ["哪些规则被测试过？", "给我看我的清单", "什么情况下这个发现是错的？"],
           "court": ["我最大的坏习惯是什么？", "给我看这周的复盘"],
           "report": ["和上次相比有什么变化？", "检查一个下单想法：买 2万 rNVDA"],
           "gate": ["给我看我的清单", "什么情况下这个发现是错的？"],
           "checklist": ["检查一个下单想法：买 2万 rNVDA", "给我看这周的复盘"],
           "falsify": ["哪些规则被测试过？", "给我看这周的复盘"],
           "diff": ["给我看这周的复盘", "我最大的坏习惯是什么？"],
           "gate_log": ["检查一个下单想法：买 2万 rNVDA", "给我看我的清单"]}
LABEL_EN = {"habit": "biggest habit", "rule": "what a rule would have changed", "court": "rule court results", "report": "weekly review",
            "source": "where the data comes from", "gate": "check an order idea", "checklist": "your checklist", "falsify": "what would make this wrong",
            "diff": "what changed since the last review", "gate_log": "what the gate blocked", "help": "not sure what you meant", "advice": "advice request (declined)"}
LABEL_ZH = {"habit": "最大的习惯", "rule": "规则会带来什么变化", "court": "规则法庭结果", "report": "周报", "source": "数据来源", "gate": "检查下单想法",
            "checklist": "你的清单", "falsify": "什么情况下会错", "diff": "与上次相比的变化", "gate_log": "闸门拦下了什么", "help": "没读懂", "advice": "买卖建议请求（已拒绝）"}

STATUS_ZH = {"ACCEPTED": "通过", "REJECTED": "未通过", "UNDERPOWERED": "样本不足"}
_RULE_ZH = [
    (re.compile(r"^cap opening size at ([\d.]+)x your median after a loss$"), r"亏损后开仓大小上限为你中位数的 \1 倍"),
    (re.compile(r"^cap opening size after a loss at ([\d.]+)x your median$"), r"亏损后把开仓大小限制在你中位数的 \1 倍"),
    (re.compile(r"^halt for the day after (\d+) consecutive losing trips$"), r"连续亏损 \1 笔后当天停手"),
    (re.compile(r"^cap at ([\d.]+)x median$"), r"上限为中位数的 \1 倍"),
]
# English reasons the Rule Gate and its checklist return, with their Chinese; anything unknown stays as the server wrote it.
_GATE_ZH = [
    (re.compile(r"^I could not read an order size, so size rules were not checked\.$"), "我没读到下单大小，所以没有检查大小规则。"),
    (re.compile(r"^Rule (\S+): your last trade lost and this idea \(([\d,]+)\) is above the cap \(([\d,]+)\)\.$"), r"规则 \1：你上一笔亏了，而这个想法（\2）超过了上限（\3）。"),
    (re.compile(r"^Estimated execution cost is ([\d.]+) bps on the live book\.$"), r"按实时订单簿估算，执行成本约 \1 个基点。"),
    (re.compile(r"^I could not read a symbol or an order size from that, so nothing was checked\. Try: (.*)$"), r"我没读到品种或下单大小，所以什么都没检查。试试：\1"),
    (re.compile(r"^I could not read a dollar order size from that \(a number followed by x is leverage, not a size\), so nothing was checked\. Give the size in USDT, for example (.*)\.$"),
     r"我没读到美元下单大小（数字后面跟 x 是杠杆，不是大小），所以什么都没检查。请用 USDT 给出大小，例如 \1。"),
    (re.compile(r"^A size rule is armed but I could not read an order size, so I cannot check this idea: tell me the size, for example (.*)\.$"),
     r"你启用了大小规则，但我没读到下单大小，所以无法检查这个想法：请告诉我大小，例如 \1。"),
    (re.compile(r"^Single order is within (\d+)% of visible depth within ([\d.]+) bps\.$"), r"单笔订单在 \2 个基点内可见深度的 \1% 以内。"),
    (re.compile(r"^Last trade lost: is this order bigger than your usual size\?$"), "上一笔亏损了：这笔订单是否比你平常的仓位更大？"),
    (re.compile(r"^Write the exit for a losing trade before you enter\.$"), "进场之前先写好亏损单的退出条件。"),
]


def rule_zh(text: str) -> str:
    for rx, rep in _RULE_ZH:
        if rx.match(text or ""):
            return rx.sub(rep, text)
    return text


def gate_zh(text: str) -> str:
    for rx, rep in _GATE_ZH:
        if rx.match(text or ""):
            return rx.sub(rep, text)
    return text


def detect_lang(text: str) -> str:
    return "zh" if CJK.search(text) else "en"


def route(text: str, previous_intent: str | None = None) -> str:
    return router.route(text, previous_intent)


def _facts_list(f: dict) -> list[float]:
    return [float(v) for v in f.values()]


def answer(tid: str, message: str, history: list[dict] | None = None, sid: str = "default") -> dict:
    out = _answer(tid, message, history, sid)
    try:
        out["receipt"] = receipt(out, tid)
    except Exception:                       # a receipt is only built from what the answer carries; no receipt beats an invented one
        out["receipt"] = None
    zh = out.get("lang") == "zh"
    out.setdefault("interpreted", (LABEL_ZH if zh else LABEL_EN).get(out.get("intent"), out.get("intent")))
    out.setdefault("next", (NEXT_ZH if zh else NEXT_EN).get(out.get("intent"), CHIPS_ZH if zh else CHIPS_EN))
    return out


def _answer(tid: str, message: str, history: list[dict] | None = None, sid: str = "default") -> dict:
    import time as _t
    t0 = _t.perf_counter()
    lang = detect_lang(message)
    zh = lang == "zh"
    prev = next((h.get("intent") for h in reversed(history or []) if h.get("intent")), None)
    if ORDER_NOW.search(message):
        text = ("我只复盘你的交易记录，不能下单，也不能在聊天里更改规则。要启用规则请点“Arm”，我只检查想法，不执行。" if zh else
                "I review your record. I can't place orders or change rules from chat. To arm a rule use the Arm button; I only check ideas, I never execute them.")
        return {"intent": "help", "lang": lang, "kind": "text", "text": text, "facts": [], "number_lock": "passed", "llm": llm.label(),
                "flags": ["order_request"], "interpreted": "order request (declined)", "next": (NEXT_ZH if zh else NEXT_EN)["checklist"],
                "steps": [{"name": "read question (safety check)", "ms": round((_t.perf_counter() - t0) * 1000, 2)}]}
    if ADVICE.search(message) or "advice" in router.safety_flags(router.normalise(message)):
        text = ("我不做买卖建议。我可以按你自己的规则检查一个下单想法，或展示你过去类似交易的结果。" if zh else
                "I don't give buy or sell advice. I can check an order idea against your own rules, or show how your own similar trades turned out.")
        return {"intent": "advice", "lang": lang, "kind": "text", "text": text, "facts": [], "number_lock": "passed", "llm": llm.label(),
                "next": (NEXT_ZH if zh else NEXT_EN)["checklist"], "steps": [{"name": "read question (keywords)", "ms": round((_t.perf_counter() - t0) * 1000, 2)}]}
    if IS_ADVICE.search(message):
        text = ("不是。Loop 只复盘你自己过去的交易，并按你自己的规则检查想法；它不会告诉你该买还是该卖。" if zh else "No. Loop reviews your own past trades and checks ideas against your own rules. It does not tell you what to buy or sell.")
        return {"intent": "help", "lang": lang, "kind": "text", "text": text, "facts": [], "number_lock": "passed", "llm": llm.label(), "interpreted": "is this advice (answered)", "next": (NEXT_ZH if zh else NEXT_EN)["checklist"]}
    if BLOCKED_Q.search(message):
        return _gate_log(tid, sid, lang)
    prev_plan = next((h.get("plan") for h in reversed(history or []) if h.get("plan")), None)
    if not FALSIFY.search(message) and not DIFF.search(message) and not GATE_SHAPE.search(message) and not ROUTER_FIRST.search(message):
        # the model is only for a sentence neither the typed QA parser nor the intent router can place; a routable one never waits on it
        q = qa_chat.answer_qa(tid, message, sid, previous_plan=prev_plan, allow_llm=router.route_ex(message, prev)[0] == "help")
        if q is not None:
            q.setdefault("llm", llm.label())
            return q
    forced = None
    if FALSIFY.search(message):
        forced = "falsify"
    elif DIFF.search(message):
        forced = "diff"
    intent, flags = router.route_ex(message, prev)
    if forced and not ({"injection", "order_request"} & set(flags)):
        intent = forced
    llm_note = llm.label()
    if intent == "help" and llm.enabled() and not qa_chat.timed_out():     # unclear sentence: Qwen may pick an intent, nothing more; one slow call is enough
        picked = qa_chat.with_deadline(lambda: llm.parse_intent(message, sid=sid, timeout=QWEN_TIMEOUT_S), QWEN_TIMEOUT_S + 0.4)
        if picked:
            intent = picked
    if flags and ("injection" in flags or "order_request" in flags):
        text = ("我只复盘你的交易记录，不能下单，也不能在聊天里更改规则。要启用规则请点“Arm”，我只检查想法，不执行。" if zh else
                "I review your record. I can't place orders or change rules from chat. To arm a rule use the Arm button; I only check ideas, I never execute them.")
        return {"intent": "help", "lang": lang, "kind": "text", "text": text, "facts": [], "number_lock": "passed", "llm": llm_note,
                "flags": flags, "chips": CHIPS_ZH if zh else CHIPS_EN}
    gate_seq = None
    gate_cl = None
    review = service.review(tid)
    f = report.facts_of(review)
    shown: list[dict] = []          # the facts behind this answer, for the click-through
    tog = None

    def use(*keys):
        for k in keys:
            if k in f:
                shown.append({"fact": k, "value": f[k]})

    if intent == "habit":
        flagged = [x for x in review["findings"] if x["status"] == "FLAGGED"]
        if flagged:
            x = flagged[0]
            d = x["detector"]
            name = (report.DETECTOR_ZH if zh else report.DETECTOR_EN)[d]
            use(f"{d}.ratio", f"{d}.lo", f"{d}.hi", f"{d}.p", f"{d}.n_a", f"{d}.n_b", "accepted", "tested")
            if zh:
                text = (f"数据里最明显的模式是“{name}”：差异 {x['ratio']}倍，范围 {x['ci'][0]} 到 {x['ci'][1]}，p={x['p']}（两组分别 {x['n_a']} 和 {x['n_b']} 笔）。"
                        f"我测试了 {review['court']['tested']} 条规则，未见过的交易上通过 {review['court']['accepted']} 条。这是模式，不是对你的评价。")
            else:
                text = (f"The clearest pattern is {name}: {x['ratio']}x, range {x['ci'][0]} to {x['ci'][1]}, p={x['p']} "
                        f"(groups of {x['n_a']} and {x['n_b']} trades). I tested {review['court']['tested']} rules on unseen trades and {review['court']['accepted']} passed. "
                        f"It is a pattern in the data, not a judgement of you.")
        elif any(x["status"] == "SUGGESTIVE" for x in review["findings"]):
            x = next(x for x in review["findings"] if x["status"] == "SUGGESTIVE")
            d = x["detector"]
            name = (report.DETECTOR_ZH if zh else report.DETECTOR_EN)[d]
            use(f"{d}.ratio", f"{d}.p", f"{d}.p_adj")
            text = (f"最接近的模式是“{name}”：{x['ratio']}倍，p={x['p']}，但校正多重检验后 p={x['p_adj']}，所以不能说它已被证实。" if zh else
                    f"The closest pattern is {name}: {x['ratio']}x, p={x['p']}, but after correcting for the several habit tests run the adjusted p is {x['p_adj']}, so I do not call it proven.")
        else:
            under = any(x["status"] == "UNDERPOWERED" for x in review["findings"])
            text = (("目前没有哪个习惯通过检验" + ("，有些检查样本还不够。" if under else "。")) if zh else
                    ("No habit passes the test right now" + (", and some checks do not have enough trades yet." if under else ".")))
    elif intent == "rule":
        m = re.search(r"(?:rule|规则)\s*#?\s*(\d)", message.lower())
        n = int(m.group(1)) if m else None
        verdicts = review["court"]["verdicts"]
        if n and 1 <= n <= len(verdicts):
            v = verdicts[n - 1]
            use(f"rule{n}.held_out", f"rule{n}.affected", f"rule{n}.test_trips")
            text = (f"规则 {n}：{rule_zh(v['rule'])}。在未见过的交易上效果 {v['held_out_effect']:,.0f} USDT，触及 {v['affected']} / {v['test_trips']} 笔，结论 {STATUS_ZH.get(v['status'], v['status'])}。" if zh else
                    f"Rule {n}: {v['rule']}. On trades it never saw the effect is {v['held_out_effect']:,.0f} USDT, touching {v['affected']} of {v['test_trips']}; verdict {v['status']}.")
        else:
            tog = service.toggle(tid, "halt")
            f["halt.in"], f["halt.out"] = round(tog["in_sample"]["effect"]), round(tog["held_out"]["effect"])
            f["halt.skipped_in"], f["halt.skipped_out"] = tog["in_sample"]["n_skipped"], tog["held_out"]["n_skipped"]
            use("halt.in", "halt.out", "halt.skipped_in", "halt.skipped_out")
            text = (f"规则“{rule_zh(tog['rule'])}”：在用来建立它的交易上效果 {f['halt.in']:,} USDT（跳过 {f['halt.skipped_in']} 笔），在没见过的交易上效果 {f['halt.out']:,} USDT（跳过 {f['halt.skipped_out']} 笔）。结论 {STATUS_ZH.get(tog['status'], tog['status'])}。" if zh else
                    f"Rule \"{tog['rule']}\": on the trades it was built from the effect is {f['halt.in']:,} USDT ({f['halt.skipped_in']} trips skipped); on trades it never saw it is {f['halt.out']:,} USDT ({f['halt.skipped_out']} skipped). Verdict {tog['status']}.")
    elif intent == "falsify":
        flagged = [x for x in review["findings"] if x["status"] == "FLAGGED"]
        c = review["court"]
        if not flagged:
            text = ("现在没有通过检验的发现，所以没有需要反驳的结论。" if zh else "No finding passes the test right now, so there is nothing to disprove.")
        else:
            x = flagged[0]
            d = x["detector"]
            use(f"{d}.lo", f"{d}.hi", "proposed", "accepted")
            ok_range = x["ci"][0] > 1.0
            checks = []
            checks.append((f"范围 {x['ci'][0]} 到 {x['ci'][1]}：" + ("下限高于 1，通过" if ok_range else "下限没有高于 1，不能排除没有这个习惯")) if zh else
                          (f"range {x['ci'][0]} to {x['ci'][1]}: " + ("the lower end stays above 1 (pass)" if ok_range else "the lower end does not clear 1, so a no-habit explanation is not ruled out")))
            checks.append((f"我提出了 {c['proposed']} 条规则，未见过的交易上通过 {c['accepted']} 条" if zh else f"{c['proposed']} rules were tried and {c['accepted']} passed on unseen trades"))
            text = (("三项检查：" if zh else "Three checks: ") + "；".join(checks) if zh else "Checks: " + "; ".join(checks)) + \
                   ("。没有测试：市场环境和品种构成。" if zh else ". Not tested: market regime and symbol mix.")
    elif intent == "diff":
        key = f"{sid}-{tid}"
        prevsnap = report.previous_snapshot(key)
        r = report.build(review, prevsnap, lang)
        sect = re.split(r"(?m)^## 7\.", r["markdown"].split("## 6.")[-1])[0]        # only the "what changed" section, never the next heading
        lines = [ln.strip("- ").strip() for ln in sect.splitlines()[1:] if ln.strip() and not ln.lstrip().startswith("#")]
        text = (" ".join(lines) if lines else ("没有变化。" if zh else "Nothing changed."))
        report.save_snapshot(key, r["facts"])
    elif intent == "gate":
        g = service.gate_check(sid, tid, re.sub(r"(?<=[一-鿿])(?=\d)", " ", message))
        idea = g["idea"]
        if not idea.get("notional"):
            qty = idea.get("quantity")
            if qty:
                sym = idea.get("symbol") or "?"
                ask_text = (f"我读到的是 {qty:g} 个 {sym}（数量，不是美元），但现在没有可用的价格来换算成 USDT，所以我没有猜，也没有检查。请用 USDT 给出大小，例如 买 $200 {sym}。" if zh else
                            f"I read {qty:g} {sym} (units, not dollars) but have no recent price to convert that to USDT, so I did not guess and nothing was checked. Give the size in USDT, for example Buy $200 {sym}.")
            else:
                ask_text = "多大的仓位？请告诉我下单金额，例如 5000 USDT。" if zh else "What size? Tell me the order size, for example 5000 USDT."
            return {"intent": "gate", "lang": lang, "kind": "text", "number_lock": "passed", "llm": llm_note, "facts": [], "record_seq": g.get("record_seq"),
                    "text": ask_text,
                    "next": ["Buy $5k rNVDA", "Buy $20k rNVDA"] if not zh else ["买 5000 rNVDA", "买 2万 rNVDA"]}
        nums = [x for x in (idea.get("notional"),) if x] + list(g.get("numbers", []))
        for i, v in enumerate(nums):
            f[f"gate.n{i}"] = v
        states = {"CHECKS_PASSED": ("检查通过", "checks passed"), "CHECKS_PASSED_WITH_NOTES": ("通过，但有提示", "passed with notes"),
                  "REVIEW_NEEDED": ("需要复核", "review needed"), "COULD_NOT_CHECK": ("无法检查", "could not check"), "BLOCKED_BY_YOUR_RULES": ("被你自己的规则拦下", "blocked by your own rules")}[g["state"]]
        size = f"{idea['notional']:,.0f} USDT" if idea.get("notional") else ("?" if not zh else "未读到")
        head = (f"我把这个想法读作：{idea.get('side') or '?'} {idea.get('symbol') or '?'}，约 {size}。结果：{states[0]}。" if zh else
                f"I read this idea as {idea.get('side') or '?'} {idea.get('symbol') or '?'}, about {size}. Result: {states[1]}.")
        parts = [head] + ([gate_zh(x) for x in g["reasons"]] if zh else g["reasons"])
        cl = g.get("check_line") or {}
        if cl.get("available") and cl.get("stale"):
            f["gate.age"] = cl["cache_age_s"]
            parts.append((f"最近的盘口是 {cl['cache_age_s']} 秒前的（已过期），所以没有使用成本估算。" if zh else
                          f"The last book snapshot is {cl['cache_age_s']} seconds old (stale), so no cost estimate is used."))
        elif cl.get("available") and cl.get("cost_bps") is not None:
            f["gate.cost"] = round(cl["cost_bps"], 1)
            parts.append((f"实时盘口估算成本 {cl['cost_bps']:.1f} 个基点（缓存 {cl['cache_age_s']} 秒前）。" if zh else
                          f"Estimated cost on the live book: {cl['cost_bps']:.1f} bps (cache {cl['cache_age_s']} seconds old)."))
            f["gate.age"] = cl["cache_age_s"]
        elif cl:
            parts.append("没有最新盘口，所以没有成本估算。" if zh else "No recent book, so no cost estimate.")
        if g["checklist"]:
            parts.append(("清单：" if zh else "Checklist: ") + " / ".join((gate_zh(i["text"]) if zh else i["text"]) for i in g["checklist"]))
        text = " ".join(parts)
        shown = [{"fact": k, "value": v} for k, v in f.items() if k.startswith("gate.")]
        gate_seq = g.get("record_seq")
        gate_cl = cl
    elif intent == "checklist":
        b = service.rulebook_view(sid, tid)
        if b["checklist"]:
            text = ("你的清单：" if zh else "Your checklist: ") + " / ".join((gate_zh(i["text"]) if zh else i["text"]) for i in b["checklist"][:3])
        else:
            text = ("现在还没有清单项目：它们来自通过检验的习惯和你启用的规则。" if zh else
                    "No checklist items yet: they come from habits that pass the test and from rules you arm.")
    elif intent == "court":
        c = review["court"]
        use("proposed", "tested", "accepted")
        text = (f"规则法庭：提出 {c['proposed']} 条，测试 {c['tested']} 条，通过 {c['accepted']} 条。每条提案都被计数，所以通过的门槛随尝试次数提高。" if zh else
                f"Rule court: {c['proposed']} proposed, {c['tested']} tested, {c['accepted']} accepted. Every proposal is counted, so the bar rises with each rule tried.")
    elif intent == "report":
        key = f"{sid}-{tid}"
        r = report.build(review, report.previous_snapshot(key), lang)
        report.save_snapshot(key, r["facts"])
        return {"intent": intent, "lang": lang, "kind": "report", "markdown": r["markdown"], "text": "", "facts": [],
                "number_lock": "passed", "llm": llm_note, "chips": CHIPS_ZH if zh else CHIPS_EN}
    elif intent == "source":
        tr = review["trader"]
        text = (f"这是{tr['label']}（来源标签 {tr['provenance']}）。页面上每个数字都是加载时由成交记录计算的。" if zh else
                f"{tr['label']} Provenance label: {tr['provenance']}. Every number on this page is computed from fills when it loads.")
    else:
        text = ("我没能读懂这个问题。我可以回答：最大的习惯是什么、某条规则如果执行会怎样、规则法庭的结果、周报，以及数据来源。" if zh else
                "I could not parse that as a question about your record, so I computed nothing. I can answer: what the biggest habit is, what a rule would have changed, what the rule court did, a weekly review, and where the data comes from.")
    try:
        verify(text, _facts_list(f), allow=tuple(float(i) for i in range(0, 11)))
        lock = "passed"
    except NumberLockError as e:       # a number without a fact: refuse, fall back to the plain line
        text, lock = ("这个回答包含无法由计算结果支持的数字，已被拒绝。" if zh else "That answer had a number I could not back with a computed fact, so I refused it."), f"refused: {e}"
    return {"intent": intent, "lang": lang, "kind": "text", "text": text, "facts": shown, "number_lock": lock,
            "llm": llm_note, "record_seq": gate_seq, "book_line": gate_cl, "chips": CHIPS_ZH if zh else CHIPS_EN,
            "steps": [{"name": "读取问题" if zh else "read question", "ms": 0.1},
                      {"name": f"载入 {review['summary']['n_trips']} 个完整交易" if zh else f"loaded {review['summary']['n_trips']} round trips", "ms": round((_t.perf_counter() - t0) * 1000, 1)},
                      {"name": f"数字锁：每个数字都有依据（{"通过" if lock == "passed" else lock}）" if zh else f"number-lock: every number backed ({lock})", "ms": 0.1}]}


# ---------------------------------------------------------------- receipt, gate log, verdict banner
_COMPUTE_EN = {"habit": "habit detectors (tested within this trader, corrected for several tests)", "falsify": "habit detectors and rule court counts",
               "rule": "rule replay on trades the rule never saw", "court": "rule court counts", "report": "weekly report build and snapshot diff",
               "diff": "report snapshot diff", "gate": "Rule Gate check against your armed rules", "checklist": "rulebook checklist",
               "source": "provenance label of the loaded record", "gate_log": "public record scan (gate decisions)"}
_COMPUTE_ZH = {"habit": "习惯检测（只在这位交易者自己的数据里检验，并校正多重检验）", "falsify": "习惯检测与规则法庭计数", "rule": "规则在未见交易上的回放", "court": "规则法庭计数",
               "report": "周报生成与快照对比", "diff": "报告快照对比", "gate": "按你已启用的规则做闸门检查", "checklist": "规则手册清单", "source": "已载入记录的来源标签",
               "gate_log": "公开记录中的闸门决定扫描"}
_PROV_EN = {"REAL_PLATFORM_PUBLIC": "real public data", "REAL_OWN": "your own data as imported", "SIM_PLANTED": "simulated", "SIM_PAPER": "paper", "REPLAY_NATIVE": "recorded Bitget book"}
_PROV_ZH = {"REAL_PLATFORM_PUBLIC": "真实公开数据", "REAL_OWN": "你自己导入的数据", "SIM_PLANTED": "模拟数据", "SIM_PAPER": "纸面交易", "REPLAY_NATIVE": "录制的 Bitget 订单簿"}


def receipt(out: dict, tid: str) -> dict:
    """What stands behind an answer, built only from fields the answer or the cached review already carries.
    A missing field is reported as missing, never filled in."""
    zh = out.get("lang") == "zh"
    intent = out.get("intent")
    rv = service.review(tid)
    tr = rv["trader"]
    prov = (_PROV_ZH if zh else _PROV_EN).get(tr.get("provenance"), tr.get("provenance"))
    who = (f"{'钱包' if zh else 'Wallet'} {tr.get('id')}" if tr.get("role") != "import" else ("你的导入" if zh else "Your import"))
    sources = [f"{who}: {'成交记录' if zh else 'fills'} ({prov})"]
    comps: list[str] = []
    rows = None
    comp = out.get("computed") or {}
    plan = out.get("plan")
    if intent == "qa" and plan:
        parts = [str(plan.get("metric"))]
        if plan.get("group_by"):
            parts.append("by " + str(plan["group_by"]))
        if plan.get("filters"):
            parts.append("filters " + ", ".join(f"{k}={v}" for k, v in plan["filters"].items()))
        comps.append(("数据查询: " if zh else "data query: ") + " / ".join(parts))
        if comp.get("n") is not None:
            rows = {"used": comp.get("n"), "of": comp.get("n_total")}
        if comp.get("window"):
            sources.append(("时间范围: " if zh else "window: ") + str(comp["window"]))
        if comp.get("method"):
            comps.append(("方法: " if zh else "method: ") + str(comp["method"]))
    elif intent == "qa":
        comps.append("数据查询（没有计算）" if zh else "data question (nothing computed)")
    else:
        c = (_COMPUTE_ZH if zh else _COMPUTE_EN).get(intent)
        if c:
            comps.append(c)
        rows = {"used": rv["summary"]["n_trips"], "of": rv["summary"]["n_trips"]}
    bl = out.get("book_line") or {}
    if intent == "gate" and bl.get("available") and bl.get("cost_bps") is not None:
        sources.append(("Bitget 公开订单簿（缓存 " if zh else "Bitget public order book (cached ") + f"{bl.get('cache_age_s')}" + (" 秒）" if zh else " s)"))
    seq = out.get("record_seq")
    if seq:
        ledger = {"seq": seq, "note": ("已写入公开记录，序号 " if zh else "written to the public record as entry #") + str(seq)}
    else:
        ledger = {"seq": None, "note": ("只读问题不写入公开记录" if zh else "a read-only question is not written to the public record")}
    return {"sources": sources, "computations": comps, "rows": rows, "ledger": ledger,
            "trace": [x.get("name") for x in (out.get("steps") or [])], "number_lock": out.get("number_lock"),
            "facts": len(out.get("facts") or []), "intent": intent, "trader": tid}


def _gate_log(tid: str, sid: str, lang: str) -> dict:
    """'What did the gate block?': read straight from the public record, split into this session and everyone."""
    from . import record_api
    zh = lang == "zh"
    log = record_api.get_log()
    mine = log.session_hash(sid)
    ent = [e for e in log.entries() if e.get("kind") == "gate_decision"]
    allb = [e for e in ent if e["payload"].get("state") == "BLOCKED_BY_YOUR_RULES"]
    me = [e for e in ent if e["payload"].get("session") == mine]
    meb = [e for e in me if e["payload"].get("state") == "BLOCKED_BY_YOUR_RULES"]
    armed = len(service.book(sid, tid).active_rules())
    facts = {"session_checked": len(me), "session_blocked": len(meb), "record_decisions": len(ent), "record_blocked": len(allb), "armed_rules": armed}
    if zh:
        text = (f"本次会话里闸门检查了 {len(me)} 个下单想法，被你自己的规则拦下 {len(meb)} 个。公开记录里共有 {len(ent)} 条闸门决定，其中 {len(allb)} 条被规则拦下。"
                + ("你现在还没有启用规则，所以闸门暂时拦不下任何东西：先在下面的规则手册里启用一条通过检验的规则。" if not armed else f"你当前启用了 {armed} 条规则。"))
    else:
        text = (f"In this session the gate checked {len(me)} order ideas and your own rules blocked {len(meb)}. The public record holds {len(ent)} gate decisions, {len(allb)} of them blocked by a rule. "
                + ("You have no rule armed, so the gate cannot block anything yet: arm a rule that passed the court in the rulebook below." if not armed else f"You have {armed} rules armed."))
    lock = "passed"
    try:
        verify(text, [float(v) for v in facts.values()], allow=tuple(float(i) for i in range(0, 11)))
    except NumberLockError as e:
        text, lock = ("这个回答包含无法由计算结果支持的数字，已被拒绝。" if zh else "That answer had a number I could not back with a computed fact, so I refused it."), f"refused: {e}"
    return {"intent": "gate_log", "lang": lang, "kind": "text", "text": text, "facts": [{"fact": k, "value": v} for k, v in facts.items()],
            "number_lock": lock, "llm": llm.label(), "chips": CHIPS_ZH if zh else CHIPS_EN,
            "steps": [{"name": "扫描公开记录" if zh else "scanned the public record", "ms": 0.1}]}


def verdict_banner(tid: str, review: dict | None = None) -> dict:
    """One sentence per language, built from the review dict (engine state). Rendered on the server before any script runs."""
    rv = review or service.review(tid)
    h = rv["headline"]
    x = h.get("finding") or h.get("suggestive")
    p = h["priced"]
    st = p["status"]

    def usd(v):
        return ("-$" if v < 0 else "+$") + f"{abs(round(v)):,}"
    out = {}
    for lg in ("en", "zh"):
        z = lg == "zh"
        det = report.DETECTOR_ZH if z else report.DETECTOR_EN
        if h.get("finding"):
            a = (f"你最贵的习惯是“{det[x['detector']]}”（{x['ratio']:.2f} 倍）" if z else f"Your costliest habit is {det[x['detector']]} ({x['ratio']:.2f}x)")
        elif x:
            a = (f"最接近的模式是“{det[x['detector']]}”（{x['ratio']:.2f} 倍），但校正后还不能称为习惯" if z else
                 f"The closest pattern is {det[x['detector']]} ({x['ratio']:.2f}x), suggestive and not proven")
        else:
            a = "没有习惯通过检验" if z else "No habit passes the test"
        if st == "ACCEPTED":
            b = (f"针对它的上限规则在没见过的交易上通过了检验（{usd(p['held_out_effect'])}），可以启用" if z else
                 f"the cap rule was tested on trades it never saw and passed ({usd(p['held_out_effect'])}), so you can arm it")
        elif st == "REJECTED":
            b = (f"针对它的规则在没见过的交易上被拒绝（{usd(p['held_out_effect'])}），所以没有启用任何规则" if z else
                 f"a rule for it was tested on trades it never saw and rejected ({usd(p['held_out_effect'])}), so nothing is armed")
        else:
            b = ("交易还不够，暂时无法判断规则，所以没有启用任何规则" if z else "there are not enough trades to judge a rule yet, so nothing is armed")
        out[lg] = f"{a}；{b}。" if z else f"{a}; {b}."
    out["status"] = st
    out["accepted_rules"] = h["court"]["accepted"]
    out["trader"] = tid
    return out
