import json
from pathlib import Path

import pytest

from engine.ledger_drift import DEFAULT_THRESHOLD_FRAC, classify, reconcile


def _samples() -> Path:
    # walk up from this file so the test works from the main checkout and from a worktree
    for p in Path(__file__).resolve().parents:
        cand = p / "tests" / "fixtures" / "bitget_samples" / "ccxt_mit" / "ccxt_bitget_uta_real_responses.json"
        if cand.exists():
            return cand
    pytest.skip("ccxt sample file not found")


def _real_items():
    return json.loads(_samples().read_text(encoding="utf-8"))["items"]


def _real_rows(endpoint_prefix):
    return [r for i in _real_items() if str(i.get("endpoint", "")).startswith(endpoint_prefix)
            and i.get("httpResponse") for r in (i["httpResponse"]["data"]["list"] or [])]


@pytest.mark.parametrize("t,expected", [
    ("CONTRACT_MAIN_SETTLE_FEE_USER_OUT", "FUNDING"),
    ("CONTRACT_MAIN_SETTLE_FEE_USER_IN", "FUNDING"),
    ("MARGIN_SETTLE_FEE_USER_IN", "FUNDING"),
    ("FIXED_SETTLE_FEE_USER_OUT", "FUNDING"),
    ("RWA_CONTRACT_MAIN_SETTLE_FEE_USER_IN", "FUNDING"),   # real but undocumented (SCHEMA.md S5)
    ("OPEN_LONG", "TRADE"), ("CLOSE_SHORT", "TRADE"), ("BUY_DEAL", "TRADE"), ("BURST_CLOSE_LONG", "TRADE"),
    ("ORDER_DEALT_IN", "TRADE"), ("FIXED_ADL_CLOSE_SHORT", "TRADE"),
    ("LIQ_FEE", "LIQUIDATION_FEE"),
    ("TRANSFER_IN", "TRANSFER"), ("TRANSFER_OUT", "TRANSFER"), ("deposit", "TRANSFER"), ("transfer_out", "TRANSFER"),
    ("TRACE_SHARE_BENEFIT_IN", "REBATE_AIRDROP_OTHER"), ("AIRDROP_REWARD", "REBATE_AIRDROP_OTHER"),
    ("SOMETHING_NEW", "UNCLASSIFIED"),
])
def test_classify_types(t, expected):
    assert classify({"type": t}) == expected


def test_real_funding_row_is_classified_and_reconciles():
    rows = _real_rows("GET /api/v3/account/financial-records")
    assert len(rows) == 1 and rows[0]["type"] == "CONTRACT_MAIN_SETTLE_FEE_USER_OUT"
    assert classify(rows[0]) == "FUNDING"
    start = 59981.7105387860399993 + 0.31399125      # balance before = balance after - amount (from the row)
    r = reconcile(rows, trade_pnl=0.0, trade_fees=0.0, balance_change=-0.31399125, start_equity=start)
    assert r.totals["FUNDING"] == pytest.approx(-0.31399125)
    assert r.status == "RECONCILED" and r.residual == pytest.approx(0.0, abs=1e-12)


def test_real_funding_wallet_rows_are_transfers_including_blank_type():
    rows = _real_rows("GET /api/v3/account/funding-financial-records")
    assert len(rows) == 4 and any(x["type"] == "" for x in rows)
    assert all(classify(x) == "TRANSFER" for x in rows)


def test_unexplained_residual_is_reported_never_plugged():
    rows = [{"id": "1", "type": "CONTRACT_MAIN_SETTLE_FEE_USER_OUT", "amount": "-2", "fee": "0"},
            {"id": "2", "type": "TRANSFER_IN", "amount": "100", "fee": "0"},
            {"id": "3", "type": "CLOSE_LONG", "amount": "40", "fee": "-1"}]       # cross-check only
    # trading: +40 realised, 1 fee -> 39; funding -2; transfer +100 -> explained 137. Balance moved 132.
    r = reconcile(rows, trade_pnl=40.0, trade_fees=1.0, balance_change=132.0, start_equity=1000.0)
    assert r.explained == pytest.approx(137.0)
    assert r.residual == pytest.approx(-5.0)
    assert r.status == "UNEXPLAINED"
    assert r.totals["TRADE"] == pytest.approx(39.0)              # reported, not added
    assert sum(r.totals[c] for c in ("FUNDING", "TRANSFER", "REBATE_AIRDROP_OTHER", "LIQUIDATION_FEE")) == \
        pytest.approx(98.0)                                     # the 5 was not pushed into any category
    assert r.threshold == pytest.approx(1000.0 * DEFAULT_THRESHOLD_FRAC)


def test_threshold_is_configurable_and_unclassified_rows_surface():
    rows = [{"id": "1", "type": "MYSTERY", "amount": "5", "fee": "0"}]
    r = reconcile(rows, 0.0, 0.0, balance_change=5.0, start_equity=1000.0)   # threshold 1.0 by default
    assert r.status == "UNEXPLAINED" and r.unclassified_types == ["MYSTERY"] and r.residual == pytest.approx(5.0)
    assert r.totals["UNCLASSIFIED"] == 5.0
    loose = reconcile(rows, 0.0, 0.0, balance_change=5.0, start_equity=1000.0, threshold_frac=0.01)
    assert loose.status == "RECONCILED"


def test_duplicate_rows_are_dropped_and_coin_filter_applies():
    rows = [{"id": "1", "coin": "USDT", "type": "TRANSFER_IN", "amount": "10"},
            {"id": "1", "coin": "USDT", "type": "TRANSFER_IN", "amount": "10"},
            {"id": "2", "coin": "BTC", "type": "TRANSFER_IN", "amount": "1"}]
    r = reconcile(rows, 0.0, 0.0, balance_change=10.0, start_equity=100.0, coin="USDT")
    assert r.duplicates_dropped == 1 and r.totals["TRANSFER"] == 10.0 and r.status == "RECONCILED"
