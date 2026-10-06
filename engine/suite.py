"""Planted-RULE suite for the rule court (SIM_PLANTED only; never shown as a real person).

Two rules are judged, exactly as the product judges them:
- CAP: "cap opening size at 1.5x median after a loss" through engine.court.Court
  (4 proposals in the trial ledger, so the threshold is 0.05/4), and
- HALT: "halt for the day after 2 consecutive losing trips" through engine.halt.judge.

Scenarios (each simulated many times with fixed seeds):
- STATIONARY at loss base rates 5/25/60/75 percent: NULL (no habit, no leak), HABIT
  (sizes up 3x after a loss but outcomes are unchanged: costless) and LEAK (sizes up 3x
  after a loss AND after-loss trades have negative expectancy: costly).
- DECAY: the leak is real in the first half and gone in the second (the habit stays).
- BASE-RATE SHIFT: a real leak throughout while the loss rate moves 25 -> 75 percent
  (and 75 -> 25) mid-history; plus a null with the same shift.
- LOOK-AHEAD: rules that peek at outcomes not known at the order's open; the structural
  guard in engine.lookahead must refuse them every time.

Generator. Each trip's sign is an independent Bernoulli draw: it loses with probability
equal to the nominal base rate, whatever the state, so the unconditional loss rate is the
nominal one by construction (and is measured and reported per cell). Magnitudes are
|N(0,1)| times s_L for losses and s_W for wins, with b*s_L = (1-b)*s_W = sigma*sqrt(b(1-b)),
so the expected return is zero and the variance is sigma^2 at every base rate. The LEAK
multiplies loss magnitudes by (1+k) and win magnitudes by (1-k) on trips that follow a
loss: same loss probability, negative expectancy (-2*k*0.798*sigma*sqrt(b(1-b)) per unit
notional). Its strength k is fixed across base rates, so power is allowed to differ.

For every cell the suite also runs the decay check (engine/decay.py) on the second half of
the history as if the rule had been armed at the midpoint, and the full lifecycle
(court on the first half -> rulebook arm -> decay check -> retirement proposal).
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np

from . import halt, lookahead
from .court import Court, Rule, _baseline
from .decay import apply_to_rulebook, cap_decay_check, halt_decay_check
from .detectors import after_loss_labels
from .rulebook import Rulebook
from .schema import Provenance, RoundTrip

T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)
MIN_MS = 60_000
CAP_RULE = Rule(value=1.5)
PROPOSALS = (1.0, 1.5, 2.0, 3.0)
HALT_N = 2


# -- statistics -----------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


# -- generator ------------------------------------------------------------------------

def suite_trader(n: int = 500, base_rate: float = 0.25, size_mult: float = 1.0, k: float = 0.0, sigma: float = 0.02,
                 base: float = 5000.0, seed: int = 0, leak_until: int | None = None, base_rate2: float | None = None,
                 shift_at: int | None = None) -> list[RoundTrip]:
    g = np.random.default_rng(seed)
    trips: list[RoundTrip] = []
    t = T0
    prev_loss = False
    for i in range(n):
        b = base_rate2 if (base_rate2 is not None and shift_at is not None and i >= shift_at) else base_rate
        m = sigma * math.sqrt(b * (1 - b))
        s_l, s_w = m / b, m / (1 - b)
        leak_on = leak_until is None or i < leak_until
        after = prev_loss
        notional = base * float(np.exp(g.normal(0, 0.4))) * (size_mult if after else 1.0)
        kk = k if (after and leak_on) else 0.0
        z = abs(float(g.normal()))
        lose = g.random() < b
        r = -s_l * z * (1 + kk) if lose else s_w * z * (1 - kk)
        net = notional * r
        if net == 0.0:
            net = -1e-9 if lose else 1e-9
        hold = int(g.integers(5, 240)) * MIN_MS
        trips.append(RoundTrip(symbol="PLANTED", t_open_ms=t, t_close_ms=t + hold, side="buy",
                               first_order_notional=notional, opened_notional=notional, net_pnl=net,
                               first_order_id=f"p{i}", provenance=Provenance.SIM_PLANTED))
        t += hold + int(g.integers(5, 600)) * MIN_MS
        prev_loss = net < 0
    return trips


# -- cells ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Cell:
    name: str
    scenario: str            # STATIONARY | DECAY | SHIFT | LOOKAHEAD
    truth: str               # null | leak | decay
    params: dict = field(default_factory=dict)


def cells(n: int = 500) -> list[Cell]:
    out = []
    for b in (0.05, 0.25, 0.60, 0.75):
        pct = int(round(b * 100))
        out.append(Cell(f"stationary {pct}% null", "STATIONARY", "null", dict(n=n, base_rate=b)))
        out.append(Cell(f"stationary {pct}% costless habit", "STATIONARY", "null", dict(n=n, base_rate=b, size_mult=3.0)))
        out.append(Cell(f"stationary {pct}% costly leak", "STATIONARY", "leak", dict(n=n, base_rate=b, size_mult=3.0, k=0.5)))
    for b in (0.25, 0.60):
        pct = int(round(b * 100))
        out.append(Cell(f"decay {pct}% (leak first half only)", "DECAY", "decay",
                        dict(n=n, base_rate=b, size_mult=3.0, k=0.5, leak_until=n // 2)))
    out.append(Cell("shift 25->75% costly leak", "SHIFT", "leak", dict(n=n, base_rate=0.25, base_rate2=0.75, shift_at=n // 2, size_mult=3.0, k=0.5)))
    out.append(Cell("shift 75->25% costly leak", "SHIFT", "leak", dict(n=n, base_rate=0.75, base_rate2=0.25, shift_at=n // 2, size_mult=3.0, k=0.5)))
    out.append(Cell("shift 25->75% null", "SHIFT", "null", dict(n=n, base_rate=0.25, base_rate2=0.75, shift_at=n // 2)))
    out.append(Cell("look-ahead plant on a 25% costly-leak trader", "LOOKAHEAD", "lookahead",
                    dict(n=n, base_rate=0.25, size_mult=3.0, k=0.5)))
    return out


# -- one simulation ---------------------------------------------------------------------

def _guard_checks(trips: list[RoundTrip], reg: lookahead.FeatureRegistry, seed: int) -> dict:
    """The honest rules pass the guard and its masks equal the court's and halt's own logic."""
    s = lookahead.sort_trips(trips)
    gc = lookahead.guard(s, lookahead.CAP_AFTER_LOSS, reg, seed=seed)
    gh = lookahead.guard(s, lookahead.halt_after_losses(HALT_N), reg, seed=seed)
    lab = after_loss_labels(s)
    cap_same = gc.status == "OK" and bool(np.array_equal(gc.applies, lab == 1))
    halt_same = gh.status == "OK" and bool(np.array_equal(gh.applies, halt.skip_mask(s, HALT_N)))
    return {"guard_ok": gc.status == "OK" and gh.status == "OK", "guard_same": cap_same and halt_same,
            "registry_hash": gc.registry_hash}


def run_one(cell: Cell, seed: int, n_perm: int = 1000) -> dict:
    p = dict(cell.params)
    trips = suite_trader(seed=seed, **p)
    n = len(trips)
    out = {"seed": seed, "loss_rate": float(np.mean([t.net_pnl < 0 for t in trips]))}
    if cell.scenario == "LOOKAHEAD":
        reg = lookahead.selftest_registry()
        for key, rule in (("peek", lookahead.LEAKY_PEEK), ("following", lookahead.LEAKY_FOLLOWING),
                          ("mistagged", lookahead.LEAKY_MISTAGGED), ("honest_cap", lookahead.CAP_AFTER_LOSS)):
            r = lookahead.judge_guarded(trips, rule, reg, n_perm=n_perm, seed=seed)
            out[key] = r["status"]
            out[key + "_stats_only"] = r["stats_only"]
        out["registry_hash"] = reg.hash()
        return out
    reg = lookahead.default_registry()
    out.update(_guard_checks(trips, reg, seed))
    # court on the whole history (train 60 / held-out 40)
    court = Court(n_perm=n_perm, seed=seed)
    for m in PROPOSALS:
        court.propose(Rule(value=m))
    v = court.judge(trips, CAP_RULE)
    out["cap"] = v.status
    out["halt"] = halt.judge(trips, HALT_N, n_perm=n_perm, seed=seed)["status"]
    # decay check on the second half, as if armed at the midpoint (baseline frozen from the first half)
    first, second = trips[: n // 2], trips[n // 2:]
    base = _baseline(first)
    out["cap_decay"] = cap_decay_check(second, CAP_RULE, base, n_perm=n_perm, seed=seed)["status"]
    out["halt_decay"] = halt_decay_check(second, HALT_N, n_perm=n_perm, seed=seed)["status"]
    # full lifecycle for the cap rule: court on the first half only -> arm -> decay check -> proposal
    c1 = Court(n_perm=n_perm, seed=seed)
    for m in PROPOSALS:
        c1.propose(Rule(value=m))
    v1 = c1.judge(first, CAP_RULE)
    out["life_accepted"] = v1.status == "ACCEPTED"
    out["life_retired"] = False
    if v1.status == "ACCEPTED":
        rb = Rulebook("suite")
        e = rb.record_verdict(v1)
        rb.arm(e.rule_id, approved_by="suite-owner")
        chk = cap_decay_check(second, CAP_RULE, base, n_perm=n_perm, seed=seed)
        out["life_retired"] = apply_to_rulebook(rb, e.rule_id, chk) == "PENDING_RETIREMENT"
    return out


def _run_cell_chunk(cell: Cell, seeds: list[int], n_perm: int) -> list[dict]:
    return [run_one(cell, s, n_perm) for s in seeds]


# -- summary --------------------------------------------------------------------------

def _rate(rs: list[dict], key: str, val) -> dict:
    k = sum(1 for r in rs if r.get(key) == val)
    lo, hi = wilson(k, len(rs))
    return {"k": k, "n": len(rs), "rate": k / len(rs) if rs else float("nan"), "lo": lo, "hi": hi}


def summarize(cell: Cell, rs: list[dict]) -> dict:
    lr = [r["loss_rate"] for r in rs]
    s = {"cell": cell.name, "scenario": cell.scenario, "truth": cell.truth, "sims": len(rs),
         "loss_rate_mean": float(np.mean(lr)), "loss_rate_min": float(np.min(lr)), "loss_rate_max": float(np.max(lr)),
         "seeds": (min(r["seed"] for r in rs), max(r["seed"] for r in rs)), "rules": {}}
    if cell.scenario == "LOOKAHEAD":
        for key in ("peek", "following", "mistagged", "honest_cap"):
            s["rules"][key] = {"refused": _rate(rs, key, "REFUSED_LOOKAHEAD"),
                               "stats_only_accept": _rate(rs, key + "_stats_only", "ACCEPTED"),
                               "accepted": _rate(rs, key, "ACCEPTED")}
        s["registry_hash"] = rs[0]["registry_hash"]
        return s
    for rule in ("cap", "halt"):
        s["rules"][rule] = {"accept": _rate(rs, rule, "ACCEPTED"), "under": _rate(rs, rule, "UNDERPOWERED"),
                            "retire": _rate(rs, rule + "_decay", "RETIRE"),
                            "decay_under": _rate(rs, rule + "_decay", "UNDERPOWERED")}
    acc = [r for r in rs if r["life_accepted"]]
    s["life"] = {"accepted": len(acc), "retired": sum(r["life_retired"] for r in acc)}
    s["guard_ok"] = _rate(rs, "guard_ok", True)
    s["guard_same"] = _rate(rs, "guard_same", True)
    s["registry_hashes"] = sorted({r["registry_hash"] for r in rs})
    return s


def run_suite(sims: int = 100, n: int = 500, n_perm: int = 1000, budget_s: float = 3600.0, workers: int = 8,
              chunk: int = 10, progress=print) -> dict:
    """Run every cell. Seeds are 10_000 * cell_index + sim. If the wall-clock budget runs out,
    the remaining work is cancelled and every cell reports the sims it actually completed."""
    t0 = time.time()
    cs = cells(n)
    results: dict[int, list[dict]] = {i: [] for i in range(len(cs))}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for ci, c in enumerate(cs):
            seeds = [10_000 * ci + s for s in range(sims)]
            for j in range(0, sims, chunk):
                futs[ex.submit(_run_cell_chunk, c, seeds[j:j + chunk], n_perm)] = ci
        stopped = False
        for f in as_completed(futs):
            if f.cancelled():
                continue
            results[futs[f]].extend(f.result())
            if not stopped and time.time() - t0 > budget_s:
                stopped = True
                for g in futs:
                    g.cancel()
                progress(f"budget of {budget_s:.0f}s reached; cancelling the remaining work")
    summaries = []
    for ci, c in enumerate(cs):
        rs = sorted(results[ci], key=lambda r: r["seed"])
        if rs:
            summaries.append(summarize(c, rs))
            progress(f"{c.name}: {len(rs)} sims")
    return {"summaries": summaries, "runtime_s": time.time() - t0, "sims_requested": sims, "n_trips": n,
            "n_perm": n_perm, "budget_s": budget_s, "workers": workers}


# -- report ---------------------------------------------------------------------------

def _pct(d: dict) -> str:
    return f"{d['rate']:.1%} [{d['lo']:.1%}, {d['hi']:.1%}] ({d['k']}/{d['n']})"


RULE_NAMES = {"cap": "cap 1.5x median after a loss (court, threshold 0.05/4)",
              "halt": "halt for the day after 2 losses (halt.judge, threshold 0.05)"}


def to_markdown(res: dict) -> str:
    S = res["summaries"]
    L = ["# Planted-rule suite for the Loop rule court (SIM_PLANTED), measured results", "",
         f"Generated by `scripts/run_suite.py`. Every number below is measured by that run, none typed. "
         f"{res['sims_requested']} sims requested per cell, {res['n_trips']} trips per simulated history, "
         f"{res['n_perm']} permutations per test, {res['workers']} worker processes, wall-clock budget {res['budget_s']:.0f}s, "
         f"actual runtime {res['runtime_s']:.0f}s. Seeds: cell i uses seeds 10000*i .. 10000*i+sims-1 (listed per cell). "
         "Rates are fractions of simulated histories; brackets are 95% Wilson intervals.", "",
         "How to read the ACCEPT column: on a null, decay or habit cell it is the FALSE-ADMISSION rate; on a costly-leak "
         "cell it is POWER. The RETIRE column is the decay check run on the second half of the history as if the rule had "
         "been armed at the midpoint: on a costly-leak cell it is the WRONGFUL-RETIREMENT rate, on a decay cell it is the "
         "rate at which a dead rule is correctly proposed for retirement, on a null cell retiring is correct.", "",
         "## Stationary, decay and base-rate shift", "",
         "| cell | truth | measured loss rate (mean, min-max) | rule | sims | ACCEPT | meaning | UNDERPOWERED | decay check RETIRE | meaning | decay check underpowered |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in S:
        if s["scenario"] == "LOOKAHEAD":
            continue
        for rule in ("cap", "halt"):
            r = s["rules"][rule]
            meaning = "power" if s["truth"] == "leak" else "false admission"
            rmean = {"leak": "wrongful retirement", "decay": "correct retirement", "null": "retirement (correct)"}[s["truth"]]
            L.append(f"| {s['cell']} | {s['truth']} | {s['loss_rate_mean']:.1%} ({s['loss_rate_min']:.1%}-{s['loss_rate_max']:.1%}) | "
                     f"{rule} | {s['sims']} | {_pct(r['accept'])} | {meaning} | {_pct(r['under'])} | {_pct(r['retire'])} | {rmean} | {_pct(r['decay_under'])} |")
    L += ["", "Full lifecycle (cap rule): court judges the FIRST half only; if ACCEPTED the rulebook arms it (owner approval "
          "simulated), then the decay check runs on the second half and, if it says RETIRE, the rulebook moves the rule to "
          "PENDING_RETIREMENT.", "", "| cell | accepted on first half | of those, retirement proposed |", "|---|---|---|"]
    for s in S:
        if s["scenario"] != "LOOKAHEAD":
            L.append(f"| {s['cell']} | {s['life']['accepted']}/{s['sims']} | {s['life']['retired']}/{s['life']['accepted']} |")
    L += ["", "Structural guard on the honest rules in every non-look-ahead history: both rules pass the guard, and the "
          "guard's rule masks equal the court's after-loss labels and halt.skip_mask exactly:", ""]
    for s in S:
        if s["scenario"] != "LOOKAHEAD":
            L.append(f"- {s['cell']}: guard passes {s['guard_ok']['k']}/{s['guard_ok']['n']}, masks identical "
                     f"{s['guard_same']['k']}/{s['guard_same']['n']}, registry hash {', '.join(s['registry_hashes'])}")
    L += ["", "## Look-ahead plant", ""]
    for s in S:
        if s["scenario"] != "LOOKAHEAD":
            continue
        L += [f"{s['cell']}, {s['sims']} histories, measured loss rate {s['loss_rate_mean']:.1%}, registry hash {s['registry_hash']}. "
              "`stats only` is what the held-out permutation test (threshold 0.05/4) would have said with the guard switched off.", "",
              "| rule | refused by the guard | accepted with the guard | stats only would ACCEPT |", "|---|---|---|---|"]
        names = {"peek": "LEAKY: skip the trade if it is going to lose (peeks at the next trade's outcome)",
                 "following": "LEAKY: skip if the following trade loses",
                 "mistagged": "LEAKY + LYING TAG: own outcome tagged as known at the open (caught by the as-of audit)",
                 "honest_cap": "honest: cap after a loss (control; must NOT be refused)"}
        for key, nm in names.items():
            r = s["rules"][key]
            L.append(f"| {nm} | {_pct(r['refused'])} | {_pct(r['accepted'])} | {_pct(r['stats_only_accept'])} |")
    L += ["", "## Our own losses, plainly", ""] + losses(S)
    L += ["", "## Caveats", "",
          "- Everything here is SIM_PLANTED. It measures the court's operating characteristics on a generator we chose; "
          "real traders have dependence structures (volatility clustering, symbol mix, overlapping positions) this generator does not.",
          "- One leak strength (k=0.5, sizes up 3x) and one history length per run. Power is a function of both; the numbers are not a "
          "general power curve.",
          "- The halt rule's court (engine/halt.py) uses p < 0.05 with no trial deflation; the cap rule's court deflates by 4 proposals.",
          "- The decay check thresholds (retire if effect <= 0 or p > 0.3; underpowered below 30 trips or 10/8 affected) were fixed in "
          "engine/decay.py before this run and not tuned on it.",
          "- The look-ahead guard audits a random sample of 12 trips per evaluation for mis-tagged features; a lying feature that "
          "only leaks on a few trips could slip through a sample that misses them. The tag check itself covers every trip.",
          "- Wilson intervals assume independent simulations, which holds by construction (distinct seeds)."]
    return "\n".join(L) + "\n"


def losses(S: list[dict]) -> list[str]:
    """Where the court fails its own bar, stated from the measured numbers."""
    out = []
    for s in S:
        if s["scenario"] == "LOOKAHEAD":
            for key, r in s["rules"].items():
                if key != "honest_cap" and r["refused"]["k"] < r["refused"]["n"]:
                    out.append(f"- LOSS: look-ahead rule '{key}' was NOT refused in {r['refused']['n'] - r['refused']['k']} of {r['refused']['n']} runs.")
                if key == "honest_cap" and r["refused"]["k"]:
                    out.append(f"- LOSS: the honest cap rule was wrongly refused by the guard in {r['refused']['k']} runs.")
            continue
        for rule, r in s["rules"].items():
            a, u, ret = r["accept"], r["under"], r["retire"]
            if s["truth"] in ("null", "decay") and a["hi"] > 0.05:
                out.append(f"- {s['cell']}, {rule}: false admission {a['rate']:.1%} (upper Wilson bound {a['hi']:.1%} is above 5%).")
            if s["truth"] == "leak" and a["rate"] < 0.8:
                out.append(f"- {s['cell']}, {rule}: power only {a['rate']:.1%}; underpowered {u['rate']:.1%} of the time.")
            if s["truth"] == "leak" and ret["rate"] > 0.10:
                out.append(f"- {s['cell']}, {rule}: the decay check would wrongly propose retiring a real rule {ret['rate']:.1%} of the time.")
            if s["truth"] == "decay" and ret["rate"] < 0.5:
                out.append(f"- {s['cell']}, {rule}: a dead rule is proposed for retirement only {ret['rate']:.1%} of the time.")
    return out or ["- No cell failed the bars above (false admission upper bound <= 5%, power >= 80%, wrongful retirement <= 10%)."]
