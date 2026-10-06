import csv
from pathlib import Path

import pytest

from adapters import bitget_csv_en as c
from adapters.bitget_uta import SchemaDrift
from engine import ledger

SAMPLE = Path(__file__).resolve().parents[1] / "deploy_data" / "real_bitget" / "doge_trades_analysis.csv"


def test_header_drift_is_refused(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Date,Order ID,Direction\n2025-01-01 00:00:00,1,Open long\n", encoding="utf-8")
    with pytest.raises(SchemaDrift):
        c.parse(p)


def test_synthetic_roundtrip_net_uses_close_fee_only_and_flags_missing_open_fee(tmp_path):
    p = tmp_path / "s.csv"
    hdr = ["Date", "Order ID", "Direction", "Coin", "Futures", "order source", "Transaction type", "Price", "Average Price",
           "Order amount", "Executed", "Trading volume", "Realized P/L", "NetProfits", "Status"]
    rows = [["2025-01-01 00:00:00", "\t1", "Open long", "USDT", "BTCUSDT", "GTC", "Market", "", "100", "2", "2", "200", "0", "0", "fully executed"],
            ["2025-01-01 01:00:00", "\t2", "Close long", "USDT", "BTCUSDT", "GTC", "Market", "", "110", "2", "2", "220", "20", "19.868", "fully executed"],
            ["2025-01-01 02:00:00", "\t3", "Open long", "USDT", "BTCUSDT", "GTC", "Market", "", "100", "1", "0", "0", "0", "0", "cancelled"]]
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(hdr); w.writerows(rows)
    fills, notes = c.parse(p)
    assert len(fills) == 2 and notes["skipped_unfilled"] == 1 and notes["open_fees_missing"] is True
    trips = ledger.to_round_trips(ledger.dedupe(fills))
    assert len(trips) == 1 and abs(trips[0].net_pnl - 19.868) < 1e-9       # gross 20 minus the 0.132 close fee


@pytest.mark.skipif(not SAMPLE.exists(), reason="real sample not present")
def test_real_english_export_reconciles_to_netprofits():
    fills, notes = c.parse(SAMPLE)
    trips = ledger.to_round_trips(ledger.dedupe(fills))
    with SAMPLE.open(newline="", encoding="utf-8-sig") as fh:
        net_total = sum(float(r["NetProfits"]) for r in csv.DictReader(fh) if r["Direction"].startswith("Close"))
    assert len(trips) >= 60
    assert abs(sum(t.net_pnl for t in trips) - net_total) < 0.05          # every close counted once, none invented
    assert notes["open_fees_missing"] is True
