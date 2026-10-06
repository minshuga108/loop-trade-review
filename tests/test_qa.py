"""engine.qa + app.qa_chat: every metric against hand-computed values, planted traders, properties, parser, chat shape."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

from app import qa_chat, service
from engine import ledger, qa
from engine.planted import planted_trader
from engine.schema import Fill, Provenance, RoundTrip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import score_qa  # noqa: E402

H = 3_600_000
D = 24 * H
T0 = 1_704_103_200_000            # 2024-01-01 10:00:00 UTC, a Monday


def trip(sym, side, open_ms, hold_h, size, pnl, oid):
    return RoundTrip(symbol=sym, t_open_ms=open_ms, t_close_ms=open_ms + int(hold_h * H), side=side, first_order_notional=size,
                     opened_notional=size, net_pnl=pnl, first_order_id=oid, provenance=Provenance.SIM_PLANTED)


@pytest.fixture
def five():
    """Mon BTC +100 | Tue ETH -50 | Tue BTC +200 | Wed ETH -150 | Thu BTC +30 (open times UTC)."""
    return [trip("BTC", "buy", T0, 2, 1000, 100.0, "a"),
            trip("ETH", "sell", T0 + D + 1 * H, 1, 2000, -50.0, "b"),
            trip("BTC", "buy", T0 + D + 4 * H, 4, 3000, 200.0, "c"),
            trip("ETH", "buy", T0 + 2 * D - 1 * H, 0.5, 1500, -150.0, "d"),
            trip("BTC", "sell", T0 + 3 * D + 5 * H, 3, 500, 30.0, "e")]


def run(trips, fills=None, now_ms=None, **plan):
    return qa.execute(qa.QueryPlan.model_validate(plan), trips, fills, now_ms=now_ms)


# ---------------------------------------------------------------- hand-computed metrics
def test_scalar_metrics_against_hand_values(five):
    exp = {"trade_count": 5, "wins": 3, "losses": 2, "win_rate": 0.6, "net_pnl": 130, "avg_pnl": 26, "expectancy": 26, "avg_win": 110, "avg_loss": 100,
           "median_size": 1500, "avg_hold": 2.1, "median_hold": 2.0, "best_trade": 200, "worst_trade": -150, "profit_factor": 1.65,
           "max_drawdown": 150, "win_streak": 1, "loss_streak": 1, "trades_per_day": 1.25, "busiest_day": 2, "best_day": 150, "worst_day": -150,
           "active_days": 4}
    for m, v in exp.items():
        r = run(five, metric=m)
        assert r.available and r.value == pytest.approx(v), (m, r.value)
        assert r.n == 5
    assert run(five, metric="busiest_day").detail["day"] == "2024-01-02"
    assert run(five, metric="best_day").detail["day"] == "2024-01-02"
    assert run(five, metric="worst_day").detail["day"] == "2024-01-03"
    assert run(five, metric="best_trade").detail["symbol"] == "BTC"
    dd = run(five, metric="max_drawdown").detail
    assert dd["peak_day"] == "2024-01-02" and dd["trough_day"] == "2024-01-03"
    last_close = five[4].t_close_ms
    assert run(five, metric="time_since_last", now_ms=last_close + 2 * D).value == pytest.approx(2.0)


def test_streaks_and_drawdown_on_a_run():
    trips = [trip("X", "buy", T0 + i * D, 1, 100, p, str(i)) for i, p in enumerate([10, 20, -5, -5, -5, 30, -1])]
    assert run(trips, metric="win_streak").value == 2
    assert run(trips, metric="loss_streak").value == 3
    assert run(trips, metric="max_drawdown").value == 15      # peak 30 after two wins, trough 15


def test_filters_hand_values(five):
    assert run(five, metric="trade_count", filters={"weekdays": [1]}).value == 2
    assert run(five, metric="trade_count", filters={"weekdays": [5, 6]}).value == 0
    assert run(five, metric="trade_count", filters={"symbol": "BTC"}).value == 3
    assert run(five, metric="trade_count", filters={"symbol": "btc"}).value == 3           # case-insensitive
    assert run(five, metric="net_pnl", filters={"side": "sell"}).value == -20
    assert run(five, metric="avg_hold", filters={"outcome": "loss"}).value == pytest.approx(0.75)
    r = run(five, metric="win_rate", filters={"after_loss": True})
    assert r.value == 1.0 and r.n == 2                                                      # trips c and e follow a loss
    assert run(five, metric="net_pnl", filters={"after_loss": False}).value == -200          # trips b and d follow a win; a has no prior
    r = run(five, metric="win_rate", filters={"symbol": "ZZZ"})
    assert r.n == 0 and "no_symbol_match" in r.caveats and "BTC" in r.detail["symbols_traded"]


def test_symbol_matching_handles_prefixes_and_quote_suffixes():
    assert qa.symbol_matches("xyz:TSLA", "TSLA") and qa.symbol_matches("BTCUSDT", "BTC") and qa.symbol_matches("BTC-PERP", "BTC")
    assert not qa.symbol_matches("BTCDOWN", "BTC") and not qa.symbol_matches("ETH", "BTC")


def test_periods_hand_values(five):
    assert run(five, metric="trade_count", period={"kind": "last_7d"}).value == 5
    r = run(five, metric="net_pnl", period={"kind": "last_n", "n": 2})
    assert r.value == -120 and r.n == 2
    assert run(five, metric="net_pnl", period={"kind": "first_third"}).value == 100        # n//3 = 1 trip
    assert run(five, metric="net_pnl", period={"kind": "last_third"}).value == 30
    assert run(five, metric="trade_count", period={"kind": "first_half"}).value == 2
    assert run(five, metric="trade_count", period={"kind": "second_half"}).value == 3
    one_day = [trip("X", "buy", T0 + i * D, 1, 100, 1.0, str(i)) for i in range(40)]
    assert run(one_day, metric="trade_count", period={"kind": "last_30d"}).value == 30      # 30 days back from the last close (+1 h), anchored to the record


def test_exclude_best_and_compare(five):
    r = run(five, metric="net_pnl", exclude_best=True)
    assert r.value == -70 and r.n == 4 and r.detail["excluded_best"]["net_pnl"] == 200
    assert run(five, metric="win_rate", exclude_best=True).value == pytest.approx(0.5)
    r = run(five, metric="net_pnl", compare="first_vs_last_third")
    assert r.compare["first"] == 100 and r.compare["last"] == 30 and r.value == -70 and r.compare["n_first"] == 1
    r = run(five, metric="worst_trade", top_n=2)
    assert [x["net_pnl"] for x in r.rows] == [-150, -50]


def test_group_bys_hand_values(five):
    g = {r.label: (r.value, r.n) for r in run(five, metric="net_pnl", group_by="weekday").groups}
    assert g == {"Mon": (100, 1), "Tue": (150, 2), "Wed": (-150, 1), "Thu": (30, 1)}
    g = {r.key: (r.value, r.n) for r in run(five, metric="net_pnl", group_by="symbol").groups}
    assert g == {"BTC": (330, 3), "ETH": (-200, 2)}
    g = {r.key: r.value for r in run(five, metric="net_pnl", group_by="side").groups}
    assert g == {"buy": 150, "sell": -20}
    r = run(five, metric="net_pnl", group_by="after_loss")
    assert {x.key: (x.value, x.n) for x in r.groups} == {"1": (230, 2), "0": (-200, 2)} and r.detail["dropped_unlabelled"] == 1
    g = {r.key: r.value for r in run(five, metric="median_hold", group_by="outcome").groups}
    assert g == {"win": 3.0, "loss": 0.75}
    g = {r.key: r.n for r in run(five, metric="trade_count", group_by="hour").groups}
    assert g == {"10": 1, "11": 1, "14": 1, "09": 1, "15": 1}
    r = run(five, metric="net_pnl", group_by="symbol", top_n=1)
    assert [x.key for x in r.groups] == ["BTC"]


def test_fees_from_fills_hand_values():
    def fill(i, sym, side, t, px, sz, fee, pnl, sp, is_open, oid):
        return Fill(venue="t", account="a", exec_id=str(i), order_id=oid, t_ms=t, symbol=sym, side=side, is_open=is_open, price=px, size=sz, fee=fee,
                    realized_pnl=pnl, start_position=sp, provenance=Provenance.SIM_PAPER)
    fills = [fill(1, "BTC", "buy", T0, 100, 1, 1.0, 0, 0, True, "o1"), fill(2, "BTC", "sell", T0 + H, 110, 1, 1.5, 10, 1, False, "o2"),
             fill(3, "ETH", "buy", T0 + 2 * H, 50, 2, 0.5, 0, 0, True, "o3"), fill(4, "ETH", "sell", T0 + 3 * H, 45, 2, 0.5, -10, 2, False, "o4")]
    trips = ledger.to_round_trips(fills)
    assert sorted(t.net_pnl for t in trips) == [-11.0, 7.5]
    assert run(trips, fills, metric="total_fees").value == pytest.approx(3.5)
    r = run(trips, fills, metric="fee_share")
    assert r.value == pytest.approx(0.35) and r.detail["gross_profit"] == 10
    assert run(trips, fills, metric="total_fees", filters={"symbol": "ETH"}).value == pytest.approx(1.0)
    r = run(trips, None, metric="total_fees")
    assert not r.available and "no_fee_data" in r.caveats
    assert not run(planted_trader(n=50), [], metric="fee_share").available        # planted trips carry no fills


def test_small_n_and_empty_caveats(five):
    assert "small_n" in run(five, metric="net_pnl").caveats
    r = run(five, metric="win_rate", filters={"weekdays": [6]})
    assert r.n == 0 and r.value is None and "empty" in r.caveats
    assert run(five, metric="profit_factor", filters={"outcome": "win"}).available is False     # no losers: undefined


# ---------------------------------------------------------------- planted traders
def test_planted_size_after_loss_shows_in_group_by():
    trips = planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=2)
    r = run(trips, metric="median_size", group_by="after_loss")
    g = {x.key: x.value for x in r.groups}
    assert 2.0 < g["1"] / g["0"] < 4.5
    flat = planted_trader(n=600, size_mult=1.0, seed=3)
    g = {x.key: x.value for x in run(flat, metric="median_size", group_by="after_loss").groups}
    assert 0.8 < g["1"] / g["0"] < 1.25


def test_planted_values_match_direct_numpy():
    trips = planted_trader(n=300, size_mult=2.0, tilt=-0.004, seed=5)
    p = np.array([t.net_pnl for t in trips])
    assert run(trips, metric="net_pnl").value == pytest.approx(p.sum())
    assert run(trips, metric="win_rate").value == pytest.approx((p > 0).sum() / ((p > 0).sum() + (p < 0).sum()))
    assert run(trips, metric="median_size").value == pytest.approx(np.median([t.first_order_notional for t in trips]))
    assert run(trips, metric="avg_hold").value == pytest.approx(np.mean([t.hold_ms for t in trips]) / H)
    assert run(trips, metric="best_trade").value == p.max() and run(trips, metric="worst_trade").value == p.min()
    assert run(trips, metric="net_pnl", exclude_best=True).value == pytest.approx(p.sum() - p.max())
    cum = np.cumsum(p)
    assert run(trips, metric="max_drawdown").value == pytest.approx((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max())
    r = run(trips, metric="avg_pnl")
    assert r.interval and r.interval[0] < r.value < r.interval[1]


# ---------------------------------------------------------------- property tests (seeded random)
def random_trips(seed: int, n: int) -> list[RoundTrip]:
    g = np.random.default_rng(seed)
    syms = ["BTC", "ETH", "SOL", "xyz:TSLA"]
    t = T0
    out = []
    for i in range(n):
        hold = int(g.integers(1, 48)) * H
        out.append(RoundTrip(symbol=str(g.choice(syms)), t_open_ms=t, t_close_ms=t + hold, side=str(g.choice(["buy", "sell"])),
                             first_order_notional=float(g.uniform(100, 5000)), opened_notional=1.0, net_pnl=float(np.round(g.normal(0, 100), 2)),
                             first_order_id=str(i), provenance=Provenance.SIM_PLANTED))
        t += hold + int(g.integers(0, 72)) * H
    return out


@pytest.mark.parametrize("seed", range(12))
def test_property_groups_sum_to_total_and_counts_add_up(seed):
    trips = random_trips(seed, int(np.random.default_rng(seed).integers(5, 120)))
    total = sum(t.net_pnl for t in trips)
    for g in qa.GROUP_BYS:
        r = run(trips, metric="net_pnl", group_by=g)
        s = sum(x.value for x in r.groups)
        if g == "after_loss":
            lab = qa._labels(trips)
            s += sum(t.net_pnl for t in trips if lab[id(t)] < 0)
        elif g == "outcome":
            s += sum(t.net_pnl for t in trips if t.net_pnl == 0)
        assert s == pytest.approx(total, abs=1e-6), g
        c = run(trips, metric="trade_count", group_by=g)
        assert sum(x.n for x in c.groups) + c.detail["dropped_unlabelled"] == len(trips)
    assert run(trips, metric="wins").value + run(trips, metric="losses").value + sum(t.net_pnl == 0 for t in trips) == len(trips)


@pytest.mark.parametrize("seed", range(12))
def test_property_filters_never_increase_n_and_exclusion_removes_one(seed):
    g = np.random.default_rng(100 + seed)
    trips = random_trips(seed, int(g.integers(3, 150)))
    base = run(trips, metric="trade_count")
    filters = [{"symbol": "BTC"}, {"side": "sell"}, {"weekdays": sorted(set(g.integers(0, 7, 3).tolist()))}, {"outcome": "loss"}, {"after_loss": True},
               {"symbol": "ETH", "side": "buy"}, {"weekdays": [0, 1], "outcome": "win", "after_loss": False}]
    for f in filters:
        r = run(trips, metric="trade_count", filters=f)
        assert r.n <= base.n and r.value == r.n
        rr = run(trips, metric="trade_count", filters=f, period={"kind": str(g.choice(["last_7d", "last_30d", "first_third", "last_third", "first_half"]))})
        assert rr.n <= r.n
    ex = run(trips, metric="net_pnl", exclude_best=True)
    assert ex.n == base.n - 1 and ex.value == pytest.approx(sum(t.net_pnl for t in trips) - max(t.net_pnl for t in trips))
    for k in ("last_n",):
        r = run(trips, metric="trade_count", period={"kind": k, "n": 7})
        assert r.n == min(7, len(trips))


# ---------------------------------------------------------------- schema
def test_schema_is_closed():
    assert qa.validate_plan({"metric": "net_pnl"}) is not None
    assert qa.validate_plan({"metric": "sharpe"}) is None
    assert qa.validate_plan({"metric": "net_pnl", "evil": 1}) is None
    assert qa.validate_plan({"metric": "net_pnl", "filters": {"weekdays": [7]}}) is None
    assert qa.validate_plan({"metric": "net_pnl", "filters": {"symbol": "BTC; DROP TABLE"}}) is None
    assert qa.validate_plan({"metric": "net_pnl", "top_n": 500}) is None
    assert qa.validate_plan({"metric": "net_pnl", "group_by": "trader"}) is None
    assert qa.validate_plan("metric=net_pnl") is None
    assert qa.QueryPlan(metric="net_pnl").compact() == {"metric": "net_pnl"}


# ---------------------------------------------------------------- parser
def test_parser_dev_set_is_fully_covered():
    res = score_qa.score("dev")
    assert res["groups"]["all"][0] == res["n"] == 75, res["misses"]


def test_parser_heldout_frozen_score():
    """Scored once after the parser was finished (docs/QA.md). This pins that number so a later edit cannot silently regress it."""
    res = score_qa.score("heldout")
    assert res["n"] == 75
    assert res["groups"]["all"][0] >= 72, res["misses"]           # frozen single-shot figure 72/75 (2026-10-06); see docs/QA.md


def test_parser_followups_modify_previous_plan():
    prev = qa.QueryPlan(metric="net_pnl")
    assert qa.parse("and without my best trade?", prev).plan.compact() == {"metric": "net_pnl", "exclude_best": True}
    assert qa.parse("what about Tuesdays", prev).plan.compact() == {"metric": "net_pnl", "filters": {"weekdays": [1]}}
    assert qa.parse("那周二呢", prev).plan.compact() == {"metric": "net_pnl", "filters": {"weekdays": [1]}}
    assert qa.parse("only BTC", prev).plan.compact() == {"metric": "net_pnl", "filters": {"symbol": "BTC"}}
    assert qa.parse("and for shorts?", prev).plan.compact() == {"metric": "net_pnl", "filters": {"side": "sell"}}
    assert qa.parse("last week", prev).plan.compact() == {"metric": "net_pnl", "period": {"kind": "last_7d"}}
    # a fresh question with its own metric does not inherit the old filters
    p2 = qa.parse("my biggest loss", qa.parse("what about Tuesdays", prev).plan).plan.compact()
    assert p2 == {"metric": "worst_trade"}
    assert qa.parse("and the best?", qa.QueryPlan(metric="worst_trade")).plan.metric == "best_trade"


def test_parser_unsupported_clarify_and_none():
    assert qa.parse("what was my MAE").kind == "unsupported"
    assert qa.parse("why did the price dump").kind == "unsupported"
    assert qa.parse("should I buy BTC now").reason == "advice"
    assert qa.parse("my best").kind == "clarify" and len(qa.parse("my best").options) >= 2
    assert qa.parse("BTC").kind == "clarify"
    for s in ("hello", "what is my biggest costly habit?", "what if I had kept the halt rule?", "show my weekly review", "asdfgh qwerty", "is this advice"):
        assert qa.parse(s).kind == "none", s


# ---------------------------------------------------------------- app.qa_chat
def test_answer_qa_shape_and_lock_on_real_and_planted_traders():
    rows = [json.loads(l) for l in (ROOT / "eval" / "qa_questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    plans = [qa.QueryPlan.model_validate(r["expected"]["plan"]) for r in rows if r["expected"]["kind"] == "plan"]
    for tid in ("A", "B", "F"):
        meta, fills, orders, trips = service._load(tid)
        for p in plans:
            for lang in ("en", "zh"):
                out = qa.render(qa.execute(p, trips, fills), lang)
                assert out["number_lock"] == "passed", (tid, p.compact(), lang, out["text"])
                assert out["text"] and out["card"]["type"] in ("tiles", "bars", "table") and len(out["next"]) == 3
    r = qa_chat.answer_qa("B", "how much did fees cost me")
    for k in ("intent", "lang", "kind", "text", "facts", "number_lock", "llm", "interpreted", "next", "plan", "card", "computed", "steps", "provenance", "label"):
        assert k in r, k
    assert r["number_lock"] == "passed" and r["plan"] == {"metric": "total_fees"} and r["paper_only"] is True
    assert r["computed"]["n"] == 112 and "UTC" in r["computed"]["method"]
    assert any(f["fact"] == "value" for f in r["facts"])


def test_answer_qa_follow_up_chain_and_none():
    r1 = qa_chat.answer_qa("B", "what is my net pnl")
    r2 = qa_chat.answer_qa("B", "and without my best trade?", previous_plan=r1["plan"])
    assert r2["plan"] == {"metric": "net_pnl", "exclude_best": True} and r2["followup"] and r2["number_lock"] == "passed"
    assert r2["computed"]["n"] == r1["computed"]["n"] - 1
    r3 = qa_chat.answer_qa("B", "what about Tuesdays", previous_plan=r2["plan"])
    assert r3["plan"]["filters"] == {"weekdays": [1]} and r3["lang"] == "en"
    r4 = qa_chat.answer_qa("B", "那周二呢", previous_plan={"metric": "trade_count"})
    assert r4["lang"] == "zh" and "周二" in r4["interpreted"] and r4["number_lock"] == "passed"
    for msg in ("hello", "what is my biggest costly habit?", "show my weekly review", "asdfgh qwerty", "place an order for 3 BTC"):
        assert qa_chat.answer_qa("B", msg) is None, msg
    u = qa_chat.answer_qa("B", "what was my MAE on that trade", previous_plan={"metric": "worst_trade"})
    assert u["plan"] is None and u["card"]["type"] == "unsupported" and len(u["next"]) == 3
    c = qa_chat.answer_qa("B", "my best")
    assert c["card"]["type"] == "clarify" and c["plan"] is None


def test_planner_hook_validates_and_refuses(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    assert qa_chat.qwen_plan("anything") is None and "off" in qa_chat.planner_label()
    assert qa_chat.answer_qa("B", "zzz blorp") is None                                    # no key: deterministic only
    good = qa_chat.answer_qa("B", "zzz blorp", planner=lambda t, p: {"metric": "win_rate"})
    assert good["plan"] == {"metric": "win_rate"} and good["number_lock"] == "passed" and "Qwen" in good["llm"]
    bad = qa_chat.answer_qa("B", "zzz blorp", planner=lambda t, p: {"metric": "net_pnl", "evil": "x"})
    assert bad["plan"] is None and "refused" in bad["llm"] and bad["card"]["type"] == "refused" and bad["facts"] == []
    bad2 = qa_chat.answer_qa("B", "zzz blorp", planner=lambda t, p: {"metric": "sharpe"})
    assert bad2["plan"] is None and "plan_refused" in bad2["flags"]
    assert qa_chat.answer_qa("B", "zzz blorp", planner=lambda t, p: {"not_a_data_question": True}) is None
    assert "refused" in qa_chat.answer_qa("B", "zzz blorp", planner=lambda t, p: "garbage")["llm"]      # not even a dict: refused, nothing computed
    # the planner is only consulted when the deterministic parser found nothing
    seen = []
    r = qa_chat.answer_qa("B", "how many trades", planner=lambda t, p: seen.append(t))
    assert r["plan"] == {"metric": "trade_count"} and seen == []
    # http path with a mock transport: the model's JSON is parsed, then validated by answer_qa
    monkeypatch.setenv("QWEN_API_KEY", "test-key-not-real")

    def handler(request):
        assert request.headers["authorization"] == "Bearer test-key-not-real"
        body = json.loads(request.content)
        assert "QueryPlan" in body["messages"][0]["content"] or "metric" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"metric\": \"total_fees\", \"filters\": {\"symbol\": \"BTC\"}}"}}]})
    raw = qa_chat.qwen_plan("fees on bitcoin pls", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert qa.validate_plan(raw).compact() == {"metric": "total_fees", "filters": {"symbol": "BTC"}}

    def broken(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    assert qa_chat.qwen_plan("x", client=httpx.Client(transport=httpx.MockTransport(broken))) is None


def test_number_lock_refuses_an_invented_number(monkeypatch):
    trips = planted_trader(n=60, seed=1)
    res = qa.execute(qa.QueryPlan(metric="net_pnl"), trips, [])
    monkeypatch.setattr(qa, "_headline", lambda r, lang: ("Net P&L is 999,999 over 60 trades.", [60.0]))
    out = qa.render(res, "en")
    assert out["number_lock"].startswith("refused") and "refused" in out["text"]
