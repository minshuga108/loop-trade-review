"""Public record: tamper detection, ordering of outcomes, counter, day roots, OTS receipts (no network)."""
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine import anchor
from engine.record import (GENESIS, RecordError, RecordLog, counter, day_root, merkle_proof, merkle_root,
                           verify_file, verify_merkle_proof)

DAY0 = 1_790_000_000_000          # fixed clock: 2026-09-21 UTC
DAY = 86_400_000


class Clock:
    def __init__(self, t=DAY0):
        self.t = t

    def __call__(self):
        self.t += 1000
        return self.t


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_RECORD_SALT", "test-salt")
    return RecordLog(tmp_path / "rec.jsonl", clock=Clock())


def _decision(log, sid="sess-1", state="BLOCKED_BY_YOUR_RULES"):
    return log.log_decision({"session": log.session_hash(sid), "trader": "F", "state": state,
                             "idea": {"side": "buy", "symbol": "RNVDA", "notional": 200000.0}})


def test_chain_links_and_intact(log):
    a = _decision(log)
    b = log.log_rule_event({"kind": "arm", "rule_id": "R1"})
    assert a["prev_hash"] == GENESIS and b["prev_hash"] == a["hash"] and a["seq"] == 1 and b["seq"] == 2
    assert a["payload"]["provenance"] == "SIM_PAPER"
    v = verify_file(log.path)
    assert v["intact"] and v["entries"] == 2 and v["first_bad_seq"] is None and v["head"] == b["hash"]


def test_session_never_raw(log):
    e = _decision(log, sid="my-secret-session")
    assert "my-secret-session" not in log.path.read_text(encoding="utf-8")
    assert e["payload"]["session"].startswith("s_")
    with pytest.raises(RecordError):
        log.log_decision({"session": "my-secret-session"})
    with pytest.raises(RecordError):
        log.log_decision({"provenance": "LIVE"})


def test_one_character_edit_is_caught_at_that_seq(log):
    for _ in range(4):
        _decision(log)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace("200000.0", "200001.0")        # one character in seq 3
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    v = verify_file(log.path)
    assert not v["intact"] and v["first_bad_seq"] == 3 and "edited" in v["reason"]


def test_rehashing_the_edit_breaks_the_next_link(log):
    for _ in range(3):
        _decision(log)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["payload"]["state"] = "CHECKS_PASSED"
    from engine.record import canonical, entry_hash
    e["hash"] = entry_hash(e)
    lines[1] = canonical(e)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    v = verify_file(log.path)
    assert not v["intact"] and v["first_bad_seq"] == 3 and "prev_hash" in v["reason"]


def test_deleted_line_and_reorder_caught(log):
    for _ in range(3):
        _decision(log)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert verify_file(log.path)["first_bad_seq"] == 2


def test_outcome_rules(log):
    rule = log.log_rule_event({"kind": "arm", "rule_id": "R1"})
    with pytest.raises(RecordError):                       # nothing to resolve yet
        log.log_outcome(1, {"result": "x"})
    with pytest.raises(RecordError):                       # a rule event is not a decision
        log.log_outcome(rule["seq"], {"result": "x"})
    with pytest.raises(RecordError):                       # a future seq
        log.log_outcome(99, {"result": "x"})
    d = _decision(log)
    with pytest.raises(RecordError):                       # cannot be dated before its decision
        log.log_outcome(d["seq"], {"result": "x"}, ts_ms=d["ts_ms"] - 5000)
    o = log.log_outcome(d["seq"], {"result": "price moved against the idea"})
    assert o["seq"] > d["seq"]
    with pytest.raises(RecordError):                       # never rewritten
        log.log_outcome(d["seq"], {"result": "changed my mind"})
    assert verify_file(log.path)["intact"]


def test_forged_outcome_before_decision_fails_verify(log):
    d = _decision(log)
    log.log_outcome(d["seq"], {"result": "ok"})
    from engine.record import canonical, entry_hash
    lines = log.path.read_text(encoding="utf-8").splitlines()
    # swap so the outcome comes first, re-chained perfectly by a forger
    out, dec = json.loads(lines[1]), json.loads(lines[0])
    out.update(seq=1, prev_hash=GENESIS)
    out["hash"] = entry_hash(out)
    dec.update(seq=2, prev_hash=out["hash"])
    dec["hash"] = entry_hash(dec)
    log.path.write_text(canonical(out) + "\n" + canonical(dec) + "\n", encoding="utf-8")
    v = verify_file(log.path)
    assert not v["intact"] and v["first_bad_seq"] == 1 and "outcome" in v["reason"]


def test_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_RECORD_SALT", "s")
    clk = Clock()
    log = RecordLog(tmp_path / "c.jsonl", clock=clk)
    d1, d2, d3 = _decision(log), _decision(log), _decision(log)
    log.log_rule_event({"kind": "arm", "rule_id": "R1"})
    clk.t += 2 * DAY
    log.log_outcome(d2["seq"], {"result": "held"})
    c = counter(log.path, clk.t)
    assert (c["decisions_logged"], c["outcomes_resolved"], c["pending"], c["rule_events"], c["entries"]) == (3, 1, 2, 1, 5)
    assert c["days_running"] == 3 and c["days_with_entries"] == 2
    assert counter(tmp_path / "empty.jsonl", clk.t)["days_running"] == 0


def test_day_root_deterministic_and_proofs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_RECORD_SALT", "s")
    roots = []
    for name in ("a.jsonl", "b.jsonl"):
        log = RecordLog(tmp_path / name, clock=Clock())
        for _ in range(5):
            _decision(log)
        log.append("rule_event", {"kind": "arm"}, ts_ms=DAY0 + DAY)       # next day: not in today's root
        roots.append(day_root(log.path, "2026-09-21"))
    assert roots[0] == roots[1] and roots[0]["n"] == 5 and roots[0]["last_seq"] == 5
    hs = [e["hash"] for e in RecordLog(tmp_path / "a.jsonl").entries()[:5]]
    assert merkle_root(hs) == roots[0]["root"]
    for i in range(5):
        assert verify_merkle_proof(hs[i], merkle_proof(hs, i), roots[0]["root"])
    assert not verify_merkle_proof(hs[0], merkle_proof(hs, 1), roots[0]["root"])
    assert merkle_root(hs[:4]) != merkle_root(hs[:4] + [hs[3]])            # no duplicate-last ambiguity
    assert day_root(tmp_path / "a.jsonl", "2020-01-01")["n"] == 0


# ---- OpenTimestamps with a mock calendar ---------------------------------------------------------
PENDING_URI = "https://alice.btc.calendar.opentimestamps.org"


def _pending(uri):
    return b"\x00" + anchor.TAG_PENDING + anchor.write_varbytes(anchor.write_varbytes(uri.encode()))


def _cal_response(tail: bytes):
    # what a calendar does: prepend its own salt, sha256, append, sha256, then a pending attestation
    return (bytes([anchor.OP_PREPEND]) + anchor.write_varbytes(b"calsalt") + bytes([anchor.OP_SHA256]) +
            bytes([anchor.OP_APPEND]) + anchor.write_varbytes(b"\x01" * 32) + bytes([anchor.OP_SHA256]) + tail)


class MockTransport:
    def __init__(self, fail=()):
        self.calls, self.fail = [], fail

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url))
        if any(f in url for f in self.fail):
            raise OSError("calendar down")
        if method == "POST":
            assert len(body) == 32 and headers["Accept"] == "application/vnd.opentimestamps.v1"
            return 200, _cal_response(_pending(PENDING_URI))
        # upgrade: the rest of the path to a bitcoin block
        return 200, bytes([anchor.OP_SHA256]) + b"\x00" + anchor.TAG_BITCOIN + anchor.write_varbytes(anchor.write_varuint(915123))


def _expected_pending_digest(root, nonce):
    c = anchor.commitment(root, nonce)
    c = hashlib.sha256(b"calsalt" + c).digest()
    return hashlib.sha256(c + b"\x01" * 32).digest()


def test_anchor_submit_verify_upgrade_offline():
    root = hashlib.sha256(b"day").hexdigest()
    nonce = b"\x07" * 16
    t = MockTransport(fail=("bob",))
    r = anchor.submit(root, t, nonce=nonce, day="2026-10-06")
    assert [c["ok"] for c in r["calendars"]] == [True, False, True]
    v = anchor.verify_anchor(root, r)
    assert v["ok"] and len(v["pending"]) == 2 and not v["bitcoin"]
    assert v["pending"][0]["digest"] == _expected_pending_digest(root, nonce).hex()
    assert "not yet on Bitcoin" in v["proves"]
    # wrong root / tampered nonce are refused
    assert not anchor.verify_anchor(hashlib.sha256(b"other").hexdigest(), {**r, "root": hashlib.sha256(b"other").hexdigest()})["ok"]
    assert not anchor.verify_anchor(root, {**r, "nonce_hex": "00" * 16})["ok"]
    assert not anchor.verify_anchor(hashlib.sha256(b"x").hexdigest(), r)["ok"]
    # upgrade -> bitcoin attestation at the right digest
    r = anchor.upgrade(r, t)
    v = anchor.verify_anchor(root, r)
    assert [b["height"] for b in v["bitcoin"]] == [915123]
    assert v["bitcoin"][0]["digest"] == hashlib.sha256(_expected_pending_digest(root, nonce)).hexdigest()
    assert all(m in ("POST", "GET") for m, _ in t.calls)


def test_ots_file_round_trip(tmp_path):
    root = hashlib.sha256(b"day").hexdigest()
    r = anchor.submit(root, MockTransport(), nonce=b"\x01" * 16, day="2026-10-06")
    data = anchor.to_ots_file(r)
    assert data.startswith(anchor.OTS_MAGIC)
    rest = data[len(anchor.OTS_MAGIC):]
    assert rest[0] == 1 and rest[1] == anchor.OP_SHA256 and rest[2:34].hex() == root
    atts = anchor.walk(anchor.parse_timestamp(rest[34:]), bytes.fromhex(root))
    assert len(atts) == 3 and all(a["type"] == "pending" for a in atts)
    p = anchor.save_receipt(r, tmp_path)
    assert p.exists() and (tmp_path / "2026-10-06.ots").exists()
    assert anchor.latest_receipt(tmp_path)["root"] == root


def test_junk_calendar_response_rejected():
    def junk(method, url, body, headers):
        return 200, b"\x99garbage"
    r = anchor.submit(hashlib.sha256(b"d").hexdigest(), junk, calendars=("https://x",))
    assert not r["calendars"][0]["ok"]
    assert not anchor.verify_anchor(r["root"], r)["ok"]


# ---- API ---------------------------------------------------------------------------------------------
def test_api_endpoints_and_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_RECORD_PATH", str(tmp_path / "api.jsonl"))
    monkeypatch.setenv("LOOP_ANCHOR_DIR", str(tmp_path / "anchors"))
    monkeypatch.setenv("LOOP_RECORD_SALT", "s")
    from app import record_api
    app = FastAPI()
    app.include_router(record_api.router)
    c = TestClient(app)
    gate_out = {"idea": {"side": "buy", "symbol": "RNVDA", "notional": 200000.0}, "state": "BLOCKED_BY_YOUR_RULES",
                "broken_rules": ["R1"], "evidence": ["armed rule R1"], "last_trade_was_loss": True}
    e = record_api.log_gate_decision("raw-session-id", "F", gate_out, {"R1": 1})
    assert e["kind"] == "gate_decision" and e["payload"]["state"] == "BLOCKED_BY_YOUR_RULES"
    ev = record_api.log_rule_event("raw-session-id", "F", {"seq": 2, "at_ms": 1, "kind": "arm", "rule_id": "R1", "by": "owner-click",
                                                           "version": 1, "prev": "abc", "hash": "def"})
    assert ev["payload"]["rulebook_hash"] == "def" and ev["payload"]["kind"] == "arm"
    record_api.log_outcome(e["seq"], {"result": "held"})
    assert "raw-session-id" not in (tmp_path / "api.jsonl").read_text(encoding="utf-8")
    ents = c.get("/api/record/entries").json()["entries"]
    assert [x["seq"] for x in ents] == [3, 2, 1] and all(x["line"].startswith('{"hash":"') for x in ents)
    # the browser's trick: hash of the line with the hash key removed == stored hash
    body = '{' + ents[0]["line"][len('{"hash":"') + 64 + 2:]
    assert hashlib.sha256(body.encode()).hexdigest() == ents[0]["hash"]
    assert c.get("/api/record/verify").json()["intact"] is True
    cnt = c.get("/api/record/counter").json()
    assert cnt["decisions_logged"] == 1 and cnt["outcomes_resolved"] == 1 and cnt["pending"] == 0 and cnt["last_anchor"] is None
    assert c.get("/record").status_code == 200 and "Verify this log" in c.get("/record").text
    assert c.get("/api/record/day/not-a-day").status_code == 422
    # a broken record never breaks the gate
    monkeypatch.setenv("LOOP_RECORD_PATH", str(tmp_path / "x" / "y.jsonl"))
    record_api._LOGS.clear()
    assert "error" in record_api.log_gate_decision("s", "F", {"state": float("nan")})
