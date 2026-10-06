"""Round-3 audit items 5, 6, 8, 9: headline consistency, suggestive falsify, unit-safe gate, tagged record."""
import time

from app import costs, record_api, service
from engine import gate as gate_mod
from engine import report
from engine.record import RecordLog


def test_headline_never_says_no_habit_over_an_accepted_rule():
    priced = {"held_out_effect": 4804.0, "status": "ACCEPTED"}
    t = service._plain(None, None, priced, {"accepted": 2, "tested": 4})
    assert "No habit passes" in t and "accepted that rule" in t and "without calling it a habit" in t
    assert "Separately" in t
    t2 = service._plain(None, None, {"held_out_effect": 5539.0, "status": "REJECTED"}, {"accepted": 1, "tested": 4})
    assert "1 of the 4 caps" in t2


def test_every_wallet_headline_is_consistent():
    for t in service.traders():
        if not t.get("available"):
            continue
        h = service.review(t["id"])["headline"]
        if "No habit passes" in h["plain"]:
            assert h["priced"]["status"] != "ACCEPTED" or "without calling it a habit" in h["plain"]


def _sug(p=0.02, pa=0.06, na=40, nb=60):
    return {"detector": "size_after_loss", "status": "SUGGESTIVE", "p": p, "p_adj": pa, "n_a": na, "n_b": nb, "ratio": 1.3, "ci": [1.0, 1.6]}


def test_trips_needed_is_computed_and_grows_with_the_gap():
    tn = report.trips_needed(_sug())
    assert tn["n_now"] == 100 and tn["n_needed"] > 100
    assert report.trips_needed(_sug(p=0.04, pa=0.12))["n_needed"] > tn["n_needed"]
    assert report.trips_needed({**_sug(), "p": None}) is None


def test_suggestive_falsify_says_what_confirms_or_kills_it():
    rv = service.review("B") if any(f["status"] == "SUGGESTIVE" for f in service.review("B")["findings"]) else None
    if rv is None:                                 # build a minimal review around a suggestive finding
        rv = {k: v for k, v in service.review("B").items()}
        rv["findings"] = [_sug()]
    md = report.build(rv)["markdown"]
    assert "What would confirm it" in md and "nothing to disprove" not in md.lower()
    assert "Rough projection" in md or "cannot honestly estimate" in md


def test_quantity_is_not_read_as_dollars():
    i = gate_mod.parse_order("buy 100 DOGE")
    assert i.notional is None and i.quantity == 100 and i.symbol == "DOGE"
    assert gate_mod.parse_order("Buy $100 DOGE").notional == 100
    assert gate_mod.parse_order("buy 100 USDT of DOGE").notional == 100
    assert gate_mod.parse_order("Buy $20k rNVDA").notional == 20000
    r = gate_mod.check(i, [], [], 1000.0, False, [])
    assert r.state == "COULD_NOT_CHECK" and "USDT" in r.reasons[0]


def test_quantity_converted_with_cached_price(monkeypatch):
    monkeypatch.setattr(costs, "price_of", lambda s: {"symbol": "BTCUSDT", "price": 50000.0, "age_s": 3})
    monkeypatch.setattr(record_api, "log_gate_decision", lambda *a, **k: {"seq": 1})
    out = service.gate_check("t-s", "F", "buy 3 BTC", False)
    assert out["idea"]["notional"] == 150000.0 and "3 BTC x 50,000.00" in out["idea"]["converted_from"]


def test_quantity_without_price_asks_for_notional(monkeypatch):
    monkeypatch.setattr(costs, "price_of", lambda s: None)
    monkeypatch.setattr(record_api, "log_gate_decision", lambda *a, **k: {"seq": 1})
    out = service.gate_check("t-s", "F", "buy 100 DOGE", False)
    assert out["state"] == "COULD_NOT_CHECK" and out["idea"]["notional"] is None


def test_record_separates_user_decisions_from_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_RECORD_PATH", str(tmp_path / "r.jsonl"))
    record_api._LOGS.clear()
    base = {"state": "CHECKS_PASSED", "idea": {}}
    record_api.log_gate_decision("abc", "F", base)                       # demo wallet click
    record_api.log_gate_decision("judge-1", "F", base)
    record_api.log_gate_decision("testsess", "F", base)
    d = record_api.log_gate_decision("abc", "imp1", base, origin=record_api.classify_origin("abc", "imp1", True))
    record_api.log_outcome(d["seq"], {"result": "x"})
    c = record_api.get_log().counter()
    assert c["decisions_logged"] == 4 and c["user_decisions"] == 1 and c["user_outcomes_resolved"] == 1
    assert c["by_origin"] == {"sandbox": 1, "judge": 1, "test": 1, "user": 1}
    record_api._LOGS.clear()
