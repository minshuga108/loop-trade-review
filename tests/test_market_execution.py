"""Check-line cost module. No network: every Bitget reply is a recorded public GET
(2026-10-05 ~19:35 UTC, US regular session) served through httpx.MockTransport."""
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

from engine import cost_report as cr
from engine import execution as ex
from engine import market as mk
from engine.schema import Provenance

FIX = Path(__file__).parent / "fixtures" / "market"
SYMS = ["RNVDAUSDT", "RTSLAUSDT", "RSPYUSDT", "RQQQUSDT", "RAAPLUSDT", "RMSTRUSDT"]
BOOK_TS = 1791228955597          # RNVDAUSDT book ts in the fixture (Mon 15:35 ET)


def _handler(req: httpx.Request) -> httpx.Response:
    q, p = req.url.params, req.url.path
    cat = {"SPOT": "spot", "USDT-FUTURES": "fut"}.get(q.get("category", ""), "")
    sym = q.get("symbol", "")
    name = {"/api/v3/market/instruments": f"inst_{cat}_{sym}.json",
            "/api/v3/market/tickers": f"tick_{cat}_{sym}.json",
            "/api/v3/market/orderbook": f"book_{cat}_{sym}.json",
            "/api/v3/market/candles": f"candles_{cat}_{sym}.json",
            "/api/v2/spot/public/symbols": f"v2_spot_symbol_{sym}.json",
            "/api/v3/reality/market/states": "reality_states.json"}.get(p)
    if sym == "RSOXLUSDT" and p.endswith("orderbook"):
        name = "book_spot_RSOXLUSDT_empty.json"
    if sym == "NOSUCHXYZUSDT":
        name = "err_unknown_symbol.json"
    f = FIX / (name or "missing")
    if not f.exists():
        return httpx.Response(404, json={"code": "404", "msg": f"no fixture {name}", "data": None})
    return httpx.Response(200, content=f.read_bytes())


@pytest.fixture
def fx():
    with mk.Fetcher(httpx.Client(transport=httpx.MockTransport(_handler))) as f:
        yield f


def _book(bids, asks, prov=Provenance.SIM_PAPER):
    return mk.OrderBook(symbol="TEST", category=mk.Category.SPOT, ts_ms=1, provenance=prov,
                        bids=tuple(mk.Level(price=p, size=s) for p, s in bids),
                        asks=tuple(mk.Level(price=p, size=s) for p, s in asks))


# ------------------------------------------------------------------ market client


def test_spot_and_perp_instruments_parse_string_numbers(fx):
    r = fx.instrument("RNVDAUSDT")
    assert (r.min_order_usdt, r.tick, r.qty_step, r.min_order_qty) == (10, 0.01, 0.0001, 0.0001)
    assert r.is_reality and r.symbol_type == "stock" and r.status == "online"
    assert r.taker_fee is None                                   # SPOT v3 instruments carry no fee
    p = fx.instrument("NVDAUSDT", "USDT-FUTURES")
    assert (p.min_order_usdt, p.qty_step, p.taker_fee) == (5, 0.01, 0.0006) and not p.is_reality
    assert fx.spot_fees("RNVDAUSDT").taker_fee == 0.001


def test_orderbook_sorted_numbers_and_empty_book(fx):
    b = fx.orderbook("RNVDAUSDT")
    assert b.provenance is Provenance.REPLAY_NATIVE and b.ts_ms == BOOK_TS
    assert all(x.price > y.price for x, y in zip(b.bids, b.bids[1:]))
    assert all(x.price < y.price for x, y in zip(b.asks, b.asks[1:]))
    assert b.best_bid < b.mid < b.best_ask
    e = fx.orderbook("RSOXLUSDT")
    assert e.is_empty and e.mid is None and e.spread_bps is None


def test_unknown_symbol_raises_with_bitget_code(fx):
    with pytest.raises(mk.BitgetAPIError) as ei:
        fx.orderbook("NOSUCHXYZUSDT")
    assert ei.value.code == "40034"


def test_null_list_and_candles_and_tickers(fx):
    assert mk._list(None) == [] and mk._list({"list": None}) == []
    c = fx.candles("NVDAUSDT", "USDT-FUTURES")
    assert len(c) == 5 and all(a.ts_ms < b.ts_ms for a, b in zip(c, c[1:]))
    t = fx.ticker("NVDAUSDT", "USDT-FUTURES")
    assert t.mark and t.index and t.funding_rate is not None
    assert [w.state for w in fx.reality_states()] == ["pre_market", "regular", "after_hours", "overnight"]


# ------------------------------------------------------------------ depth walk


def test_depth_walk_exact_numbers_and_unfilled_remainder():
    b = _book([(99, 1)], [(101, 1), (102, 1)])                  # mid 100
    w = ex.depth_walk(b, "buy", 151.5)
    base = 1 + 50.5 / 102
    assert w.avg_price == pytest.approx(151.5 / base)
    assert w.cost_bps == pytest.approx((151.5 / base - 100) / 100 * 1e4)
    assert w.fill_fraction == 1 and w.unfilled == 0 and w.levels_used == 2
    big = ex.depth_walk(b, "buy", 1000)
    assert big.filled == pytest.approx(203) and big.unfilled == pytest.approx(797)
    assert big.fill_fraction == pytest.approx(0.203)              # never assumes the rest clears
    s = ex.depth_walk(b, "sell", 0.5, size_in="base")
    assert s.avg_price == 99 and s.cost_bps == pytest.approx(100)


def test_empty_side_gives_no_cost_not_a_number():
    w = ex.depth_walk(_book([(99, 1)], []), "buy", 50)
    assert w.fill_fraction == 0 and w.avg_price is None and w.cost_bps is None


def test_provenance_flows_and_sim_never_calibrates(fx):
    sim = ex.depth_walk(_book([(99, 1)], [(101, 1)]), "buy", 10)
    assert sim.provenance is Provenance.SIM_PAPER and not ex.may_calibrate(sim.provenance)
    real = ex.depth_walk(fx.orderbook("RNVDAUSDT"), "buy", 1000)
    assert real.provenance is Provenance.REPLAY_NATIVE and ex.may_calibrate(real.provenance)


# ------------------------------------------------------------------ order rules


def test_min_order_tick_and_step(fx):
    i = fx.instrument("RNVDAUSDT")
    assert not ex.validate_order(i, 9.99, 239.94).ok
    assert ex.validate_order(i, 10, 239.94).ok                    # spot market buy is sized in USDT
    sell = ex.validate_order(i, 10, 239.94, side="sell")          # sized in base: 0.0416 x 239.94 = 9.98
    assert not sell.ok and sell.qty == pytest.approx(0.0416) and "after rounding" in sell.reasons[0]
    assert ex.validate_order(i, 10.5, 239.94, side="sell").ok
    assert not ex.validate_order(i, 100, None, limit_price=239.945, order_type="limit").ok
    whole = i.model_copy(update={"qty_step": 1.0, "min_order_qty": 1.0})
    r = ex.validate_order(whole, 100, 239.94, side="sell")
    assert not r.ok and "below the minimum quantity" in r.reasons[0]
    assert any("price band not checked" in n for n in r.notes)


# ------------------------------------------------------------------ slicing


@pytest.mark.parametrize("sym,size", [("RNVDAUSDT", 1000), ("RAAPLUSDT", 10000), ("RMSTRUSDT", 2000)])
def test_slice_plan_rules_on_recorded_books(fx, sym, size):
    b, i = fx.orderbook(sym), fx.instrument(sym)
    p = ex.slice_plan(b, i, "buy", size, participation=0.10)
    d = ex.depth_within_bps(b, "buy", 50)
    assert p.depth_window_usdt == pytest.approx(d)
    assert p.advise_slower == (d < 3 * size or not p.feasible)
    assert p.child_usdt <= 0.10 * d + 1e-9 and p.n_children * p.child_usdt == pytest.approx(size)
    assert p.optimistic.cost_bps <= p.pessimistic.cost_bps + 1e-9   # prefix walk never costs more
    assert p.pessimistic.label == ex.PESSIMISTIC and p.optimistic.label == ex.OPTIMISTIC


def test_slice_below_min_order_is_rejected_not_sent():
    i = mk.Instrument(symbol="TEST", category="SPOT", base_coin="T", quote_coin="USDT", status="online",
                      symbol_type="stock", is_reality=True, min_order_usdt=10, min_order_qty=0.0001, tick=0.01,
                      qty_step=0.0001, max_market_order_usdt=None, maker_fee=None, taker_fee=None,
                      buy_limit_price_ratio_raw=None, sell_limit_price_ratio_raw=None)
    b = _book([(99.99, 1)], [(100.01, 0.5)])                     # ~50 USDT visible within 50 bps
    p = ex.slice_plan(b, i, "buy", 40, participation=0.10)
    assert not p.feasible and p.advise_slower and "Cannot slice" in p.advice
    tw = ex.twap_benchmark(b, i, "buy", 40, minutes=8)
    assert tw.n_slices == 8 and tw.slice_usdt == 5 and not tw.slice_check.ok
    assert tw.pessimistic.fill_fraction == 1 and tw.optimistic.cost_bps <= tw.pessimistic.cost_bps


def test_empty_book_plan_says_do_not_send(fx):
    p = ex.slice_plan(fx.orderbook("RSOXLUSDT"), fx.instrument("RNVDAUSDT"), "buy", 100)
    assert not p.feasible and p.n_children is None and p.pessimistic.fill_fraction == 0


# ------------------------------------------------------------------ cost report


def test_cost_report_card_on_recorded_rnvda(fx):
    r = cr.cost_report(fx, "RNVDAUSDT", 5000, twap_minutes=10, now_ms=BOOK_TS)
    json.dumps(r)                                                  # plain, renderable structure
    assert r["provenance"] == "REPLAY_NATIVE" and r["session"]["label"] == "regular" and not r["session"]["weekend"]
    assert r["fees"]["taker_fee_bps"] == pytest.approx(10)
    assert r["all_in_bps"] == pytest.approx(r["cost"]["cost_bps"] + 10)
    assert r["min_order"]["ok"] and r["funding"]["applies"] is False
    assert r["ticker_vs_book"]["ticker_inside_book"]               # recorded: ticker 239.82/239.83 vs book 239.77/239.94
    assert r["twap"]["slice_usdt"] == 500
    assert any("cannot be validated" in c for c in r["caveats"])


def test_cost_report_reports_unfilled_on_thin_book(fx):
    b = fx.orderbook("RAAPLUSDT")
    visible = sum(lv.notional for lv in b.asks)
    r = cr.cost_report(fx, "RAAPLUSDT", visible * 2, now_ms=BOOK_TS)
    assert r["cost"]["fill_fraction"] == pytest.approx(0.5) and r["all_in_bps"] is None
    assert r["slicing"]["advise_slower"] and "unfilled" in r["caveats"][0]


def test_depth_rank_is_measured_and_relative_to_size(fx):
    rows = cr.rank_symbols(fx, SYMS + ["RSOXLUSDT"], 10_000)
    depths = [x["depth_usdt"] for x in rows]
    assert depths == sorted(depths, reverse=True) and rows[-1]["tier"] == "empty"
    tiers_small = {x["symbol"]: x["tier"] for x in cr.rank_symbols(fx, SYMS, 10)}
    tiers_huge = {x["symbol"]: x["tier"] for x in cr.rank_symbols(fx, SYMS, 1e9)}
    assert set(tiers_huge.values()) == {"thin"} and "deep" in tiers_small.values()


def _ms(y, mo, d, h, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp() * 1000)


def test_session_labels_weekend_and_overnight_wrap(fx):
    w = fx.reality_states()
    assert cr.session_label(_ms(2026, 10, 10, 15), w)["weekend"]                # Saturday
    assert cr.session_label(_ms(2026, 10, 6, 6), w)["label"] == "overnight"     # 02:00 ET Tue
    assert cr.session_label(_ms(2026, 10, 6, 12), w)["label"] == "pre_market"   # 08:00 ET
    assert cr.session_label(_ms(2026, 10, 6, 12), None)["label"].startswith("unknown")


def test_funding_zero_only_inside_measured_window(fx):
    p = fx.instrument("NVDAUSDT", "USDT-FUTURES")
    sat = cr.funding_note(p, _ms(2026, 10, 10, 10))       # next slot Sat 16:00 UTC
    assert sat["measured_zero"] and "13 of 13" in sat["text"] and "not measured" not in sat["text"]
    fri = cr.funding_note(p, _ms(2026, 10, 9, 20))        # next slot Sat 00:00 UTC: not in the window
    assert not fri["measured_zero"]
    other = cr.funding_note(p.model_copy(update={"symbol": "AAPLUSDT"}), _ms(2026, 10, 10, 10))
    assert "AAPLUSDT itself was not measured" in other["text"]


def test_recorded_capture_reads_back_as_replay_native():
    books = list(mk.books_from_jsonl(FIX / "capture_sample.jsonl"))
    assert books and all(b.provenance is Provenance.REPLAY_NATIVE for b in books)
    assert all(b.mid is not None for b in books)
