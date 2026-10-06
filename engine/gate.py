"""Rule Gate: check an order IDEA against the owner's armed rules and checklist.

It never places, previews or routes an order. Output states:
CHECKS_PASSED, CHECKS_PASSED_WITH_NOTES, REVIEW_NEEDED (two independent evidence
items above their thresholds), BLOCKED_BY_YOUR_RULES (an armed rule is broken).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .checklist import Item, select_for_order
from .court import Rule

# thousands groups first ("1,000,000" is one million, not 1,000), then the older "1.5" / "1,5" form
AMOUNT = re.compile(r"(?<![\w.])(\$?)\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)\s*([kKmM万千]?)\s*((?:usdt|usd|u|美元|刀)(?![a-z]))?", re.I)
# "100 DOGE" / "3 BTC": a bare number straight before a ticker is a quantity of that coin, not dollars
QTY_AFTER = re.compile(r"\s*([A-Za-z]{2,10})(?![A-Za-z])")
MAX_NOTIONAL = 1e12                              # anything above is not an order size; never inf
STOP = {"system", "override", "now", "all", "me", "you", "please", "order", "ignore", "buy", "sell", "long", "short", "add", "usdt", "usd", "can", "the", "of", "in", "a", "to", "on", "my", "at", "worth", "u",
        "check", "order", "idea", "position", "and", "for", "with", "some", "more", "ok", "is", "it", "this", "that", "should", "i"}
SIDE_BUY = ("buy", "long", "add", "买", "買", "做多", "加仓", "加倉")
SIDE_SELL = ("sell", "short", "卖", "賣", "做空", "减仓", "減倉")
# "100x" / "100 x" / "x100" is leverage, never a dollar size
LEV_AFTER = re.compile(r"\s?[x×](?![A-Za-z])", re.I)
LEV_BEFORE = re.compile(r"(?<![0-9A-Za-z])[x×]\s?$", re.I)
CN_RUN = re.compile(r"[零〇一二两兩三四五六七八九十百千万萬]+")
CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def _cn_to_int(run: str) -> int | None:
    """Chinese numerals (simplified or traditional) like 一萬, 三万五千, 十万 to an int; None if it is not one."""
    if run[0] in "百千万萬" or not any(c in CN_DIGIT or c == "十" for c in run):
        return None
    total, section, num = 0, 0, None
    for c in run:
        if c in CN_DIGIT:
            num = CN_DIGIT[c]
        elif c in CN_UNIT:
            section += (1 if num is None else num) * CN_UNIT[c]
            num = None
        else:                                    # 万 / 萬
            section += num or 0
            total += (section or 1) * 10_000
            section, num = 0, None
    return total + section + (num or 0)


def _normalise_cn(text: str) -> str:
    def sub(m):
        v = _cn_to_int(m.group(0))
        return f" ${v} " if v is not None and len(m.group(0)) > 1 else m.group(0)   # "$": a spoken amount is money, not coin units
    return CN_RUN.sub(sub, text)


@dataclass
class OrderIdea:
    side: str | None
    symbol: str | None
    notional: float | None
    raw: str
    quantity: float | None = None              # units of the coin ("3 BTC"); needs a price to become a notional
    converted_from: str | None = None          # set by the caller when it turned a quantity into a notional


@dataclass
class GateResult:
    state: str
    reasons: list[str]
    checklist: list[dict]
    broken_rules: list[str] = field(default_factory=list)
    evidence_items: list[str] = field(default_factory=list)
    paper_only: bool = True


def parse_order(text: str) -> OrderIdea:
    t = _normalise_cn(text.strip())
    low = t.lower()
    side = "buy" if any(w in low for w in SIDE_BUY) else "sell" if any(w in low for w in SIDE_SELL) else None
    amt = None
    qty = None
    for m in AMOUNT.finditer(t):
        dollar, unit = bool(m.group(1)), bool(m.group(4))
        raw, suf = m.group(2).replace(",", ""), m.group(3).lower()
        try:
            v = float(raw)
        except ValueError:
            continue
        if LEV_AFTER.match(t, m.end()) or LEV_BEFORE.search(t[:m.start()]):
            continue                             # "BTC 100x": leverage, not a $100 size
        mult = {"k": 1e3, "千": 1e3, "m": 1e6, "万": 1e4}.get(suf, 1.0)
        if not math.isfinite(v * mult) or v * mult > MAX_NOTIONAL:
            continue                             # a 400-digit "size" is noise, not an order
        nxt = QTY_AFTER.match(t, m.end())
        if not dollar and not unit and not suf and nxt and nxt.group(1).lower() not in STOP and (nxt.group(1).isupper() or re.fullmatch(r"r[A-Z]{2,8}", nxt.group(1))):
            qty = v * mult                       # "buy 100 DOGE": units, never read as $100 (a k/m/万 suffix keeps the older reading: "9k NVDA" is dollars)
            break
        if v * mult >= 10:                       # ignore stray small numbers
            amt = v * mult
            break
    sym = None
    for tok in re.findall(r"[A-Za-z]{2,10}", t):
        if tok.lower() in STOP:
            continue
        if tok.isupper() or re.fullmatch(r"r[A-Z]{2,8}", tok):
            sym = tok.upper()
            break
    return OrderIdea(side, sym, amt, t, quantity=qty)


def check(idea: OrderIdea, armed: list[tuple[str, Rule]], items: list[Item], median_notional: float,
          last_trip_was_loss: bool, flagged: list[str], cost_line: dict | None = None) -> GateResult:
    reasons: list[str] = []
    broken: list[str] = []
    evidence: list[str] = []
    if idea.notional is None and idea.quantity is not None:
        return GateResult("COULD_NOT_CHECK", [f"You gave a quantity ({idea.quantity:g} {idea.symbol or 'units'}), not a dollar size, and I have no recent book price for "
                                              f"{idea.symbol or 'that symbol'} to convert it, so nothing was checked. Give the size in USDT, for example Buy $5k {idea.symbol or 'BTC'}."], [], [], [])
    if idea.notional is None and idea.symbol is None:
        return GateResult("COULD_NOT_CHECK", ["I could not read a symbol or an order size from that, so nothing was checked. Try: Buy $20k rNVDA."], [], [], [])
    if idea.notional is None:
        return GateResult("COULD_NOT_CHECK", ["I could not read a dollar order size from that (a number followed by x is leverage, not a size), so nothing was checked. "
                                              f"Give the size in USDT, for example Buy $5k {idea.symbol or 'BTC'}."], [], [], [])
    if idea.notional is None and armed:
        return GateResult("COULD_NOT_CHECK", ["A size rule is armed but I could not read an order size, so I cannot check this idea: tell me the size, for example Buy $5k rNVDA."], [], [], [])
    if idea.notional is None:
        reasons.append("I could not read an order size, so size rules were not checked.")
    else:
        for rid, r in armed:
            cap = r.value * median_notional
            if last_trip_was_loss and idea.notional > cap:
                broken.append(rid)
                evidence.append(f"armed rule {rid}")
                reasons.append(f"Rule {rid}: your last trade lost and this idea ({idea.notional:,.0f}) is above the cap ({cap:,.0f}).")
    if last_trip_was_loss and "size_after_loss" in flagged and idea.notional:
        evidence.append("flagged habit: size after a loss")
    if cost_line and cost_line.get("cost_bps") is not None and cost_line["cost_bps"] > cost_line.get("limit_bps", 30):
        evidence.append("execution cost above limit")
        reasons.append(f"Estimated execution cost is {cost_line['cost_bps']:.1f} bps on the live book.")
    shown = select_for_order(items, last_trip_was_loss)
    if broken:
        state = "BLOCKED_BY_YOUR_RULES"
    elif len(set(evidence)) >= 2:
        state = "REVIEW_NEEDED"
    elif evidence or reasons:
        state = "CHECKS_PASSED_WITH_NOTES"
    else:
        state = "CHECKS_PASSED"
    return GateResult(state, reasons, [{"id": i.item_id, "text": i.text} for i in shown], broken, sorted(set(evidence)))
