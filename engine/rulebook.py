"""Versioned rulebook with a hash-chained, append-only event log.

States: ACCEPTED (court passed, waiting for the owner) -> ARMED (owner clicked) ->
PENDING_RETIREMENT (proposed, still active) -> RETIRED (owner confirmed).
Court rejections go to QUARANTINED with the reason. Nothing arms, retires or
reverts without an `approved_by` value, and the log is hash-chained so a past
change cannot be edited unnoticed. Paper only: no state here places an order.
"""
from __future__ import annotations

import functools
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field

from .court import Rule, Verdict

STATES = ("ACCEPTED", "ARMED", "PENDING_RETIREMENT", "RETIRED", "QUARANTINED", "UNDERPOWERED")
ACTIVE = ("ARMED", "PENDING_RETIREMENT")          # a rule pending retirement still guards orders


class RulebookError(ValueError):
    pass


def _h(prev: str, body: dict) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


def evidence_hash(v: Verdict) -> str:
    """Hash of the facts that justified the decision (what the court saw)."""
    body = {"rule": v.rule.model_dump(), "status": v.status, "train": v.train, "test": v.test, "p": v.p, "trials": v.trials}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class Entry:
    rule_id: str
    versions: list[dict] = field(default_factory=list)   # {version, rule, evidence, at_ms, reason}
    state: str = "PROPOSED"

    @property
    def current(self) -> dict:
        return self.versions[-1]


def _locked(fn):
    """Serialise a mutator: two threads must never get the same rule id or fork the hash chain."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self.lock:
            return fn(self, *a, **kw)
    return wrapper


class Rulebook:
    def __init__(self, owner: str = "session"):
        self.lock = threading.RLock()
        self.owner = owner
        self.entries: dict[str, Entry] = {}
        self.log: list[dict] = []
        self.proposed_count = 0            # every proposal counts, accepted or not (trial-count ledger)
        self.rules_tried: list[Rule] = []  # the proposals behind that count

    # -- log ------------------------------------------------------------------
    @_locked
    def _emit(self, kind: str, rule_id: str, **data) -> None:
        prev = self.log[-1]["hash"] if self.log else "GENESIS"
        body = {"seq": len(self.log) + 1, "at_ms": int(time.time() * 1000), "kind": kind, "rule_id": rule_id, **data}
        self.log.append({**body, "prev": prev, "hash": _h(prev, body)})

    @_locked
    def verify_chain(self) -> bool:
        prev = "GENESIS"
        for e in self.log:
            body = {k: v for k, v in e.items() if k not in ("prev", "hash")}
            if e["prev"] != prev or e["hash"] != _h(prev, body):
                return False
            prev = e["hash"]
        return True

    # -- court results -----------------------------------------------------------
    @_locked
    def record_verdict(self, v: Verdict) -> Entry:
        """Put a court verdict into the book. Every call counts as a proposal."""
        self.proposed_count += 1
        rid = f"R{len(self.entries) + 1}"
        state = {"ACCEPTED": "ACCEPTED", "REJECTED": "QUARANTINED", "UNDERPOWERED": "UNDERPOWERED"}[v.status]
        e = Entry(rid, [{"version": 1, "rule": v.rule.model_dump(), "evidence": evidence_hash(v), "at_ms": int(time.time() * 1000),
                         "reason": v.reason}], state)
        self.entries[rid] = e
        self._emit("verdict", rid, state=state, evidence=e.current["evidence"], reason=v.reason, trials=v.trials)
        return e

    # -- human-approved transitions ------------------------------------------------
    def _need(self, rule_id: str, approved_by: str, allowed: tuple[str, ...], action: str) -> Entry:
        if not approved_by or not approved_by.strip():
            raise RulebookError(f"{action} needs the owner's explicit approval")
        e = self.entries.get(rule_id)
        if e is None:
            raise RulebookError(f"unknown rule {rule_id}")
        if e.state not in allowed:
            raise RulebookError(f"cannot {action} a rule in state {e.state}")
        return e

    @_locked
    def arm(self, rule_id: str, approved_by: str) -> Entry:
        e = self._need(rule_id, approved_by, ("ACCEPTED",), "arm")
        e.state = "ARMED"
        self._emit("arm", rule_id, by=approved_by, version=e.current["version"])
        return e

    @_locked
    def propose_retirement(self, rule_id: str, reason: str) -> Entry:
        e = self.entries.get(rule_id)
        if e is None or e.state != "ARMED":
            raise RulebookError("only an armed rule can be proposed for retirement")
        e.state = "PENDING_RETIREMENT"
        self._emit("retire_proposed", rule_id, reason=reason)
        return e

    @_locked
    def confirm_retirement(self, rule_id: str, approved_by: str) -> Entry:
        e = self._need(rule_id, approved_by, ("PENDING_RETIREMENT",), "retire")
        e.state = "RETIRED"
        self._emit("retire", rule_id, by=approved_by)
        return e

    @_locked
    def keep(self, rule_id: str, approved_by: str) -> Entry:
        """Owner declines a retirement proposal: the rule stays armed."""
        e = self._need(rule_id, approved_by, ("PENDING_RETIREMENT",), "keep")
        e.state = "ARMED"
        self._emit("retire_declined", rule_id, by=approved_by)
        return e

    @_locked
    def revise(self, rule_id: str, new_rule: Rule, v: Verdict, approved_by: str) -> Entry:
        """v1 -> v2: a changed rule needs its own court verdict; changelog keeps the old version."""
        e = self._need(rule_id, approved_by, ("ACCEPTED", "ARMED", "PENDING_RETIREMENT"), "revise")
        self.proposed_count += 1
        if v.status != "ACCEPTED":
            raise RulebookError(f"revision not accepted by the court ({v.status}); the current version stays")
        e.versions.append({"version": len(e.versions) + 1, "rule": new_rule.model_dump(), "evidence": evidence_hash(v),
                           "at_ms": int(time.time() * 1000), "reason": v.reason})
        self._emit("revise", rule_id, by=approved_by, version=len(e.versions), evidence=e.current["evidence"])
        return e

    @_locked
    def revert(self, rule_id: str, approved_by: str) -> Entry:
        e = self._need(rule_id, approved_by, ("ACCEPTED", "ARMED", "PENDING_RETIREMENT"), "revert")
        if len(e.versions) < 2:
            raise RulebookError("no earlier version to revert to")
        gone = e.versions.pop()
        self._emit("revert", rule_id, by=approved_by, removed_version=gone["version"], now_version=e.current["version"])
        return e

    # -- views -----------------------------------------------------------------
    @_locked
    def active_rules(self) -> list[tuple[str, Rule]]:
        return [(rid, Rule(**e.current["rule"])) for rid, e in self.entries.items() if e.state in ACTIVE]

    @_locked
    def summary(self) -> dict:
        return {"proposed": self.proposed_count, "entries": [
            {"rule_id": rid, "state": e.state, "version": e.current["version"], "rule": e.current["rule"], "reason": e.current["reason"],
             "evidence": e.current["evidence"], "changelog": [{"version": x["version"], "rule": x["rule"], "evidence": x["evidence"], "reason": x["reason"]} for x in e.versions]}
            for rid, e in self.entries.items()],
            "chain_ok": self.verify_chain(), "events": len(self.log)}
