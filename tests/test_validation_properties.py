"""Property tests (hypothesis, dev-only: skipped when it is not installed) for the ledger, the court and Holm."""
import numpy as np
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from engine import ledger  # noqa: E402
from engine.court import Court, Rule  # noqa: E402
from engine.detectors import after_loss_labels  # noqa: E402
from engine.planted import planted_trader  # noqa: E402
from engine.schema import Fill, Provenance, RoundTrip  # noqa: E402
from engine.stats import holm  # noqa: E402
from engine.walkforward import judge_wf  # noqa: E402

SET = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
money = st.floats(min_value=-500, max_value=500, allow_nan=False, allow_infinity=False)
fee = st.floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False)


@st.composite
def histories(draw, with_open_tail=False):
    """Fills for 1-3 symbols: complete flat-to-flat trips (1-3 opening fills, 1-2 closing fills), optional unfinished tail."""
    fills, expected_net, n_trips, tail_net = [], 0.0, 0, 0.0
    t = 1_700_000_000_000
    ctr = 0
    for sym in draw(st.lists(st.sampled_from(["BTC", "ETH", "SOL"]), min_size=1, max_size=3, unique=True)):
        pos = 0.0
        ntr = draw(st.integers(1, 5))
        for k in range(ntr + (1 if with_open_tail else 0)):
            tail = with_open_tail and k == ntr
            sign = draw(st.sampled_from([1, -1]))
            opens = draw(st.lists(st.integers(1, 20), min_size=1, max_size=3))
            closes = [sum(opens)] if tail is False and draw(st.booleans()) else None
            if closes is None:
                cut = draw(st.integers(1, sum(opens)))
                closes = [cut, sum(opens) - cut] if sum(opens) - cut > 0 else [sum(opens)]
            seq = [(True, o) for o in opens] + ([] if tail else [(False, c) for c in closes])
            net = 0.0
            for is_open, size in seq:
                signed = size if is_open else -size
                signed *= sign
                ctr += 1
                t += draw(st.integers(1, 10_000))
                r, fe = draw(money), draw(fee)
                fills.append(Fill(venue="x", account="a", exec_id=f"e{ctr}", order_id=f"o{ctr}", t_ms=t, symbol=sym,
                                  side="buy" if signed > 0 else "sell", is_open=is_open, price=100.0, size=float(size),
                                  fee=fe, realized_pnl=r, start_position=pos, provenance=Provenance.SIM_PLANTED))
                pos += signed
                net += r - fe
            if tail:
                tail_net += net
            else:
                expected_net += net
                n_trips += 1
            assert tail or abs(pos) < 1e-9
    return fills, expected_net, n_trips


@SET
@given(histories(with_open_tail=True))
def test_round_trips_conserve_net_pnl(h):
    fills, expected_net, n_trips = h
    trips = ledger.to_round_trips(fills)
    assert len(trips) == n_trips
    assert sum(t.net_pnl for t in trips) == pytest.approx(expected_net, abs=1e-6)
    # every fill's pnl and fee lands in exactly one trip or in the ignored unfinished tail: nothing is double counted
    assert sum(t.net_pnl for t in trips) <= sum(f.realized_pnl - f.fee for f in fills) + 1e3 * len(fills)


@SET
@given(histories(), st.randoms(use_true_random=False))
def test_dedupe_idempotent_and_order_free(h, rnd):
    fills = h[0]
    once = ledger.dedupe(fills)
    assert ledger.dedupe(once) == once
    noisy = list(fills) + [rnd.choice(fills) for _ in range(len(fills))]
    rnd.shuffle(noisy)
    assert ledger.dedupe(noisy) == once            # replayed/duplicated/reordered rows change nothing
    assert len({(f.account, f.exec_id) for f in once}) == len(once)
    assert [(f.t_ms, f.exec_id) for f in once] == sorted((f.t_ms, f.exec_id) for f in once)


@SET
@given(histories(), st.randoms(use_true_random=False))
def test_trips_unchanged_by_duplicates(h, rnd):
    fills = h[0]
    a = ledger.to_round_trips(ledger.dedupe(fills))
    b = ledger.to_round_trips(ledger.dedupe(list(fills) + fills[: len(fills) // 2]))
    assert a == b


trip_seed = st.integers(0, 10_000)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(trip_seed, st.integers(60, 200))
def test_after_loss_label_ignores_the_future(seed, n):
    trips = planted_trader(n=n, size_mult=2.0, tilt=-0.004, seed=seed)
    full = after_loss_labels(trips)
    for i in range(10, n, 17):
        prefix = after_loss_labels(trips[: i + 1])          # history as of trip i's open: nothing after it
        assert prefix[i] == full[i]
        mutated = list(trips)
        for j in range(i + 1, n):                           # rewrite every later trip's outcome
            t = trips[j]
            mutated[j] = RoundTrip(**{**t.model_dump(), "net_pnl": -t.net_pnl - 1.0})
        assert after_loss_labels(mutated)[i] == full[i]


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(trip_seed, st.integers(0, 4))
def test_court_cap_uses_only_earlier_chunks(seed, fold):
    """Rewriting the sizes and pnl of the LAST out-of-sample chunk must not move the cap applied to that chunk."""
    n = 240
    trips = planted_trader(n=n, size_mult=3.0, tilt=-0.006, seed=seed)
    court = Court(n_perm=50, seed=0)
    base = judge_wf(court, trips, Rule(value=1.5)).test["cap"]
    edges = np.linspace(0, n, 7).astype(int)
    mutated = list(trips)
    for j in range(edges[5], n):
        t = trips[j]
        mutated[j] = RoundTrip(**{**t.model_dump(), "first_order_notional": t.first_order_notional * (10 + fold),
                                  "opened_notional": t.opened_notional * (10 + fold), "net_pnl": t.net_pnl * 7 - 3.0})
    court2 = Court(n_perm=50, seed=0)
    assert judge_wf(court2, mutated, Rule(value=1.5)).test["cap"] == pytest.approx(base)


pvals = st.lists(st.one_of(st.none(), st.floats(0, 1, allow_nan=False)), max_size=15)


@SET
@given(pvals)
def test_holm_monotone_and_bounded(ps):
    adj = holm(ps)
    assert len(adj) == len(ps)
    for p, a in zip(ps, adj):
        assert (a is None) == (p is None)
        if p is not None:
            assert p - 1e-12 <= a <= 1.0
    pairs = sorted((p, a) for p, a in zip(ps, adj) if p is not None)
    adjs = [a for _, a in pairs]
    assert adjs == sorted(adjs)                    # step-down adjusted p-values never decrease with the raw ones
    m = len(pairs)
    if m:
        assert max(adjs) <= min(1.0, m * max(p for p, _ in pairs)) + 1e-12   # never worse than Bonferroni


@SET
@given(st.lists(st.floats(0, 1, allow_nan=False), min_size=1, max_size=10), st.floats(0, 1, allow_nan=False))
def test_holm_adding_a_test_never_helps_the_others(ps, extra):
    before, after = holm(ps), holm(ps + [extra])
    assert all(a2 >= a1 - 1e-12 for a1, a2 in zip(before, after[: len(ps)]))


@SET
@given(st.lists(st.floats(0, 1, allow_nan=False), min_size=2, max_size=10), st.randoms(use_true_random=False))
def test_holm_permutation_equivariant(ps, rnd):
    perm = list(range(len(ps)))
    rnd.shuffle(perm)
    base = holm(ps)
    shuffled = holm([ps[i] for i in perm])
    assert shuffled == pytest.approx([base[i] for i in perm])


def test_holm_matches_statsmodels():
    sm = pytest.importorskip("statsmodels.stats.multitest")
    rng = np.random.default_rng(0)
    for _ in range(200):
        p = np.round(rng.random(int(rng.integers(1, 12))) ** 2, 4)
        assert np.allclose(holm(list(p)), sm.multipletests(p, method="holm")[1], atol=1e-12)
