"""Score frozen runs older than 24h against what the engine computes now. Appends final scores to data/runs/scores.jsonl.

Three components, each labelled:
  rule       live data   thesis.score() on trades opened after the freeze; pending until enough new trades exist
  reproduce  replay      engine recomputed for the frozen day: the thesis hash must match the frozen one
  cost       live data   BTCUSDT order-book cost now vs frozen, within max(50%, 2 bps); pending if no fresh book
A final score is never rewritten; anything not yet knowable is written as nothing and stays 'pending'.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LOOP_NO_REFRESH", "1")

from app import costs, runs_api, service  # noqa: E402
from engine import thesis as T  # noqa: E402

TOL_REL, TOL_BPS = 0.5, 2.0


def score_rule(e: dict):
    p = e["predictions"]["thesis"]
    sc = T.score(p, service._load(e["trader"])[3])
    if not sc["testable"]:
        return None
    res = sc["rule"] if sc["rule"] != "NA" else sc["habit"]
    if res not in ("CONFIRMED", "MISSED"):
        return None
    return ("scored" if res == "CONFIRMED" else "missed", "live-data", {"n_new": sc["n_new"], "effect": sc["effect"], "result": res})


def score_reproduce(e: dict):
    p = e["predictions"]["thesis"]
    facts = T.build_facts(service.review(e["trader"]), service._load(e["trader"])[3])
    now = T.thesis_hash(facts, p["date"])
    return ("scored" if now == p["thesis_hash"] else "missed", "replay", {"frozen": p["thesis_hash"][:12], "now": now[:12]})


def score_cost(e: dict):
    p = e["predictions"]["cost"]
    if not p.get("available"):
        return None
    c = costs.cost_line(p["symbol"], p["size_usdt"], p["side"])
    if not c.get("available") or c.get("stale"):
        return None
    now, was = c["cost_bps"], p["cost_bps"]
    ok = abs(now - was) <= max(TOL_REL * abs(was), TOL_BPS)
    return ("scored" if ok else "missed", "live-data", {"frozen_bps": was, "now_bps": now})


FUNCS = {"rule": score_rule, "reproduce": score_reproduce, "cost": score_cost}


def run(now: float | None = None, net: bool = True) -> list[dict]:
    now = now or time.time()
    if net and "BTCUSDT" not in costs.CACHE:
        try:
            costs.refresh_once()
        except Exception:
            pass
    done = runs_api.load_scores()
    d = runs_api.live_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = []
    with (d / "scores.jsonl").open("a", encoding="utf-8") as fh:
        for e in runs_api.load_chain()["entries"]:
            if now - e["ts"] < runs_api.DAY_S:
                continue
            for comp, fn in FUNCS.items():
                if (e["hash"], comp) in done:
                    continue
                try:
                    r = fn(e)
                except Exception:
                    r = None
                if r is None:
                    continue
                s = {"run_hash": e["hash"], "component": comp, "state": r[0], "basis": r[1], "detail": r[2], "scored_at": round(now, 3)}
                fh.write(json.dumps(s, sort_keys=True) + "\n")
                out.append(s)
    return out


if __name__ == "__main__":
    for s in run(net="--no-net" not in sys.argv):
        print(s["run_hash"][:12], s["component"], s["state"], s["basis"])
