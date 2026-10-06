from adapters.hyperliquid_csv import load
from engine import detectors, ledger
from engine.court import Court, Rule
from engine.planted import planted_trader
from engine.schema import Fill, Provenance


def _fill(i, t, side, is_open, px, sz, start, pnl=0.0, fee=0.1, oid=None, sym="X"):
    return Fill(venue="t", account="a", exec_id=str(i), order_id=oid or str(i), t_ms=t, symbol=sym, side=side,
                is_open=is_open, price=px, size=sz, fee=fee, realized_pnl=pnl, start_position=start,
                provenance=Provenance.SIM_PLANTED)


def test_round_trip_flat_to_flat_and_fees_included():
    fills = [
        _fill(1, 1000, "buy", True, 10, 5, 0.0),
        _fill(2, 2000, "buy", True, 11, 5, 5.0),
        _fill(3, 3000, "sell", False, 12, 10, 10.0, pnl=15.0),
    ]
    trips = ledger.to_round_trips(fills)
    assert len(trips) == 1
    assert trips[0].net_pnl == 15.0 - 0.3          # realised minus all three fees
    assert trips[0].first_order_notional == 50.0
    assert trips[0].opened_notional == 50.0 + 55.0


def test_mid_position_start_is_skipped_not_guessed():
    fills = [_fill(1, 1000, "sell", False, 10, 5, 5.0, pnl=3.0), _fill(2, 2000, "buy", True, 10, 5, 0.0),
             _fill(3, 3000, "sell", False, 11, 5, 5.0, pnl=5.0)]
    trips = ledger.to_round_trips(fills)
    assert len(trips) == 1 and trips[0].t_open_ms == 2000


def test_dedupe_by_account_and_exec_id():
    f = _fill(1, 1000, "buy", True, 10, 5, 0.0)
    assert len(ledger.dedupe([f, f])) == 1


def test_real_wallet_loads_with_public_label():
    fills = load("deploy_data/trader_samples/wallet_A.csv")
    assert fills and all(x.provenance is Provenance.REAL_PLATFORM_PUBLIC for x in fills)


def test_detector_finds_planted_size_leak_and_not_the_control():
    leaky = planted_trader(n=400, size_mult=3.0, seed=1)
    control = planted_trader(n=400, size_mult=1.0, seed=1)
    assert detectors.size_after_loss(leaky, n_perm=800).status == "FLAGGED"
    assert detectors.size_after_loss(control, n_perm=800).status == "NOT_FLAGGED"


def test_court_accepts_costly_leak_rejects_costless_habit_and_null():
    # costly: sizes up after a loss AND does worse after a loss -> the cap helps on held-out trades
    costly = planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=2)
    # costless: sizes up but returns are unchanged -> detector may flag, court must not accept
    costless = planted_trader(n=600, size_mult=3.0, tilt=0.0, seed=3)
    null = planted_trader(n=600, size_mult=1.0, tilt=0.0, seed=4)
    c = Court(n_perm=800)
    c.propose(Rule(value=1.5))
    assert c.judge(costly, Rule(value=1.5)).status == "ACCEPTED"
    assert Court(n_perm=800).judge(costless, Rule(value=1.5)).status != "ACCEPTED"
    assert Court(n_perm=800).judge(null, Rule(value=1.5)).status != "ACCEPTED"


def test_trial_ledger_deflates_the_threshold():
    c = Court(n_perm=200)
    for m in (1.0, 1.5, 2.0, 3.0):
        c.propose(Rule(value=m))
    v = c.judge(planted_trader(n=300, size_mult=1.0, seed=5), Rule(value=1.5))
    assert v.trials == 4 and abs(v.alpha_used - 0.05 / 4) < 1e-12


def test_small_samples_are_underpowered_not_flagged():
    tiny = planted_trader(n=40, size_mult=3.0, tilt=-0.006, seed=6)
    assert Court(n_perm=200).judge(tiny, Rule(value=1.5)).status == "UNDERPOWERED"
