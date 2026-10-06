import json
from pathlib import Path

import pytest

from adapters import bitget_uta as b
from engine.schema import Provenance

SAMPLES = Path(__file__).parent / "fixtures" / "bitget_samples"


def _ccxt_items():
    d = json.loads((SAMPLES / "ccxt_mit" / "ccxt_bitget_uta_real_responses.json").read_text(encoding="utf-8"))
    return d["items"]


def _resp(endpoint):
    return [i["httpResponse"] for i in _ccxt_items() if i.get("endpoint") == endpoint and i.get("httpResponse")]


def test_real_ccxt_fills_parse_with_positive_fee_and_missing_tradeside():
    resps = _resp("GET /api/v3/trade/fills")
    fills = [f for r in resps for f in b.parse_fills(r, "ccxt-demo")]
    assert len(fills) >= 2
    assert all(f.fee > 0 and f.venue == "bitget" and f.provenance is Provenance.REAL_OWN for f in fills)
    assert all(f.symbol == "BTCUSDT" for f in fills)


def test_real_ccxt_positions_satisfy_net_identity_and_normalise_fee_sign():
    pos = [p for r in _resp("GET /api/v3/position/history-position") for p in b.parse_positions(r)]
    assert len(pos) >= 2
    for p in pos:
        assert p.fees > 0                                  # stored negative by Bitget, normalised to a cost
        assert abs(p.net_pnl - (p.gross_pnl - p.fees + p.funding)) < 0.01


def test_trips_from_positions_use_net_pnl_and_fall_back_without_fills():
    pos = [p for r in _resp("GET /api/v3/position/history-position") for p in b.parse_positions(r)]
    trips = b.trips_from_positions(pos, [])
    assert len(trips) == len(pos)
    assert all(t.first_order_notional == t.opened_notional for t in trips)   # no fills: nothing guessed


def test_empty_page_with_null_list_is_empty_not_an_error():
    assert b.parse_fills({"code": "00000", "msg": "success", "data": {"list": None, "cursor": None}}, "x") == []


def test_schema_drift_is_refused_loudly():
    with pytest.raises(b.SchemaDrift):
        b.parse_fills({"code": "00000", "data": {"list": [{"execId": "1"}]}}, "x")
    with pytest.raises(b.SchemaDrift):
        b.parse_fills({"code": "40014", "msg": "Incorrect permissions", "data": {}}, "x")
    bad = {"code": "00000", "data": {"list": [{"positionId": "1", "symbol": "BTCUSDT", "posSide": "long",
           "createdTime": "1", "updatedTime": "2", "netProfit": "5", "cumRealisedPnl": "-1", "openFeeTotal": "-0.1",
           "closeFeeTotal": "-0.1", "totalFunding": "0"}]}}
    with pytest.raises(b.SchemaDrift):
        b.parse_positions(bad)                             # net identity broken -> convention changed


def test_doc_example_schema_only_rows_parse():
    txt = (SAMPLES / "jkorf_mit_doc_examples" / "GetUserTrades.txt").read_text(encoding="utf-8")
    body = txt[txt.index('{\n  "code"'):]               # skip the "UriParams: {...}" header line
    fills = b.parse_fills(json.loads(body), "doc-example", Provenance.SIM_PAPER)
    assert fills and fills[0].provenance is Provenance.SIM_PAPER
