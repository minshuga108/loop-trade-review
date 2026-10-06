"""Intent capture sandbox (R10): stamp the plan BEFORE a hypothetical order, grade it after.

Each stamp is a hash-locked record using engine/record.py's canonical JSON and SHA-256:
hash = sha256(canonical(entry without "hash")), and every entry links the previous one's
hash, so a stamp cannot be edited or back-dated after the outcome is known. Server time
only (the caller's clock is never trusted). Provenance is always SIM_PAPER: these are
hypothetical orders in a per-session sandbox, never real fills.

Grading:
  process-versus-outcome grid: followed plan / broke plan x won / lost
    (earned win, good loss, lucky win, deserved loss) after Annie Duke's "resulting".
  calibration: only at MIN_CALIBRATION resolved entries or more; stated confidence is
    scored with the Brier score (a proper scoring rule) and shown per confidence bin.
Imported histories carry no stamp made before the order, so intent metrics are refused for them.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from pydantic import BaseModel, ConfigDict, Field

from .record import GENESIS, PROVENANCE, canonical, entry_hash

MIN_CALIBRATION = 30
BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001))
REFUSAL = ("Intent metrics need a plan stamped BEFORE the order. An imported history (fills from an exchange or a "
           "public wallet) has no such stamp, and a plan written afterwards would be shaped by the outcome, so Loop "
           "does not grade intent, plan adherence or calibration on it.")


class IntentError(ValueError):
    pass


class StampIn(BaseModel):
    model_config = ConfigDict(frozen=True)
    thesis: str = Field(min_length=3, max_length=300)
    side: str = Field(pattern="^(long|short)$")
    symbol: str = Field(min_length=1, max_length=30)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    size: float = Field(gt=0, le=1e9)          # notional in USDT
    confidence: float = Field(ge=0.01, le=0.99)  # stated probability that the trade wins


class ResolveIn(BaseModel):
    model_config = ConfigDict(frozen=True)
    seq: int
    followed_plan: bool
    won: bool
    exit_price: float | None = Field(default=None, gt=0)


class IntentBook:
    """One session's hash-chained intent log. Thread-safe within one process."""

    def __init__(self, clock=None):
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.entries: list[dict] = []
        self._lock = threading.Lock()

    def _append(self, kind: str, payload: dict) -> dict:
        head = self.entries[-1] if self.entries else None
        ts = int(self.clock())
        if head and ts < head["ts_ms"]:
            ts = head["ts_ms"]
        e = {"seq": len(self.entries) + 1, "ts_ms": ts, "kind": kind, "payload": payload,
             "prev_hash": head["hash"] if head else GENESIS}
        e["hash"] = entry_hash(e)
        self.entries.append(e)
        return e

    def stamp(self, s: StampIn) -> dict:
        if s.side == "long" and s.stop >= s.entry or s.side == "short" and s.stop <= s.entry:
            raise IntentError("the stop must be below the entry for a long and above it for a short")
        risk = abs(s.entry - s.stop) / s.entry * s.size
        with self._lock:
            return self._append("intent", {**s.model_dump(), "risk_usdt": round(risk, 2), "provenance": PROVENANCE,
                                           "stamped_before_order": True})

    def resolve(self, r: ResolveIn) -> dict:
        with self._lock:
            target = next((e for e in self.entries if e["seq"] == r.seq and e["kind"] == "intent"), None)
            if target is None:
                raise IntentError("no stamped intent with that number")
            if any(e["kind"] == "outcome" and e["payload"]["intent_seq"] == r.seq for e in self.entries):
                raise IntentError("this intent already has an outcome; outcomes are never rewritten")
            return self._append("outcome", {"intent_seq": r.seq, "followed_plan": r.followed_plan, "won": r.won,
                                            "exit_price": r.exit_price, "provenance": PROVENANCE})

    def verify(self) -> dict:
        prev = GENESIS
        for e in self.entries:
            if e["prev_hash"] != prev or e["hash"] != entry_hash(e):
                return {"intact": False, "first_bad_seq": e["seq"]}
            prev = e["hash"]
        return {"intact": True, "first_bad_seq": None, "head": prev, "entries": len(self.entries)}

    def view(self) -> dict:
        outs = {e["payload"]["intent_seq"]: e for e in self.entries if e["kind"] == "outcome"}
        rows = []
        for e in self.entries:
            if e["kind"] != "intent":
                continue
            o = outs.get(e["seq"])
            rows.append({"seq": e["seq"], "ts_ms": e["ts_ms"], "hash": e["hash"], **e["payload"],
                         "outcome": None if o is None else {**o["payload"], "ts_ms": o["ts_ms"], "hash": o["hash"]},
                         "line": canonical({k: v for k, v in e.items()})})
        resolved = [r for r in rows if r["outcome"]]
        return {"entries": rows, "grid": grid(resolved), "calibration": calibration(resolved),
                "chain": self.verify(), "provenance": PROVENANCE,
                "label": "SANDBOX: hypothetical orders you typed in this session. SIM_PAPER, not real fills; resets with the session."}


def grid(resolved: list[dict]) -> dict:
    cells = {"earned_win": 0, "good_loss": 0, "lucky_win": 0, "deserved_loss": 0}
    for r in resolved:
        f, w = r["outcome"]["followed_plan"], r["outcome"]["won"]
        cells[("earned_win" if w else "good_loss") if f else ("lucky_win" if w else "deserved_loss")] += 1
    return {"cells": cells, "n": len(resolved),
            "followed_rate": (cells["earned_win"] + cells["good_loss"]) / len(resolved) if resolved else None}


def calibration(resolved: list[dict]) -> dict:
    n = len(resolved)
    if n < MIN_CALIBRATION:
        return {"status": "NOT_ENOUGH", "n": n, "needed": MIN_CALIBRATION - n, "min": MIN_CALIBRATION, "bins": [], "brier": None}
    conf = [r["confidence"] for r in resolved]
    won = [1.0 if r["outcome"]["won"] else 0.0 for r in resolved]
    brier = sum((c - w) ** 2 for c, w in zip(conf, won)) / n
    base = sum(won) / n
    bins = []
    for lo, hi in BINS:
        sel = [(c, w) for c, w in zip(conf, won) if lo <= c < hi]
        if sel:
            bins.append({"lo": lo, "hi": min(hi, 1.0), "n": len(sel), "stated": sum(c for c, _ in sel) / len(sel),
                         "actual": sum(w for _, w in sel) / len(sel)})
    return {"status": "MEASURED", "n": n, "needed": 0, "min": MIN_CALIBRATION, "bins": bins, "brier": brier,
            "brier_always_base_rate": base * (1 - base),
            "detail": "Brier score: mean squared gap between stated confidence and the 0/1 outcome (lower is better); "
                      "compared with always stating your own win rate"}


class Sandbox:
    """Per-session IntentBooks, bounded LRU like the rulebook sandbox."""

    def __init__(self, max_sessions: int = 200, clock=None):
        self.books: "OrderedDict[str, IntentBook]" = OrderedDict()
        self.max, self.clock = max_sessions, clock
        self._lock = threading.Lock()

    def get(self, sid: str) -> IntentBook:
        key = sid or "default"
        with self._lock:
            if key not in self.books:
                self.books[key] = IntentBook(self.clock)
                while len(self.books) > self.max:
                    self.books.popitem(last=False)
            self.books.move_to_end(key)
            return self.books[key]
