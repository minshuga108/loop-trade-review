"""Review service: turns a trader's history into the JSON the first screen shows.

Every number is computed here from fills; the browser only draws it. Provenance
and the honest "hand-picked, illustrative" label travel with every response.
"""
from __future__ import annotations

import math
import os
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi.responses import JSONResponse

from adapters import bitget_csv_en, bitget_v2_history, hyperliquid_csv
from collections import OrderedDict

from engine import checklist as checklist_mod
from engine.stats import holm
from engine import detectors, detectors2, gate as gate_mod, halt, ledger, winrate
from engine.rulebook import Rulebook

from engine.walkforward import judge_wf

from . import costs, record_api
from engine.court import Court, Rule, price_rule
from engine.planted import planted_trader

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "trader_samples"
SHIPPED_BITGET = Path(__file__).resolve().parents[1] / "deploy_data" / "real_bitget"
SHIPPED_JOURNAL = Path(__file__).resolve().parents[1] / "deploy_data" / "real_bitget_journal" / "journal_verified.json"
SHIPPED = Path(__file__).resolve().parents[1] / "deploy_data" / "trader_samples"      # anonymised copies named wallet_A.csv ...

# Public wallets with enough trips to say something. Addresses are withheld in the UI
# (alias only); the control trader comes first as the honesty proof.
TRADERS = [
    {"id": "A", "file": "wallet_A.csv", "role": "control", "blurb": "Stock-perp trader the engine should leave alone"},
    {"id": "B", "file": "wallet_B.csv", "role": "candidate", "blurb": "Sizes up after losses: suggestive, not proven"},
    {"id": "C", "file": "wallet_C.csv", "role": "candidate", "blurb": "Suggestive size pattern, not proven"},
    {"id": "D", "file": "wallet_D.csv", "role": "disciplined", "blurb": "Long, steady history"},
    {"id": "E", "file": "wallet_E.csv", "role": "candidate", "blurb": "No size or hold habit found"},
    {"id": "G", "file": "bitget_csv:doge_trades_analysis.csv", "role": "real_bitget", "blurb": "A REAL Bitget futures export (public, a trading bot's DOGE trades), read by our Bitget CSV importer"},
    {"id": "F", "file": None, "role": "planted", "blurb": "SIMULATED trader built to have a costly habit: shows the court's accept path"},
]
# Optional demo trader H: off unless LOOP_ENABLE_JOURNAL=1 is set when the process starts, so the default picker,
# claims and tests are unchanged. Appended after the literal on purpose (scripts/prepare_samples.py reads the literal).
if os.environ.get("LOOP_ENABLE_JOURNAL") == "1":
    TRADERS.append({"id": "H", "file": "journal:journal_verified.json", "role": "real_journal",
                    "blurb": "Real Bitget futures positions from a public journal (53 verified trades, underpowered)"})
LABEL = "Public Hyperliquid wallet, hand-picked, illustrative. Not a Bitget user and not the owner's account."
LABEL_BITGET = ("Real Bitget futures export (website CSV) published publicly by its owner (GPL-3.0 data, a trading bot's account, not the owner's). "
                "This export format omits opening fees, so net results overstate by them.")
LABEL_JOURNAL = ("Real Bitget futures positions from a public MPL-2.0 journal, pseudonymised; 53 verified trades, "
                 "below the 150 where tests have decent power; consent pending")
LABEL_IMPORT = "Your own import, parsed in this session only and not stored."
LABEL_PLANTED = "SIMULATED trader, built on purpose with a costly habit to show what an accepted rule looks like. Not a real person."


def json_safe(x):
    """Copy of x with every NaN / +-Inf float replaced by None (JSON has no such numbers)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_safe(v) for v in x]
    return x


def _r(x, nd: int):
    """round() that returns None for a missing or non-finite number."""
    try:
        return round(float(x), nd) if x is not None and math.isfinite(float(x)) else None
    except (TypeError, ValueError):
        return None


class SafeJSONResponse(JSONResponse):
    """Global safeguard: a NaN or Infinity anywhere in a payload becomes null instead of a 500."""

    def render(self, content) -> bytes:
        return super().render(json_safe(content))


class DataMissing(LookupError):
    """A demo history is not shipped in this build, or cannot be read. Routes answer 503 with this text."""


@lru_cache(maxsize=16)
def _load_static(tid: str):
    meta = next(t for t in TRADERS if t["id"] == tid)
    if meta["file"] is None:
        return meta, [], [], planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=2)
    if str(meta["file"]).startswith("journal:"):
        if not SHIPPED_JOURNAL.exists():
            raise DataMissing("The real Bitget journal is not in this build, so it cannot be reviewed here.")
        try:
            trips, _notes = bitget_v2_history.load(SHIPPED_JOURNAL)
        except (OSError, ValueError, LookupError) as e:
            raise DataMissing(f"The Bitget journal could not be read ({type(e).__name__}).") from None
        return meta, [], [], trips
    if str(meta["file"]).startswith("bitget_csv:"):
        path = SHIPPED_BITGET / str(meta["file"]).split(":", 1)[1]
        if not path.exists():
            raise DataMissing("The real Bitget export is not in this build, so it cannot be reviewed here.")
        try:
            fills, notes = bitget_csv_en.parse(path, account="bitget-export")
        except (OSError, ValueError) as e:
            raise DataMissing(f"The Bitget export could not be read ({type(e).__name__}).") from None
        fills = ledger.dedupe(fills)
        return meta, fills, ledger.to_orders(fills), ledger.to_round_trips(fills)
    shipped = SHIPPED / f"wallet_{tid}.csv"
    path = shipped if shipped.exists() else SAMPLES / meta["file"]
    if not path.exists():
        raise DataMissing(f"The history for wallet {tid} is not in this build, so it cannot be reviewed here.")
    try:
        fills = ledger.dedupe(hyperliquid_csv.load(path, account=f"wallet-{tid}"))
    except (OSError, ValueError) as e:
        raise DataMissing(f"The history for wallet {tid} could not be read ({type(e).__name__}); nothing is shown for it.") from None
    if not fills:
        raise DataMissing(f"The history for wallet {tid} could not be read (no fills); nothing is shown for it.")
    return meta, fills, ledger.to_orders(fills), ledger.to_round_trips(fills)


_DYN: dict = {}            # tid -> (meta, fills, orders, trips) for imports; tid -> owner session in _DYN_OWNER
_DYN_OWNER: dict[str, str] = {}
MAX_DYN, MAX_PER_SESSION = 200, 3


def _load(tid: str):
    if tid in _DYN:
        return _DYN[tid]
    return _load_static(tid)


_load.cache_clear = _load_static.cache_clear                     # tests and callers clear the static cache this way


def register_import(sid: str, fills, label_note: str = "") -> dict:
    """Keep a visitor's own import for this session only (memory, never written to disk)."""
    import hashlib
    fills = ledger.dedupe(fills)
    trips = ledger.to_round_trips(fills)
    if len(trips) < 5:
        raise ValueError(f"only {len(trips)} complete round trips were found; at least 5 are needed to review anything")
    tid = "U" + hashlib.sha256((sid + str(len(fills)) + str(fills[0].t_ms)).encode()).hexdigest()[:6]
    mine = [k for k, v in _DYN_OWNER.items() if v == sid]
    while len(mine) >= MAX_PER_SESSION:
        old = mine.pop(0)
        _DYN.pop(old, None); _DYN_OWNER.pop(old, None); _REVIEW_CACHE.pop(old, None)
    meta = {"id": tid, "file": "import", "role": "import", "blurb": "Your import (this session only)"}
    _DYN[tid] = (meta, fills, ledger.to_orders(fills), trips)
    _DYN_OWNER[tid] = sid
    while len(_DYN) > MAX_DYN:
        old = next(iter(_DYN)); _DYN.pop(old, None); _DYN_OWNER.pop(old, None); _REVIEW_CACHE.pop(old, None)
    return {"id": tid, "n_fills": len(fills), "n_trips": len(trips), "label": LABEL_IMPORT, "notes": label_note}


def _curve(trips, skip=None):
    """Cumulative net pnl by trip close time; with `skip`, the counterfactual curve."""
    ts = sorted(range(len(trips)), key=lambda i: trips[i].t_close_ms)
    cum, pts = 0.0, []
    for i in ts:
        if skip is None or not skip[i]:
            cum += trips[i].net_pnl
        pts.append([trips[i].t_close_ms, round(cum, 2)])
    return pts


def _prov(meta, fills) -> str:
    if meta.get("role") == "real_journal":
        return "REAL_PLATFORM_PUBLIC"
    return "SIM_PLANTED" if meta["file"] is None else fills[0].provenance.value


def _label(meta) -> str:
    if meta.get("role") == "real_bitget":
        return LABEL_BITGET
    if meta.get("role") == "real_journal":
        return LABEL_JOURNAL
    if meta.get("role") == "import":
        return LABEL_IMPORT
    return LABEL_PLANTED if meta["file"] is None else LABEL


def traders(sid: str | None = None) -> list[dict]:
    out = []
    mine = [{"id": k, "role": "import", "blurb": "Your import (this session only)", "file": "import"} for k, v in _DYN_OWNER.items() if sid and v == sid]
    for t in list(TRADERS) + mine:
        try:
            meta, fills, orders, trips = _load(t["id"])
        except DataMissing as e:                 # one missing file must not take the whole page down
            out.append({"id": t["id"], "role": t["role"], "blurb": t["blurb"], "n_trips": 0, "provenance": None,
                        "label": LABEL, "available": False, "note": str(e)})
            continue
        out.append({"id": t["id"], "role": t["role"], "blurb": t["blurb"], "n_trips": len(trips),
                    "provenance": _prov(meta, fills), "label": _label(meta), "available": True})
    return out


def _usd(x: float) -> str:
    return ("-$" if x < 0 else "$") + f"{abs(round(x)):,}"


def _plain(finding, suggestive, priced, court) -> str:
    """One plain headline derived from the habit state AND the court state, so a habit clause can never
    contradict an accepted rule (a rule can be accepted on its own evidence even when no habit is proven)."""
    held = priced["held_out_effect"]
    cap = "Capping your opening size at 1.5x your usual after a loss"
    st = priced["status"]
    n_acc = court.get("accepted", 0)
    if finding:
        habit = "A size habit passes the test within this trader."
    elif suggestive:
        habit = "A size habit looks real on its own but does not survive the correction for the several habit tests run, so it is not called a habit."
    else:
        habit = "No habit passes the test for this trader."
    link = " Separately, " if (n_acc or st == "ACCEPTED") and not finding else " "
    if st == "ACCEPTED":
        rule = f"{cap} would have saved {_usd(held)} on trades it never saw, and the court accepted that rule: send it to your rulebook and click Arm to use it."
        if not finding:
            rule = rule.replace("and the court accepted that rule", "and the court accepted that rule on that evidence alone, without calling it a habit")
    elif st == "UNDERPOWERED":
        rule = "There are not enough trades yet to judge any rule for this trader: the court needs at least 30 unseen trades and a rule that touches at least 10 of them."
    elif held > 0:
        rule = f"{cap} looks positive on unseen trades ({_usd(held)}) but not by enough to rule out luck, so the court did not accept it."
    else:
        rule = f"{cap} would have changed {_usd(held)} on trades it never saw, so the court did not accept it."
    if st != "ACCEPTED" and n_acc:
        rule += f" {n_acc} of the {court.get('tested', 4)} caps the court tested were accepted; see the court table."
    return habit + link + rule


def _review_uncached(tid: str) -> dict:
    meta, fills, orders, trips = _load(tid)
    findings = []
    for f in detectors.run_all(trips) + detectors2.run_all(trips):
        findings.append({"detector": f.detector, "status": f.status, "ratio": None if f.effect != f.effect else round(f.effect, 3),
                         "ci": None if f.ci[0] != f.ci[0] else [round(f.ci[0], 3), round(f.ci[1], 3)],
                         "p": None if f.p != f.p else round(f.p, 4), "n_a": f.n_a, "n_b": f.n_b, "detail": f.detail})
    # one pre-declared family: every habit test counts, including those too thin to run (their p is taken as 1)
    adj = holm([1.0 if f["p"] is None else f["p"] for f in findings])
    adj = [None if f["p"] is None else a for f, a in zip(findings, adj)]
    for f, a in zip(findings, adj):
        f["p_adj"] = None if a is None else round(a, 4)
        if f["status"] == "FLAGGED" and a is not None and a >= 0.05:
            f["status"] = "SUGGESTIVE"                  # raw p below 0.05 but it does not survive the correction
    # the court judges four pre-declared caps; every proposal is counted
    court = Court(n_perm=1500)
    for m in (1.0, 1.5, 2.0, 3.0):
        court.propose(Rule(value=m))
    verdicts = []
    for r in list(court.proposed):
        v = judge_wf(court, trips, r)
        priced = price_rule(trips, r, n_boot=800)
        verdicts.append({"rule": f"cap opening size at {r.value}x your median after a loss", "multiple": r.value, "status": v.status,
                         "held_out_effect": _r(v.test["effect"], 2), "affected": v.test["n_affected"],
                         "test_trips": v.test["n_trips"], "p": None if v.p != v.p else round(v.p, 4),
                         "threshold": round(v.alpha_used, 4), "all_history_effect": _r(priced["effect"], 2),
                         "all_history_ci": [_r(priced["ci"][0], 2), _r(priced["ci"][1], 2)], "reason": v.reason})
    wr = winrate.required_win_rate(trips)
    winrate_card = {"status": wr.status, "n": wr.n, "breakeven": _r(wr.breakeven, 4),
                    "breakeven_ci": [_r(wr.breakeven_ci[0], 4), _r(wr.breakeven_ci[1], 4)], "actual": _r(wr.actual, 4),
                    "margin_ci": [_r(wr.margin_ci[0], 4), _r(wr.margin_ci[1], 4)], "without_best": json_safe(wr.without_best), "detail": wr.detail}
    fee_card = None
    if fills:
        fd = detectors2.fee_drag(trips, detectors2.trip_fees(fills, trips))
        fee_card = {"status": fd.status, "share": None if fd.share != fd.share else round(fd.share, 4),
                    "ci": None if fd.ci[0] != fd.ci[0] else [_r(fd.ci[0], 4), _r(fd.ci[1], 4)], "total_fees": round(fd.total_fees, 2), "detail": fd.detail}
    pnl = [t.net_pnl for t in trips]
    summary = {"n_trips": len(trips), "wins": int(sum(x > 0 for x in pnl)), "losses": int(sum(x < 0 for x in pnl)),
               "net_pnl": round(float(sum(pnl)), 2),
               "first_ms": min(t.t_open_ms for t in trips), "last_ms": max(t.t_close_ms for t in trips)}
    flagged = [f for f in findings if f["status"] == "FLAGGED"]
    suggestive = [f for f in findings if f["status"] == "SUGGESTIVE"]
    pick = next((v for v in verdicts if v["multiple"] == 1.5), verdicts[0])
    headline = {
        "finding": flagged[0] if flagged else None,
        "suggestive": suggestive[0] if suggestive else None,
        "underpowered": sum(f["status"] == "UNDERPOWERED" for f in findings),
        "priced": {"rule": pick["rule"], "all_history_effect": pick["all_history_effect"], "all_history_ci": pick["all_history_ci"],
                   "held_out_effect": pick["held_out_effect"], "status": pick["status"], "p": pick["p"], "threshold": pick["threshold"],
                   "affected": pick["affected"], "test_trips": pick["test_trips"]},
        "court": {"proposed": court.trials, "tested": len(verdicts), "accepted": sum(v["status"] == "ACCEPTED" for v in verdicts)},
    }
    headline["plain"] = _plain(headline["finding"], headline["suggestive"], headline["priced"], headline["court"])
    return json_safe({
        "headline": headline,
        "trader": {"id": tid, "role": meta["role"], "blurb": meta["blurb"], "label": _label(meta), "provenance": _prov(meta, fills)},
        "summary": summary,
        "winrate": winrate_card,
        "fee_drag": fee_card,
        "ledger": {"fills": len(fills), "orders": len(orders), "round_trips": len(trips)},
        "curve": _curve(trips),
        "findings": findings,
        "court": {"proposed": court.trials, "tested": len(verdicts), "accepted": sum(v["status"] == "ACCEPTED" for v in verdicts),
                  "verdicts": verdicts},
        "number_source": "computed live from fills; nothing on this page is typed by hand",
    })


def _curve_scaled(trips, factors):
    ts = sorted(range(len(trips)), key=lambda i: trips[i].t_close_ms)
    cum, pts = 0.0, []
    for i in ts:
        cum += trips[i].net_pnl * factors[i]
        pts.append([trips[i].t_close_ms, round(cum, 2)])
    return pts


def toggle(tid: str, rule: str = "halt", n_losses: int = 2) -> dict:
    """Cached: the histories are fixed and every permutation test is seeded, so the answer for
    (trader, rule, n_losses) never changes; recomputing it cost ~150 ms of CPU per call (load test)."""
    return copy.deepcopy(_toggle_cached(tid, rule, n_losses))


@lru_cache(maxsize=64)
def _toggle_cached(tid: str, rule: str, n_losses: int) -> dict:
    return _toggle_uncached(tid, rule, n_losses)


def _toggle_uncached(tid: str, rule: str = "halt", n_losses: int = 2) -> dict:
    """The zero-click rule toggle: the curve with and without the rule, in-sample and held-out side by side.

    rule="halt": halt for the day after n_losses consecutive losing trips.
    rule="cap":  cap the opening size after a loss at 1.5x the median (baseline from the learning part only).
    The rule parameters are fixed in advance, never tuned on the history shown.
    """
    meta, fills, orders, trips = _load(tid)
    ts = sorted(trips, key=lambda t: t.t_open_ms)
    cut = int(len(ts) * 0.6)
    base = {"n_trips": len(ts), "cut_index": cut, "cut_time_ms": ts[cut].t_open_ms, "curve_actual": _curve(ts),
            "note": "The rule's parameter was fixed before looking at this history. The effect may be small or negative; it is shown as it is."}
    if rule == "cap":
        from engine.court import _baseline  # same baseline rule the court uses
        r = Rule(value=1.5)
        court = Court(n_perm=1500)
        for m in (1.0, 1.5, 2.0, 3.0):          # the same four proposals the table counts
            court.propose(Rule(value=m))
        v = judge_wf(court, ts, r)
        edge = int(len(ts) / 6)                  # walk-forward: the first sixth only seeds the baseline
        base["cut_index"], base["cut_time_ms"] = edge, ts[edge].t_open_ms
        b = _baseline(ts[:edge])
        lab = detectors.after_loss_labels(ts)
        factors = [min(1.0, (r.value * b) / t.first_order_notional) if (lab[i] == 1 and t.first_order_notional > 0) else 1.0
                   for i, t in enumerate(ts)]
        return {**base, "rule": "cap opening size at 1.5x your median after a loss", "rule_key": "cap",
                "curve_rule": _curve_scaled(ts, factors),
                "in_sample": {"effect": v.train["effect"], "n_skipped": v.train["n_affected"], "n_trips": v.train["n_trips"]},
                "held_out": {"effect": v.test["effect"], "n_skipped": v.test["n_affected"], "n_trips": v.test["n_trips"]},
                "status": v.status, "p": None if v.p != v.p else round(v.p, 4), "reason": v.reason}
    mask = halt.skip_mask(ts, n_losses)
    j = halt.judge(ts, n_losses)
    return {**base, "rule": j["rule"], "rule_key": "halt", "n_losses": n_losses, "curve_rule": _curve(ts, mask),
            "in_sample": j["in_sample"], "held_out": j["held_out"], "status": j["status"],
            "p": None if j["p"] is None else round(j["p"], 4), "reason": j["reason"]}


# ---- rulebook, checklist and gate (per-session sandbox; resets when the session goes) ------------------
_BOOKS: "OrderedDict[tuple[str, str], Rulebook]" = OrderedDict()
MAX_BOOKS = 200


_BOOKS_LOCK = threading.Lock()


def book(sid: str, tid: str) -> Rulebook:
    key = (sid or "default", tid)
    with _BOOKS_LOCK:                   # concurrent evictions used to raise KeyError in move_to_end
        rb = _BOOKS.get(key)
        if rb is None:
            rb = _BOOKS[key] = Rulebook(owner=key[0])
            while len(_BOOKS) > MAX_BOOKS:
                _BOOKS.popitem(last=False)
        else:
            _BOOKS.move_to_end(key)
        return rb


def _median_notional(trips) -> float:
    return float(np.median([t.first_order_notional for t in trips]))


def propose_rule(sid: str, tid: str, multiple: float) -> dict:
    meta, fills, orders, trips = _load(tid)
    rb = book(sid, tid)
    rule = Rule(value=float(multiple))
    with rb.lock:                                     # concurrent proposals each count the other
        v = _judge_cached(tid, tuple(r.value for r in rb.rules_tried), rule.value)
        rb.rules_tried.append(rule)
        e = rb.record_verdict(v)
        record_api.log_rule_event(sid, tid, rb.log[-1])
    return {"rule_id": e.rule_id, "state": e.state, "reason": v.reason, "p": None if v.p != v.p else round(v.p, 4),
            "threshold": round(v.alpha_used, 4), "trials": v.trials, "book": rulebook_view(sid, tid)}


@lru_cache(maxsize=512)
def _judge_cached(tid: str, tried: tuple[float, ...], value: float):
    """Same court, same seed, same history: the verdict depends only on these inputs (the earlier
    proposals enter through their count, which sets the trial-adjusted bar). Callers only read it."""
    trips = _load(tid)[3]
    court = Court(n_perm=1500)
    for m in tried + (value,):                       # every earlier proposal raises today's bar
        court.propose(Rule(value=m))
    return judge_wf(court, trips, Rule(value=value))


@lru_cache(maxsize=256)
def _measure_cached(tid: str, item_id: str, text: str, source: str, context: str, multiple: float) -> dict:
    trips = _load(tid)[3]
    it = checklist_mod.Item(item_id, text, source, context)
    return checklist_mod.measure(it, trips, _median_notional(trips), multiple=multiple, n_perm=1000)


def rulebook_view(sid: str, tid: str) -> dict:
    meta, fills, orders, trips = _load(tid)
    rb = book(sid, tid)
    rv = review(tid)
    items = checklist_mod.generate(rv["findings"], rb.active_rules())
    med = _median_notional(trips)
    out_items = []
    for it in items:
        mult = rb.active_rules()[0][1].value if rb.active_rules() else 1.5
        out_items.append({"id": it.item_id, "text": it.text, "context": it.context, "source": it.source,
                          "effect": dict(_measure_cached(tid, it.item_id, it.text, it.source, it.context, mult))})
    return {**rb.summary(), "checklist": out_items, "paper_only": True,
            "sandbox_note": "This sandbox is yours alone and resets when the session ends. Nothing here places an order."}


def transition(sid: str, tid: str, action: str, rule_id: str) -> dict:
    rb = book(sid, tid)
    who = "owner-click"
    fn = {"arm": lambda: rb.arm(rule_id, who),
          "retire_propose": lambda: rb.propose_retirement(rule_id, "owner asked to review this rule"),
          "retire_confirm": lambda: rb.confirm_retirement(rule_id, who), "keep": lambda: rb.keep(rule_id, who),
          "revert": lambda: rb.revert(rule_id, who)}[action]
    with rb.lock:                                     # log exactly the event this call made
        fn()
        record_api.log_rule_event(sid, tid, rb.log[-1])
    return rulebook_view(sid, tid)


def gate_check(sid: str, tid: str, text: str, after_loss: bool | None = None) -> dict:
    meta, fills, orders, trips = _load(tid)
    rb = book(sid, tid)
    rv = review(tid)
    ts = sorted(trips, key=lambda t: t.t_close_ms)
    last_loss = (ts[-1].net_pnl < 0) if after_loss is None else after_loss
    items = checklist_mod.generate(rv["findings"], rb.active_rules())
    flagged = [f["detector"] for f in rv["findings"] if f["status"] == "FLAGGED"]
    idea = gate_mod.parse_order(text)
    if idea.notional is None and idea.quantity is not None:
        px = costs.price_of(idea.symbol)
        if px:
            idea.notional = round(idea.quantity * px["price"], 2)
            idea.converted_from = (f"{idea.quantity:g} {idea.symbol} x {px['price']:,.2f} USDT (cached {px['symbol']} book mid, "
                                   f"{px['age_s']} s old) = {idea.notional:,.0f} USDT")
    cl = costs.cost_line(idea.symbol, idea.notional, idea.side)
    res = gate_mod.check(idea, rb.active_rules(), items, _median_notional(trips), last_loss, flagged,
                         cost_line=cl if cl.get("available") and not cl.get("stale") else None)
    out = {"idea": {"side": idea.side, "symbol": idea.symbol, "notional": idea.notional, "quantity": idea.quantity,
                     "converted_from": idea.converted_from}, "state": res.state,
            "reasons": res.reasons, "checklist": res.checklist, "broken_rules": res.broken_rules, "evidence": res.evidence_items,
            "last_trade_was_loss": last_loss, "paper_only": True, "check_line": cl,
            "numbers": [round(r.value * _median_notional(trips), 0) for _, r in rb.active_rules()],
            "note": "This checks an idea against your own rules. It does not place, preview or route any order."}
    from engine import bitget_context
    out["context"] = bitget_context.context_for(idea.symbol, time.strftime("%Y-%m-%d", time.gmtime()))
    try:
        from . import market_data
        mc = market_data.gate_context(idea.symbol)
        out["market_context"] = mc
        if mc.get("available") and not out["context"].get("available"):
            out["context"] = mc                      # same labelled-context slot the card already renders
    except Exception:
        pass
    versions = {rid: rb.entries[rid].current["version"] for rid, _ in rb.active_rules()}
    entry = record_api.log_gate_decision(sid, tid, out, versions, origin=record_api.classify_origin(sid, tid, tid in _DYN))
    out["record_seq"] = (entry or {}).get("seq")
    if entry and entry.get("error"):            # the gate still answers; it says the decision was not recorded
        out["record_error"] = "This decision was not written to the public record: " + entry["error"]
    return out


# ---- review cache: the demo histories are fixed, so every answer reuses one computation ----------------------------
import copy
import time
import threading

_REVIEW_CACHE: dict[str, dict] = {}
_RC_LOCK = threading.Lock()


_RC_FLIGHT: dict[str, threading.Lock] = {}


def review(tid: str) -> dict:
    if not any(t["id"] == tid for t in TRADERS) and tid not in _DYN:
        raise StopIteration                       # unknown id: no lock is created for it
    with _RC_LOCK:
        hit = _REVIEW_CACHE.get(tid)
        flight = None if hit is not None else _RC_FLIGHT.setdefault(tid, threading.Lock())
    if hit is None:
        # single flight: the first caller computes, the others wait for it. Without this, 50 cold
        # visitors each ran the same multi-second review at once (cold load test: p95 89 s).
        with flight:
            with _RC_LOCK:
                hit = _REVIEW_CACHE.get(tid)
            if hit is None:
                hit = _review_uncached(tid)
                with _RC_LOCK:
                    _REVIEW_CACHE[tid] = hit
    return copy.deepcopy(hit)


def warm() -> None:
    """Compute every demo trader once in a background thread so the first visitor never waits."""
    def run():
        for t in TRADERS:
            try:
                review(t["id"])
            except Exception:
                pass
    threading.Thread(target=run, daemon=True, name="review-warmup").start()
