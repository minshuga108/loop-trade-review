import pytest

from engine import checklist, gate, rulebook
from engine.court import Court, Rule
from engine.planted import planted_trader


def _verdicts():
    trips = planted_trader(n=600, size_mult=3.0, tilt=-0.006, seed=2)
    c = Court(n_perm=400)
    for m in (1.0, 1.5, 2.0, 3.0):
        c.propose(Rule(value=m))
    out = {m: c.judge(trips, Rule(value=m)) for m in (1.0, 1.5)}
    null = planted_trader(n=600, size_mult=1.0, tilt=0.0, seed=4)       # a trader with no leak: the court must not accept
    out[3.0] = c.judge(null, Rule(value=3.0))
    return trips, c, out


def test_nothing_arms_without_owner_approval_and_only_accepted_rules_arm():
    trips, c, v = _verdicts()
    rb = rulebook.Rulebook()
    e = rb.record_verdict(v[1.5])
    assert e.state == "ACCEPTED"
    with pytest.raises(rulebook.RulebookError):
        rb.arm(e.rule_id, "")                          # no approval, no arming
    rb.arm(e.rule_id, "owner")
    assert rb.entries[e.rule_id].state == "ARMED"
    q = rb.record_verdict(v[3.0])                      # not accepted -> never armable
    assert q.state != "ACCEPTED"
    with pytest.raises(rulebook.RulebookError):
        rb.arm(q.rule_id, "owner")


def test_retirement_is_proposed_then_confirmed_and_rule_keeps_guarding_meanwhile():
    trips, c, v = _verdicts()
    rb = rulebook.Rulebook()
    e = rb.record_verdict(v[1.5]); rb.arm(e.rule_id, "owner")
    rb.propose_retirement(e.rule_id, "no effect seen")
    assert rb.entries[e.rule_id].state == "PENDING_RETIREMENT" and rb.active_rules()      # still active
    with pytest.raises(rulebook.RulebookError):
        rb.confirm_retirement(e.rule_id, " ")
    rb.keep(e.rule_id, "owner"); assert rb.entries[e.rule_id].state == "ARMED"
    rb.propose_retirement(e.rule_id, "again"); rb.confirm_retirement(e.rule_id, "owner")
    assert rb.entries[e.rule_id].state == "RETIRED" and not rb.active_rules()


def test_revision_needs_an_accepted_court_verdict_and_revert_restores():
    trips, c, v = _verdicts()
    rb = rulebook.Rulebook()
    e = rb.record_verdict(v[1.5]); rb.arm(e.rule_id, "owner")
    rb.revise(e.rule_id, Rule(value=1.0), v[1.0], "owner")
    assert rb.entries[e.rule_id].current["version"] == 2 and rb.active_rules()[0][1].value == 1.0
    rb.revert(e.rule_id, "owner")
    assert rb.entries[e.rule_id].current["version"] == 1 and rb.active_rules()[0][1].value == 1.5
    with pytest.raises(rulebook.RulebookError):
        rb.revise(e.rule_id, Rule(value=3.0), v[3.0], "owner")      # underpowered/rejected revision refused


def test_hash_chain_detects_tampering():
    trips, c, v = _verdicts()
    rb = rulebook.Rulebook()
    e = rb.record_verdict(v[1.5]); rb.arm(e.rule_id, "owner")
    assert rb.verify_chain()
    rb.log[0]["reason"] = "edited"
    assert not rb.verify_chain()


def test_proposal_counter_counts_every_proposal():
    trips, c, v = _verdicts()
    rb = rulebook.Rulebook()
    for m in (1.0, 1.5, 3.0):
        rb.record_verdict(v[m])
    assert rb.proposed_count == 3


def test_checklist_cap_selection_and_measurement_gates():
    trips = planted_trader(n=700, size_mult=3.0, tilt=-0.006, seed=7)
    items = checklist.generate([{"status": "FLAGGED", "detector": "size_after_loss"}, {"status": "FLAGGED", "detector": "hold_asymmetry"}], [])
    assert len(items) <= checklist.MAX_ACTIVE
    assert len(checklist.select_for_order(items, after_loss=True)) <= checklist.MAX_SHOWN
    import numpy as np
    med = float(np.median([t.first_order_notional for t in trips]))
    m = checklist.measure(items[0], trips, med)
    assert m["status"] in ("MEASURED", "NOT_ENOUGH_TRADES")
    small = checklist.measure(items[0], trips[:40], med)
    assert small["status"] == "NOT_ENOUGH_TRADES"                     # never states an effect on thin data


def test_gate_parses_orders_and_blocks_on_armed_rule():
    idea = gate.parse_order("Buy $20k rNVDA")
    assert idea.side == "buy" and idea.notional == 20000 and idea.symbol == "RNVDA"
    zh = gate.parse_order("买 2万 TSLA")
    assert zh.notional == 20000 and zh.symbol == "TSLA"
    items = checklist.generate([{"status": "FLAGGED", "detector": "size_after_loss"}], [])
    r = gate.check(idea, [("R1", Rule(value=1.5))], items, median_notional=5000, last_trip_was_loss=True, flagged=["size_after_loss"])
    assert r.state == "BLOCKED_BY_YOUR_RULES" and r.paper_only and r.broken_rules == ["R1"]
    ok = gate.check(gate.parse_order("buy 3k NVDA"), [("R1", Rule(value=1.5))], items, 5000, True, [])
    assert ok.state in ("CHECKS_PASSED", "CHECKS_PASSED_WITH_NOTES")
    assert gate.check(idea, [], [], 5000, False, []).state == "CHECKS_PASSED"


def test_review_needed_needs_two_independent_evidence_items():
    idea = gate.parse_order("buy 9k NVDA")
    r = gate.check(idea, [], [], 5000, True, ["size_after_loss"], cost_line={"cost_bps": 80.0, "limit_bps": 30})
    assert r.state == "REVIEW_NEEDED" and len(r.evidence_items) == 2
    one = gate.check(idea, [], [], 5000, True, ["size_after_loss"])
    assert one.state == "CHECKS_PASSED_WITH_NOTES"
