from pathlib import Path

import pytest

from adapters import bitget_v2_history as h
from adapters.bitget_uta import SchemaDrift

REAL = Path(__file__).resolve().parents[2] / "data" / "bitget_samples" / "talentan_mpl2_real" / "contract-record_all.json"


def _row(**kw):
    r = {"positionId": "1", "symbol": "BTCUSDT", "holdSide": "short", "openAvgPrice": "100", "openTotalPos": "2",
         "pnl": "10", "netProfit": "9.5", "totalFunding": "0.2", "openFee": "-0.3", "closeFee": "-0.4",
         "ctime": "1000", "utime": "2000", "exchange": "bitget"}
    r.update(kw)
    return r


def test_identity_ok_and_fields():
    trips, notes = h.parse([_row(remark="note", entryReason="x")])
    assert len(trips) == 1 and trips[0].side == "sell" and trips[0].net_pnl == 9.5
    assert trips[0].opened_notional == 200 and notes["1"]["remark"] == "note"


def test_identity_break_is_refused_and_other_exchange_skipped():
    with pytest.raises(SchemaDrift):
        h.parse([_row(netProfit="50")])
    assert h.parse([_row(exchange="binance"), {"positionId": "s", "type": "summery"}])[0] == []


@pytest.mark.skipif(not REAL.exists(), reason="real journal not present")
def test_real_journal_has_53_verified_trips_and_reconciles():
    trips, notes = h.load(REAL)
    assert len(trips) == 53 and h.parse.skipped["hand_entered"] == 47
    assert all(t.opened_notional > 0 for t in trips)
