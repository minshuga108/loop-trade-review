"""Facts for the first-screen 'Tested on real wallets' card. Every number is read from cohort_results.json."""
from __future__ import annotations

import json
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "cohort_results.json"


def facts() -> dict | None:
    if not _P.exists():
        return None
    d = json.loads(_P.read_text(encoding="utf-8"))
    s = d["detectors"]["size_after_loss"]
    pl = s["pooled"]
    return {"n_wallets": d["n_wallets"], "n_round_trips": d["n_round_trips"], "tested": s["tested"],
            "habit_after_correction": s["bh_significant"], "fdr_q": d["fdr_q"],
            "pooled_p": pl["p_pooled_shuffle"], "within_trader_p": round(pl["p_within_trader_shuffle"], 2),
            "court_wallets_accepted": d["court"]["wallets_with_any_accepted"], "court_trials": d["court"]["cohort_trials"],
            "provenance": d["provenance"], "source": "cohort_results.json", "proof": "/proof"}
