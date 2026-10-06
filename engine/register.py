"""Review-lane head-to-head register (scaffolding).

Named reference detectors are RE-IMPLEMENTED HERE FROM THEIR PUBLISHED DEFINITIONS.
No rival code was copied, downloaded or run. Where a published definition leaves a
choice open, the choice made here is written next to it (INTERPRETATION), so a reader
can disagree with it. Results from these functions describe our reading of a
published definition, not the rival product's actual behaviour.

Sources of the definitions (as recorded in the research files of this repo's parent folder):
- TradeMirror (github.com/hackid02/trademirror), README table "The 4 heuristic rules",
  recorded in data/teardown/trademirror_README.md:
    LEAK_WEEKEND_RTOKEN        rToken + market + NYSE closed            leak 0.50% x notional
    LEAK_REVENGE_TILT          entry <=15m after a loss at >=1.4x avg size     full loss if red
    LEAK_DISPOSITION_ASYMMETRY win/loss hold ratio < 0.25, winners clipped <30m  1.5x realized gain
    LEAK_EXHAUSTION_CLUSTER    >=6 trades/2h with fees > gross wins     fee + 25% of loss slice
- tradememory-protocol (github.com/mnemox-ai/tradememory-protocol), README example output,
  recorded in CRIT8_review_lane_inventory.md: "after 2 losses in a row..., 5 of 20 trades were
  1.5x usual size, won 20%, made -$1,700; median hold winners 1.5h vs losers 9.0h". Descriptive
  statistics; it issues no verdict.
- Trivial baseline: always says "you size up after losses".
- Loop (ours): engine.detectors.size_after_loss and hold_asymmetry, engine.court cap rule,
  engine.halt rule; run unchanged.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from . import detectors, halt
from .court import Court, Rule
from .schema import Provenance, RoundTrip

NY = ZoneInfo("America/New_York")
MIN_MS = 60_000
ASSUMED_FEE_PER_SIDE = 0.0005     # used only when a trip has no measured fee (planted traders); labelled ASSUMED

PROV = {
    "trademirror": "INDEPENDENT RE-IMPLEMENTATION of TradeMirror's published rule table (README), not TradeMirror's code",
    "tradememory": "INDEPENDENT RE-IMPLEMENTATION of tradememory-protocol's published example output (README), not its code",
    "baseline": "trivial baseline written here",
    "loop": "Loop engine (ours), run unchanged",
}


@dataclass
class Detection:
    detector: str
    family: str                    # trademirror | tradememory | baseline | loop
    question: str                  # size_after_loss | weekend | disposition | overtrading
    flagged: bool | None           # None = not applicable to this input
    n_triggers: int = 0
    priced: float | None = None    # dollars the detector says leaked (its own pricing rule), if it prices
    detail: str = ""
    provenance: str = ""


@dataclass
class TripMeta:
    """Fields a trip does not carry but some published rules need. None = unknown."""
    fee: float | None = None
    is_rtoken: bool | None = None
    order_type: str | None = None   # "market" | "limit"


def _sorted(trips):
    return sorted(range(len(trips)), key=lambda i: trips[i].t_open_ms)


def _last_close_before(trips: list[RoundTrip]):
    """For each trip: the trip that most recently closed before it opened (or None)."""
    order = sorted(range(len(trips)), key=lambda i: (trips[i].t_close_ms, i))
    closes = [trips[i].t_close_ms for i in order]
    out = []
    for t in trips:
        j = bisect.bisect_left(closes, t.t_open_ms) - 1
        out.append(order[j] if j >= 0 else None)
    return out, order, closes


# -- TradeMirror (re-implemented from the published table) ------------------------------

def nyse_closed(t_ms: int) -> bool:
    """INTERPRETATION: closed = weekend or outside 09:30-16:00 New York time. Exchange holidays ignored."""
    d = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).astimezone(NY)
    if d.weekday() >= 5:
        return True
    m = d.hour * 60 + d.minute
    return not (9 * 60 + 30 <= m < 16 * 60)


def tm_weekend_rtoken(trips, meta: list[TripMeta] | None = None) -> Detection:
    name = "TradeMirror LEAK_WEEKEND_RTOKEN"
    if not meta or all(m.is_rtoken is None or m.order_type is None for m in meta):
        return Detection(name, "trademirror", "weekend", None, detail="not applicable: input has no rToken flag or order type",
                         provenance=PROV["trademirror"])
    hits = [i for i, t in enumerate(trips) if meta[i].is_rtoken and meta[i].order_type == "market" and nyse_closed(t.t_open_ms)]
    leak = sum(0.005 * trips[i].first_order_notional for i in hits)     # ASSUMED 0.5% of notional, as published
    return Detection(name, "trademirror", "weekend", len(hits) > 0, len(hits), leak,
                     "rToken market orders opened while NYSE is closed; leak = assumed 0.5% x notional (not measured from fills)",
                     PROV["trademirror"])


def tm_revenge_tilt(trips) -> Detection:
    """INTERPRETATION: 'after a loss' = the last trip that closed before this open lost; '<=15m' measured from that
    close to this open; 'avg size' = mean opening notional over the whole history; flagged if any trip triggers
    (the published table gives no minimum count)."""
    last, _, _ = _last_close_before(trips)
    avg = float(np.mean([t.first_order_notional for t in trips])) if trips else 0.0
    hits = [i for i, t in enumerate(trips) if last[i] is not None and trips[last[i]].net_pnl < 0
            and t.t_open_ms - trips[last[i]].t_close_ms <= 15 * MIN_MS and t.first_order_notional >= 1.4 * avg]
    leak = sum(-trips[i].net_pnl for i in hits if trips[i].net_pnl < 0)  # "full loss if red"
    return Detection("TradeMirror LEAK_REVENGE_TILT", "trademirror", "size_after_loss", len(hits) > 0, len(hits), leak,
                     "entry <=15 min after a losing close at >=1.4x mean size; leak = full loss of those trips if red", PROV["trademirror"])


def tm_disposition(trips) -> Detection:
    """INTERPRETATION: ratio = mean hold of winners / mean hold of losers; 'winners clipped <30m' = median winner
    hold under 30 min; leak = 1.5 x the realised gain of winners held under 30 min."""
    w = [t for t in trips if t.net_pnl > 0]
    lo = [t for t in trips if t.net_pnl < 0]
    if not w or not lo:
        return Detection("TradeMirror LEAK_DISPOSITION_ASYMMETRY", "trademirror", "disposition", None,
                         detail="needs at least one winner and one loser", provenance=PROV["trademirror"])
    ratio = float(np.mean([t.hold_ms for t in w]) / max(np.mean([t.hold_ms for t in lo]), 1.0))
    clipped = float(np.median([t.hold_ms for t in w])) < 30 * MIN_MS
    flag = ratio < 0.25 and clipped
    short = [t for t in w if t.hold_ms < 30 * MIN_MS]
    leak = 1.5 * sum(t.net_pnl for t in short) if flag else 0.0
    return Detection("TradeMirror LEAK_DISPOSITION_ASYMMETRY", "trademirror", "disposition", flag, len(short) if flag else 0, leak,
                     f"win/loss mean hold ratio {ratio:.2f}, median winner hold {'<' if clipped else '>='}30 min", PROV["trademirror"])


def tm_exhaustion(trips, meta: list[TripMeta] | None = None) -> Detection:
    """INTERPRETATION: greedy non-overlapping windows of 2 h starting at each trip's open; a window qualifies with
    >= 6 opens and total fees > gross wins (sum of pre-fee pnl of winning trips); leak = fees + 25% of the losses
    in the window. Fees come from the fills when known, else ASSUMED 0.05% per side of opened notional."""
    idx = _sorted(trips)
    fees, assumed = [], 0
    for i in range(len(trips)):
        f = meta[i].fee if meta and meta[i].fee is not None else None
        if f is None:
            f = 2 * ASSUMED_FEE_PER_SIDE * trips[i].opened_notional
            assumed += 1
        fees.append(f)
    opens = [trips[i].t_open_ms for i in idx]
    k, n_clusters, leak, n_trig = 0, 0, 0.0, 0
    while k < len(idx):
        j = bisect.bisect_left(opens, opens[k] + 2 * 3_600_000)
        w = idx[k:j]
        if len(w) >= 6:
            fee = sum(fees[i] for i in w)
            gross_w = sum(trips[i].net_pnl + fees[i] for i in w if trips[i].net_pnl + fees[i] > 0)
            if fee > gross_w:
                n_clusters += 1
                n_trig += len(w)
                leak += fee + 0.25 * sum(-trips[i].net_pnl for i in w if trips[i].net_pnl < 0)
                k = j
                continue
        k += 1
    note = f"; fees ASSUMED for {assumed} of {len(trips)} trips" if assumed else "; fees from fills"
    return Detection("TradeMirror LEAK_EXHAUSTION_CLUSTER", "trademirror", "overtrading", n_clusters > 0, n_trig, leak,
                     f"{n_clusters} clusters of >=6 trades in 2 h with fees above gross wins{note}", PROV["trademirror"])


# -- tradememory (descriptive; re-implemented from the published example output) ----------

def tradememory_stats(trips) -> tuple[Detection, dict]:
    """After two losses in a row: how many trades, how many at >=1.5x usual (median) size, win rate, pnl;
    median hold winners vs losers. READING CONVENTION (ours, not tradememory's): we count it as a 'flag'
    when at least 5 such trades exist and >= 25% of them are 1.5x usual size, anchored on its own published
    example '5 of 20 trades were 1.5x usual size' presented as the finding."""
    order = sorted(range(len(trips)), key=lambda i: (trips[i].t_close_ms, i))
    closes = [trips[i].t_close_ms for i in order]
    med = float(np.median([t.first_order_notional for t in trips])) if trips else 0.0
    sel = []
    for i, t in enumerate(trips):
        j = bisect.bisect_left(closes, t.t_open_ms) - 1
        if j >= 1 and trips[order[j]].net_pnl < 0 and trips[order[j - 1]].net_pnl < 0:
            sel.append(i)
    big = [i for i in sel if trips[i].first_order_notional >= 1.5 * med]
    w = [t.hold_ms for t in trips if t.net_pnl > 0]
    lo = [t.hold_ms for t in trips if t.net_pnl < 0]
    stats = {"after_2_losses": len(sel), "of_which_1_5x": len(big),
             "win_rate": float(np.mean([trips[i].net_pnl > 0 for i in sel])) if sel else float("nan"),
             "pnl": float(sum(trips[i].net_pnl for i in sel)),
             "median_hold_win_h": float(np.median(w)) / 3.6e6 if w else float("nan"),
             "median_hold_loss_h": float(np.median(lo)) / 3.6e6 if lo else float("nan")}
    flag = len(sel) >= 5 and len(big) / len(sel) >= 0.25
    txt = (f"after 2 losses in a row: {len(big)} of {len(sel)} trades were 1.5x usual size, won {stats['win_rate']:.0%}, "
           f"made ${stats['pnl']:,.0f}; median hold winners {stats['median_hold_win_h']:.1f}h vs losers {stats['median_hold_loss_h']:.1f}h")
    return Detection("tradememory size after 2 losses (descriptive)", "tradememory", "size_after_loss", flag, len(big), None, txt,
                     PROV["tradememory"]), stats


def baseline_always() -> Detection:
    return Detection("baseline: always 'size-after-loss'", "baseline", "size_after_loss", True, 0, None,
                     "says every trader sizes up after losses", PROV["baseline"])


# -- ours ------------------------------------------------------------------------------

def loop_detections(trips, n_perm: int = 1000, seed: int = 0) -> list[Detection]:
    out = []
    f = detectors.size_after_loss(trips, n_perm=n_perm, seed=seed)
    out.append(Detection("Loop size_after_loss detector", "loop", "size_after_loss",
                         None if f.status == "UNDERPOWERED" else f.status == "FLAGGED", 0, None,
                         f"{f.status}, ratio {f.effect:.2f}, p {f.p:.3f}", PROV["loop"]))
    h = detectors.hold_asymmetry(trips, n_perm=n_perm, seed=seed)
    out.append(Detection("Loop hold_asymmetry detector", "loop", "disposition",
                         None if h.status == "UNDERPOWERED" else h.status == "FLAGGED", 0, None,
                         f"{h.status}, loser/winner hold ratio {h.effect:.2f}, p {h.p:.3f}", PROV["loop"]))
    c = Court(n_perm=n_perm, seed=seed)
    for m in (1.0, 1.5, 2.0, 3.0):
        c.propose(Rule(value=m))
    v = c.judge(trips, Rule(value=1.5))
    out.append(Detection("Loop court: cap 1.5x after a loss", "loop", "size_after_loss",
                         None if v.status == "UNDERPOWERED" else v.status == "ACCEPTED", v.test.get("n_affected", 0),
                         v.test.get("effect"), f"{v.status}: {v.reason}", PROV["loop"]))
    hj = halt.judge(trips, 2, n_perm=n_perm, seed=seed)
    out.append(Detection("Loop halt after 2 losses", "loop", "size_after_loss",
                         None if hj["status"] == "UNDERPOWERED" else hj["status"] == "ACCEPTED", hj["held_out"]["n_skipped"],
                         hj["held_out"]["effect"], f"{hj['status']}: {hj['reason']}", PROV["loop"]))
    return out


def run_all(trips: list[RoundTrip], meta: list[TripMeta] | None = None, n_perm: int = 1000, seed: int = 0) -> list[Detection]:
    trips = list(trips)
    if meta is not None:
        pairs = sorted(zip(trips, meta), key=lambda p: p[0].t_open_ms)
        trips, meta = [p[0] for p in pairs], [p[1] for p in pairs]
    else:
        trips.sort(key=lambda t: t.t_open_ms)
    tmd, _ = tradememory_stats(trips)
    return [tm_weekend_rtoken(trips, meta), tm_revenge_tilt(trips), tm_disposition(trips), tm_exhaustion(trips, meta),
            tmd, baseline_always()] + loop_detections(trips, n_perm, seed)


# -- planted traders for the register (SIM_PLANTED) ------------------------------------------

T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)


def planted_disposition(n: int = 400, sigma: float = 0.01, base: float = 5000.0, seed: int = 0) -> list[RoundTrip]:
    """Zero-expectancy trader who cuts winners fast (5-25 min) and sits on losers (2-10 h)."""
    g = np.random.default_rng(seed)
    out, t = [], T0
    for i in range(n):
        notional = base * float(np.exp(g.normal(0, 0.3)))
        r = float(g.normal(0, sigma))
        hold = int(g.integers(5, 26) if r > 0 else g.integers(120, 601)) * MIN_MS
        out.append(RoundTrip(symbol="PLANTED", t_open_ms=t, t_close_ms=t + hold, side="buy", first_order_notional=notional,
                             opened_notional=notional, net_pnl=notional * r, first_order_id=f"d{i}", provenance=Provenance.SIM_PLANTED))
        t += hold + int(g.integers(5, 300)) * MIN_MS
    return out


def planted_weekend_rtoken(n: int = 400, sigma: float = 0.01, base: float = 5000.0, seed: int = 0):
    """Trades an rToken with market orders, ~40% of opens while NYSE is closed, and NO extra cost on those
    trips in the fills (same return distribution). Returns trips and per-trip metadata."""
    g = np.random.default_rng(seed)
    out, meta = [], []
    for i in range(n):
        day = int(g.integers(0, 200))
        minute = int(g.integers(0, 24 * 60))
        t = T0 + day * 86_400_000 + minute * MIN_MS + i            # +i keeps opens unique
        notional = base * float(np.exp(g.normal(0, 0.3)))
        hold = int(g.integers(5, 120)) * MIN_MS
        out.append(RoundTrip(symbol="RTOKEN", t_open_ms=t, t_close_ms=t + hold, side="buy", first_order_notional=notional,
                             opened_notional=notional, net_pnl=notional * float(g.normal(0, sigma)), first_order_id=f"w{i}",
                             provenance=Provenance.SIM_PLANTED))
        meta.append(TripMeta(fee=None, is_rtoken=True, order_type="market"))
    return out, meta


def planted_set(seed: int) -> dict:
    """name -> (trips, meta, truth). Truth is what was planted, in plain words."""
    from .planted2 import planted_overtrader, planted_revenge_trader
    from .suite import suite_trader
    w, wm = planted_weekend_rtoken(seed=seed)
    return {
        "control (no habit, no leak)": (suite_trader(500, 0.25, seed=seed), None, "nothing"),
        "costless habit (3x after a loss, no cost)": (suite_trader(500, 0.25, size_mult=3.0, seed=seed), None, "size habit, costless"),
        "costly leak (3x after a loss, worse outcomes)": (suite_trader(500, 0.25, size_mult=3.0, k=0.5, seed=seed), None, "size habit + cost"),
        "revenge (quick 2.5x re-entry after a loss, worse)": (planted_revenge_trader(n=500, tilt=-0.004, seed=seed), None, "revenge re-entry + cost"),
        "disposition (winners cut <25 min, losers held hours)": (planted_disposition(seed=seed), None, "disposition"),
        "overtrader (heavy days lose)": (planted_overtrader(heavy_tilt=-0.004, seed=seed), None, "overtrading on heavy days + cost"),
        "weekend rToken market orders, no extra cost in fills": (w, wm, "weekend market orders, costless in fills"),
    }


def _planted_chunk(seed: int, n_perm: int) -> list[tuple[str, str, list[Detection]]]:
    return [(name, truth, run_all(trips, meta, n_perm, seed)) for name, (trips, meta, truth) in planted_set(seed).items()]


# -- public wallets -------------------------------------------------------------------------

def wallet_trips_and_meta(path) -> tuple[list[RoundTrip], list[TripMeta], int]:
    """Round trips from a sampled public wallet with per-trip fees summed from that symbol's fills inside the
    trip's [open, close] window (an approximation if two fills share the boundary millisecond)."""
    from adapters import hyperliquid_csv
    from . import ledger
    fills = ledger.dedupe(hyperliquid_csv.load(path))
    trips = ledger.to_round_trips(fills)
    by_sym: dict[str, tuple[list[int], list[float]]] = {}
    for f in sorted(fills, key=lambda x: x.t_ms):
        ts, fs = by_sym.setdefault(f.symbol, ([], []))
        ts.append(f.t_ms)
        fs.append(f.fee)
    cums = {s: (ts, np.concatenate([[0.0], np.cumsum(fs)])) for s, (ts, fs) in by_sym.items()}
    meta = []
    for t in trips:
        ts, c = cums[t.symbol]
        a, b = bisect.bisect_left(ts, t.t_open_ms), bisect.bisect_right(ts, t.t_close_ms)
        meta.append(TripMeta(fee=float(c[b] - c[a]), is_rtoken=None, order_type=None))
    return trips, meta, len(fills)


def _wallet_one(path: str, n_perm: int) -> tuple[str, int, int, list[Detection]]:
    trips, meta, nf = wallet_trips_and_meta(path)
    return path, nf, len(trips), run_all(trips, meta, n_perm, 0)


# -- driver -------------------------------------------------------------------------------

def run_register(seeds: int = 30, n_perm: int = 1000, wallet_dir=None, workers: int = 8) -> dict:
    import time
    from concurrent.futures import ProcessPoolExecutor
    from pathlib import Path
    t0 = time.time()
    planted: list[tuple[int, str, str, list[Detection]]] = []
    wallets = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        pf = {ex.submit(_planted_chunk, 500_000 + s, n_perm): 500_000 + s for s in range(seeds)}
        wf = []
        if wallet_dir is not None and Path(wallet_dir).is_dir():
            for p in sorted(Path(wallet_dir).glob("*.csv")):
                wf.append(ex.submit(_wallet_one, str(p), n_perm))
        for f, s in pf.items():
            for name, truth, dets in f.result():
                planted.append((s, name, truth, dets))
        for f in wf:
            wallets.append(f.result())
    return {"planted": planted, "wallets": wallets, "seeds": seeds, "seed_range": (500_000, 500_000 + seeds - 1),
            "n_perm": n_perm, "runtime_s": time.time() - t0,
            "wallet_dir": str(wallet_dir) if wallet_dir else None,
            "wallet_dir_present": bool(wallet_dir and Path(wallet_dir).is_dir())}
