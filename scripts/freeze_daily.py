"""Freeze one prediction per shipped trader into the hash-chained, append-only data/runs/runs.jsonl.

    python scripts/freeze_daily.py            # freeze today (UTC); a trader already frozen today is skipped
    python scripts/freeze_daily.py --no-net   # skip the live Bitget book (cost left as 'unavailable', never invented)

Facts only: the thesis hash and cap-rule prediction come from engine/thesis.py; the cost estimate for BTCUSDT comes from
the Bitget public order book through app/costs.py. Nothing already in the file is ever rewritten. To ship the board to a
host with an ephemeral disk, copy the file to deploy_data/runs_seed.jsonl and commit it (see DEPLOY.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LOOP_NO_REFRESH", "1")

from app import costs, runs_api, service  # noqa: E402
from engine import thesis as T  # noqa: E402

SYMBOL, SIZE, SIDE = "BTCUSDT", 5000.0, "buy"


def _day(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def cost_prediction(net: bool) -> dict:
    if net and SYMBOL not in costs.CACHE:
        try:
            costs.refresh_once()
        except Exception:
            pass
    c = costs.cost_line(SYMBOL, SIZE, SIDE)
    if not c.get("available") or c.get("stale"):
        return {"available": False, "symbol": SYMBOL, "reason": c.get("reason") or "cached book is stale"}
    return {"available": True, "symbol": SYMBOL, "size_usdt": SIZE, "side": SIDE, "cost_bps": c["cost_bps"], "fill_fraction": c["fill_fraction"],
            "book_age_s": c["cache_age_s"], "source": "Bitget public order book (cached), taker fee included"}


def thesis_prediction(tid: str, day: str) -> dict:
    review = service.review(tid)
    trips = service._load(tid)[3]
    facts = T.build_facts(review, trips)
    pred = T.prediction_of(facts, trips)
    when = _day(pred["as_of_ms"])
    if pred["predicts_rule_saves"]:
        en = f"The {pred['cap_multiple']}x cap rule would still save money on trades opened after {when}."
        zh = f"{pred['cap_multiple']} 倍上限规则在 {when} 之后开仓的交易上仍然能省钱。"
    else:
        en = f"No cap rule would be armable (still rejected or underpowered) on trades opened after {when}."
        zh = f"在 {when} 之后开仓的交易上，仍没有可启用的上限规则（仍被拒绝或检验力不足）。"
    return {**pred, "as_of_date": when, "date": day, "thesis_hash": T.thesis_hash(facts, day), "claim_en": en, "claim_zh": zh}


def freeze(day: str | None = None, net: bool = True, now: float | None = None) -> list[dict]:
    now = now or time.time()
    day = day or _day(now * 1000)
    d = runs_api.live_dir()
    d.mkdir(parents=True, exist_ok=True)
    ch = runs_api.load_chain()
    have = {(e["trader"], e["day"]) for e in ch["entries"]}
    prev, seq = ch["tip"], len(ch["entries"])
    cost = cost_prediction(net)
    out = []
    with (d / "runs.jsonl").open("a", encoding="utf-8") as fh:      # append only: mode "a", never "w"
        for t in service.TRADERS:
            tid = t["id"]
            if (tid, day) in have:
                continue
            seq += 1
            e = {"seq": seq, "ts": round(now, 3), "day": day, "trader": tid, "prev": prev,
                 "predictions": {"thesis": thesis_prediction(tid, day), "cost": cost}}
            e["hash"] = prev = runs_api.entry_hash(e)
            fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
            out.append(e)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true")
    a = ap.parse_args()
    for e in freeze(net=not a.no_net):
        print(e["seq"], e["trader"], e["hash"][:12], e["predictions"]["thesis"]["claim_en"])
