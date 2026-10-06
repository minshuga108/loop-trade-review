"""Public forward record: an append-only, hash-chained JSONL log (R21, M5, R7).

Every Rule Gate decision and every rule state change is written here at the
moment it is made, BEFORE anyone knows how it turns out. A later `outcome`
entry points back at the decision's seq; it can only be appended after the
decision, only once per decision, and it never rewrites the decision line.

Line format (one canonical JSON object per line, keys sorted, no spaces):
    {"hash":..., "kind":..., "payload":..., "prev_hash":..., "seq":..., "ts_ms":...}
hash = SHA-256 of the canonical JSON of the entry WITHOUT the "hash" key. Because
"hash" sorts first, that body is exactly the stored line with the prefix
`"hash":"<64 hex>",` removed, so a browser can re-hash the raw bytes without
re-serialising anything (no float formatting differences).

Paper only: provenance SIM_PAPER is stamped on every decision; session ids are
stored only as a keyed hash, never raw.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("gate_decision", "rule_event", "outcome")
GENESIS = "0" * 64
PROVENANCE = "SIM_PAPER"
DAY_MS = 86_400_000


class RecordError(ValueError):
    pass


# ---- canonical form ------------------------------------------------------------------
def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(s: str | bytes) -> str:
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def entry_hash(entry: dict) -> str:
    return sha256_hex(canonical({k: v for k, v in entry.items() if k != "hash"}))


def utc_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def default_path() -> Path:
    env = os.environ.get("LOOP_RECORD_PATH")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "data" / "record" / "record.jsonl"


# ---- session hashing -------------------------------------------------------------------
def _salt(path: Path) -> bytes:
    """Per-log secret next to the log, so a guessable session id cannot be brute-forced back."""
    env = os.environ.get("LOOP_RECORD_SALT")
    if env:
        return env.encode()
    sp = path.with_name(path.name + ".salt")
    if not sp.exists():
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(secrets.token_hex(32), encoding="ascii")
    return sp.read_text(encoding="ascii").strip().encode()


def hash_session(sid: str, salt: bytes) -> str:
    return "s_" + hmac.new(salt, (sid or "default").encode(), hashlib.sha256).hexdigest()[:20]


# ---- the log -----------------------------------------------------------------------------
class RecordLog:
    """Append-only log. Safe for many threads in ONE process (a lock serialises appends)."""

    def __init__(self, path: str | Path | None = None, clock=None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.clock = clock or (lambda: int(time.time() * 1000))
        self._lock = threading.Lock()
        self._size = -1                      # file size at our last read/write; a change forces a reload
        self._head: dict | None = None
        self._decisions: dict[int, int] = {}  # decision seq -> ts_ms
        self._resolved: set[int] = set()

    # -- state ----------------------------------------------------------------
    def _reload(self) -> None:
        size = self.path.stat().st_size
        if size == self._size:
            return
        self._head, self._decisions, self._resolved = None, {}, set()
        for e in iter_entries(self.path):
            self._absorb(e)
        self._size = size

    def _absorb(self, e: dict) -> None:
        self._head = e
        if e["kind"] == "gate_decision":
            self._decisions[e["seq"]] = e["ts_ms"]
        elif e["kind"] == "outcome":
            self._resolved.add(e["payload"]["decision_seq"])

    def session_hash(self, sid: str) -> str:
        return hash_session(sid, _salt(self.path))

    # -- writes -----------------------------------------------------------------
    def append(self, kind: str, payload: dict, ts_ms: int | None = None) -> dict:
        if kind not in KINDS:
            raise RecordError(f"unknown kind {kind!r}")
        if not isinstance(payload, dict):
            raise RecordError("payload must be an object")
        with self._lock:
            self._reload()
            head = self._head
            seq = head["seq"] + 1 if head else 1
            ts = int(self.clock() if ts_ms is None else ts_ms)
            if head and ts < head["ts_ms"]:
                if ts_ms is not None:
                    raise RecordError("a new entry cannot be dated before the previous one")
                ts = head["ts_ms"]           # clock jitter: never let time run backwards inside the log
            payload = dict(payload)
            if kind == "gate_decision":
                if payload.get("provenance", PROVENANCE) != PROVENANCE:
                    raise RecordError("decisions are SIM_PAPER only")
                payload["provenance"] = PROVENANCE
                if "session" in payload and not str(payload["session"]).startswith("s_"):
                    raise RecordError("raw session ids are never written; use session_hash()")
            if kind == "outcome":
                ref = payload.get("decision_seq")
                if not isinstance(ref, int) or ref not in self._decisions:
                    raise RecordError("an outcome must reference an earlier gate_decision seq")
                if ref in self._resolved:
                    raise RecordError(f"decision {ref} already has an outcome; outcomes are never rewritten")
                if ts < self._decisions[ref]:
                    raise RecordError("an outcome cannot be timestamped before its decision")
            entry = {"seq": seq, "ts_ms": ts, "kind": kind, "payload": payload,
                     "prev_hash": head["hash"] if head else GENESIS}
            entry["hash"] = entry_hash(entry)
            line = canonical(entry)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._absorb(entry)
            self._size = self.path.stat().st_size
            return entry

    def log_decision(self, payload: dict, ts_ms: int | None = None) -> dict:
        return self.append("gate_decision", payload, ts_ms)

    def log_rule_event(self, payload: dict, ts_ms: int | None = None) -> dict:
        return self.append("rule_event", payload, ts_ms)

    def log_outcome(self, decision_seq: int, payload: dict, ts_ms: int | None = None) -> dict:
        return self.append("outcome", {**payload, "decision_seq": decision_seq}, ts_ms)

    # -- reads ------------------------------------------------------------------
    def entries(self) -> list[dict]:
        return list(iter_entries(self.path))

    def tail(self, n: int = 20) -> list[dict]:
        lines = read_lines(self.path)[-n:]
        out = []
        for x in reversed(lines):
            e = _parse(x)
            out.append({**e, "line": x} if e is not None else
                       {"corrupt": True, "seq": None, "ts_ms": None, "kind": "corrupt", "payload": {}, "hash": "", "prev_hash": "", "line": x})
        return out

    def verify(self) -> dict:
        return verify_file(self.path)

    def counter(self, now_ms: int | None = None) -> dict:
        return counter(self.path, self.clock() if now_ms is None else now_ms)

    def day_root(self, day: str) -> dict:
        return day_root(self.path, day)


# ---- file helpers ---------------------------------------------------------------------------
def read_lines(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [x for x in p.read_text(encoding="utf-8").split("\n") if x.strip()]


def iter_entries(path: str | Path):
    for x in read_lines(path):
        yield json.loads(x)


def _parse(line: str) -> dict | None:
    """One stored line, or None when it is not a well-formed entry (a damaged file must not crash a reader)."""
    try:
        e = json.loads(line)
    except ValueError:
        return None
    if not isinstance(e, dict) or not isinstance(e.get("ts_ms"), int) or not isinstance(e.get("payload"), dict) or "kind" not in e:
        return None
    return e


def read_entries_safe(path: str | Path) -> tuple[list[dict], int]:
    """(well-formed entries, number of damaged lines). verify_file() is what says WHERE the damage is."""
    good, bad = [], 0
    for x in read_lines(path):
        e = _parse(x)
        if e is None:
            bad += 1
        else:
            good.append(e)
    return good, bad


def verify_file(path: str | Path) -> dict:
    """Walk the whole log. Returns intact/broken and the FIRST bad seq (the line number if unparsable)."""
    prev, n, last_ts = GENESIS, 0, 0
    decisions: dict[int, int] = {}
    resolved: set[int] = set()

    def bad(seq, reason):
        return {"intact": False, "status": "broken", "entries": n, "first_bad_seq": seq, "reason": reason, "head": prev}

    for i, line in enumerate(read_lines(path), start=1):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return bad(i, "line is not valid JSON")
        if not isinstance(e, dict) or set(e) != {"seq", "ts_ms", "kind", "payload", "prev_hash", "hash"}:
            return bad(e.get("seq", i) if isinstance(e, dict) else i, "entry has missing or extra fields")
        seq = e["seq"]
        if seq != i:
            return bad(i, f"expected seq {i}, found {seq} (a line was removed, inserted or reordered)")
        if e["prev_hash"] != prev:
            return bad(seq, "prev_hash does not match the previous entry's hash")
        if e["hash"] != entry_hash(e):
            return bad(seq, "content does not match its hash (the entry was edited)")
        if canonical(e) != line:
            return bad(seq, "line is not in canonical form")
        if e["kind"] not in KINDS or not isinstance(e["ts_ms"], int) or e["ts_ms"] < last_ts:
            return bad(seq, "bad kind or timestamp went backwards")
        if e["kind"] == "gate_decision":
            if e["payload"].get("provenance") != PROVENANCE:
                return bad(seq, "decision without SIM_PAPER provenance")
            decisions[seq] = e["ts_ms"]
        if e["kind"] == "outcome":
            ref = e["payload"].get("decision_seq")
            if ref not in decisions or ref in resolved or e["ts_ms"] < decisions[ref]:
                return bad(seq, "outcome does not follow exactly one earlier decision")
            resolved.add(ref)
        prev, last_ts, n = e["hash"], e["ts_ms"], n + 1
    return {"intact": True, "status": "intact", "entries": n, "first_bad_seq": None, "reason": "every hash and link checks out", "head": prev}


# ---- Merkle root of a day (RFC 6962 style: domain-separated leaves, odd node promoted) --------
def _leaf(h_hex: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(h_hex)).digest()


def _node(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + a + b).digest()


def merkle_root(hashes: list[str]) -> str:
    if not hashes:
        return hashlib.sha256(b"").hexdigest()
    level = [_leaf(h) for h in hashes]
    while len(level) > 1:
        level = [_node(level[i], level[i + 1]) if i + 1 < len(level) else level[i] for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(hashes: list[str], index: int) -> list[list[str]]:
    """Sibling path for hashes[index]: [[side, hex], ...] with side 'L' or 'R'."""
    level, idx, path = [_leaf(h) for h in hashes], index, []
    while len(level) > 1:
        sib = idx ^ 1
        if sib < len(level):
            path.append(["L" if sib < idx else "R", level[sib].hex()])
        level = [_node(level[i], level[i + 1]) if i + 1 < len(level) else level[i] for i in range(0, len(level), 2)]
        idx //= 2
    return path


def verify_merkle_proof(entry_hash_hex: str, proof: list[list[str]], root_hex: str) -> bool:
    cur = _leaf(entry_hash_hex)
    for side, h in proof:
        cur = _node(bytes.fromhex(h), cur) if side == "L" else _node(cur, bytes.fromhex(h))
    return cur.hex() == root_hex


def day_root(path: str | Path, day: str) -> dict:
    """Merkle root over the hashes of every entry whose ts_ms falls on `day` (UTC, YYYY-MM-DD)."""
    es = [e for e in read_entries_safe(path)[0] if utc_day(e["ts_ms"]) == day]
    hs = [e["hash"] for e in es]
    return {"day": day, "n": len(es), "root": merkle_root(hs), "first_seq": es[0]["seq"] if es else None,
            "last_seq": es[-1]["seq"] if es else None, "chain_head": hs[-1] if hs else None}


# ---- honest counter -------------------------------------------------------------------------------
def counter(path: str | Path, now_ms: int) -> dict:
    es, corrupt = read_entries_safe(path)
    decisions = [e for e in es if e["kind"] == "gate_decision"]
    outcomes = [e for e in es if e["kind"] == "outcome"]
    resolved = {e["payload"].get("decision_seq") for e in outcomes}
    # origin tags: judge / test / sandbox traffic is reported apart from decisions a user made on their own data;
    # lines written before the tag existed are "untagged" and are never promoted to user decisions
    by_origin: dict[str, int] = {}
    for e in decisions:
        o = e["payload"].get("origin") or "untagged"
        by_origin[o] = by_origin.get(o, 0) + 1
    user_seqs = {e.get("seq") for e in decisions if e["payload"].get("origin") == "user"}
    user_resolved = len(user_seqs & resolved)
    if es:
        d0 = datetime.strptime(utc_day(es[0]["ts_ms"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        d1 = datetime.strptime(utc_day(now_ms), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = (d1 - d0).days + 1
    else:
        days = 0
    return {"days_running": days, "first_entry_ms": es[0]["ts_ms"] if es else None,
            "entries": len(es), "decisions_logged": len(decisions), "rule_events": sum(e["kind"] == "rule_event" for e in es),
            "outcomes_resolved": len(resolved), "pending": len(decisions) - len(resolved),
            "by_origin": by_origin, "user_decisions": len(user_seqs), "user_outcomes_resolved": user_resolved,
            "user_pending": len(user_seqs) - user_resolved,
            "days_with_entries": len({utc_day(e["ts_ms"]) for e in es}),
            "head": es[-1].get("hash") if es else GENESIS, "provenance": PROVENANCE, "corrupt_lines": corrupt,
            "note": "Paper decisions only. Pending means the outcome is not known yet; it is never filled in backwards."}
