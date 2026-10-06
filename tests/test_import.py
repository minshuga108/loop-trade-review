from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app import service

c = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
REAL = (ROOT / "deploy_data" / "real_bitget" / "doge_trades_analysis.csv").read_text(encoding="utf-8")


def test_real_bitget_export_is_a_demo_trader_with_an_honest_label():
    t = {x["id"]: x for x in c.get("/api/traders").json()}
    assert "G" in t and t["G"]["available"] and t["G"]["n_trips"] == 67
    r = c.get("/api/review/G").json()
    assert "omits opening fees" in r["trader"]["label"] and r["trader"]["provenance"] == "REAL_PLATFORM_PUBLIC"
    assert all(f["status"] in ("UNDERPOWERED", "NOT_FLAGGED") for f in r["findings"])    # 11 winners in 67: nothing can be claimed


def test_bring_your_own_export_is_session_only_and_reviewable():
    H = {"X-Session": "pytest-import-1"}
    r = c.post("/api/import", json={"text": REAL}, headers=H)
    assert r.status_code == 200 and r.json()["n_trips"] == 67
    tid = r.json()["id"]
    mine = [x["id"] for x in c.get("/api/traders", headers=H).json()]
    other = [x["id"] for x in c.get("/api/traders", headers={"X-Session": "pytest-import-2"}).json()]
    assert tid in mine and tid not in other                  # a visitor's import is private to the session
    assert c.get(f"/api/review/{tid}", headers=H).status_code == 200


def test_unrecognised_or_oversized_files_are_refused_plainly():
    H = {"X-Session": "pytest-import-3"}
    r = c.post("/api/import", json={"text": "a,b,c\n1,2,3\n"}, headers=H)
    assert r.status_code == 422 and "could not recognise" in r.json()["detail"]
    r = c.post("/api/import", json={"text": "Date,Order ID,Direction,Futures\n" + "x" * 2_100_000}, headers=H)
    assert r.status_code in (413, 422)
    bad = REAL.replace("fully executed", "fully executed", 1).replace("Open long", "Sideways", 1)
    assert c.post("/api/import", json={"text": bad}, headers=H).status_code == 422
    assert service._DYN_OWNER.get("nonexistent") is None


# ---- CRIT21 final fixes: NaN on small imports, import size cap -------------------------------

def _hl_csv(n_lines: int) -> str:
    from pathlib import Path
    lines = (Path(__file__).resolve().parents[1] / "deploy_data" / "trader_samples" / "wallet_A.csv").read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:n_lines]) + "\n"


def test_small_import_review_has_no_nan_and_is_200():
    import json
    H = {"X-Session": "pytest-import-small"}
    for n in (150, 300):
        r = c.post("/api/import", json={"text": _hl_csv(n)}, headers=H)
        assert r.status_code == 200, r.text
        rv = c.get(f"/api/review/{r.json()['id']}", headers=H)
        assert rv.status_code == 200, rv.text
        json.loads(rv.text, parse_constant=lambda s: (_ for _ in ()).throw(AssertionError("non-finite " + s)))


def test_json_safe_and_global_response_safeguard():
    import math
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.service import SafeJSONResponse, json_safe
    assert json_safe({"a": [math.nan, math.inf, -math.inf, 1.5], "b": (float("nan"),)}) == {"a": [None, None, None, 1.5], "b": [None]}
    mini = FastAPI(default_response_class=SafeJSONResponse)

    @mini.get("/x")
    def x():
        return {"v": float("nan"), "w": [float("inf")]}
    assert TestClient(mini).get("/x").json() == {"v": None, "w": [None]}


def test_import_cap_matches_ui_promise_but_other_routes_keep_64kb():
    from app import ratelimit
    assert ratelimit.body_limit("/api/import") >= 2_000_000 + 100_000
    assert ratelimit.body_limit("/api/chat") == 64 * 1024
    big = _hl_csv(100000)
    assert len(big.encode()) > 65_536
    H = {"X-Session": "pytest-import-big"}
    r = c.post("/api/import", json={"text": big}, headers=H)
    assert r.status_code == 200, r.text[:200]
    assert c.post("/api/gate/B", json={"text": "x" * 70_000}, headers=H).status_code in (413, 422)
    r = c.post("/api/import", json={"text": "Date,Order ID,Direction,Futures\n" + "x" * 5_000_000}, headers=H)
    assert r.status_code == 413
