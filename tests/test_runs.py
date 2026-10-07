import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runs_api, validation_note
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
c = TestClient(app)
T0 = 1_767_225_600


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_RUNS_DIR", str(tmp_path / "live"))
    monkeypatch.setenv("LOOP_RUNS_SEED_DIR", str(tmp_path / "seed"))
    (tmp_path / "seed").mkdir()
    return tmp_path


def test_freeze_chain_append_only_and_seed_merge(dirs):
    fd = importlib.import_module("freeze_daily")
    first = fd.freeze(day="2026-01-01", net=False, now=T0)
    assert len(first) >= 5 and first[0]["prev"] == runs_api.GENESIS
    assert all(b["prev"] == a["hash"] for a, b in zip(first, first[1:]))
    f = dirs / "live" / "runs.jsonl"
    before = f.read_text(encoding="utf-8")
    assert fd.freeze(day="2026-01-01", net=False, now=T0 + 100) == []           # same day: nothing added
    assert f.read_text(encoding="utf-8") == before
    assert runs_api.load_chain()["ok"]
    # ship the file as the seed, wipe live (ephemeral disk), continue from the seed's tip
    (dirs / "seed" / "runs_seed.jsonl").write_text(before, encoding="utf-8")
    f.unlink()
    second = fd.freeze(day="2026-01-02", net=False, now=T0 + 86400)
    assert second[0]["prev"] == first[-1]["hash"] and second[0]["seq"] == len(first) + 1
    ch = runs_api.load_chain()
    assert ch["ok"] and len(ch["entries"]) == len(first) + len(second)
    # entries present in both files are not doubled
    f.write_text(before + f.read_text(encoding="utf-8"), encoding="utf-8")
    assert len(runs_api.load_chain()["entries"]) == len(first) + len(second)


def test_tamper_is_reported(dirs):
    fd = importlib.import_module("freeze_daily")
    fd.freeze(day="2026-01-01", net=False, now=T0)
    f = dirs / "live" / "runs.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[1])
    e["trader"] = "ZZ"
    lines[1] = json.dumps(e)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    v = c.get("/api/runs").json()
    assert not v["chain_ok"] and v["broken_at"] == 2 and v["n"] == len(lines)


def test_scoring_waits_24h_labels_basis_and_never_fabricates(dirs, monkeypatch):
    fd = importlib.import_module("freeze_daily")
    sr = importlib.import_module("score_runs")
    ents = fd.freeze(day="2026-01-01", net=False, now=T0)
    assert sr.run(now=T0 + 3600, net=False) == []                               # younger than 24h: nothing
    done = sr.run(now=T0 + 90000, net=False)
    assert done and {s["component"] for s in done} == {"reproduce"}             # no book, no new trades: only the replay is knowable
    assert all(s["basis"] == "replay" and s["state"] in ("scored", "missed") for s in done)
    assert sr.run(now=T0 + 99999, net=False) == []                              # final scores are never rewritten
    v = c.get("/api/runs").json()
    assert v["n"] == len(ents)
    assert v["entries"][0]["components"]["cost"]["state"] == "pending"
    assert v["entries"][0]["components"]["rule"]["state"] == "pending"
    # a missed replay stays visible
    monkeypatch.setattr(sr.T, "thesis_hash", lambda facts, day: "0" * 64)
    (dirs / "live" / "scores.jsonl").unlink()
    sr.run(now=T0 + 90000, net=False)
    assert c.get("/api/runs").json()["counts"]["missed"] == len(ents)


def test_runs_page_i18n_and_links():
    assert c.get("/runs").status_code == 200
    body = (ROOT / "app" / "static" / "runs.html").read_text(encoding="utf-8")
    assert "onclick" not in body and body.count("<script>") == 1
    assert 'href="/runs"' in c.get("/").text and 'href="/runs"' in c.get("/wrong").text
    assert "每日运行" in (ROOT / "app" / "static" / "i18n.js").read_text(encoding="utf-8")
    assert c.post("/api/runs").status_code == 405


def test_shipped_seed_chain_verifies():
    p = ROOT / "deploy_data" / "runs_seed.jsonl"
    assert p.exists()
    prev = runs_api.GENESIS
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        e = json.loads(line)
        assert e["prev"] == prev and e["seq"] == i and runs_api.entry_hash(e) == e["hash"]
        prev = e["hash"]


def test_validation_note_for_d_from_file_and_nothing_elsewhere(monkeypatch, tmp_path):
    n = validation_note.note_for("D", -1964.0)
    d = json.loads((ROOT / "validation_results.json").read_text(encoding="utf-8"))["pbo"]["real"]["D"]
    assert n and f"{d['pbo']:.2f}" in n["en"] and f"{d['pbo']:.2f}" in n["zh"] and "NOT confirm" in n["en"] and "没有证实" in n["zh"]
    assert validation_note.note_for("A") is None and validation_note.note_for("nope") is None
    assert c.get("/api/review/D").json()["validation_note"]["trader"] == "D"
    assert "validation_note" not in c.get("/api/review/A").json()
    assert "VALIDATION" in c.get("/validation").text
    monkeypatch.setattr(validation_note, "FILE", tmp_path / "missing.json")
    validation_note._cache.update(mt=None, d=None)
    assert validation_note.note_for("D") is None
    validation_note._cache.update(mt=None, d=None)
