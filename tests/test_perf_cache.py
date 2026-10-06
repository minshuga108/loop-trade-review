"""The load-test fixes: cached court answers must equal the uncached ones, cached objects must not be
mutable through a response, and a cold review must be computed once however many callers arrive."""
from __future__ import annotations

import threading
import time

import pytest

from app import service
from engine.court import Court, Rule
from engine.walkforward import judge_wf


@pytest.mark.parametrize("rule,n", [("halt", 2), ("halt", 3), ("cap", 2)])
def test_cached_toggle_equals_uncached(rule, n):
    assert service.toggle("F", rule, n) == service._toggle_uncached("F", rule, n)


def test_toggle_result_cannot_poison_the_cache():
    a = service.toggle("F", "halt", 2)
    a["held_out"]["effect"] = 123456789.0
    a["curve_actual"].clear()
    b = service.toggle("F", "halt", 2)
    assert b["held_out"]["effect"] != 123456789.0 and b["curve_actual"]


def test_cached_court_verdict_equals_a_fresh_court():
    trips = service._load("F")[3]
    tried = (1.5, 2.0)
    court = Court(n_perm=1500)
    for m in tried + (3.0,):
        court.propose(Rule(value=m))
    fresh = judge_wf(court, trips, Rule(value=3.0))
    cached = service._judge_cached("F", tried, 3.0)
    assert (cached.status, cached.p, cached.trials, cached.alpha_used, cached.test["effect"]) == \
           (fresh.status, fresh.p, fresh.trials, fresh.alpha_used, fresh.test["effect"])
    assert cached.trials == 3                                      # every earlier proposal still raises the bar


def test_propose_still_counts_every_trial():
    sid = "perf-trials"
    for k in range(4):
        out = service.propose_rule(sid, "F", 1.5)
        assert out["trials"] == k + 1


def test_cold_review_is_computed_once_for_concurrent_callers(monkeypatch):
    calls = []
    real = service._review_uncached

    def slow(tid):
        calls.append(tid)
        time.sleep(0.3)
        return real(tid)
    monkeypatch.setattr(service, "_review_uncached", slow)
    service._REVIEW_CACHE.pop("F", None)
    ts = [threading.Thread(target=service.review, args=("F",)) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert calls == ["F"]


def test_unknown_trader_creates_no_lock():
    before = len(service._RC_FLIGHT)
    for i in range(50):
        with pytest.raises(StopIteration):
            service.review(f"nope-{i}")
    assert len(service._RC_FLIGHT) == before
