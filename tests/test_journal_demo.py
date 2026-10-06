import importlib
import os
import subprocess
import sys
from pathlib import Path

from adapters import bitget_v2_history
from app import service

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "deploy_data" / "real_bitget_journal"


def test_shipped_copy_loads_53_trips_and_has_no_free_text():
    raw = (DATA / "journal_verified.json").read_text(encoding="utf-8")
    assert "remark" not in raw and "entryReason" not in raw and "summery" not in raw
    trips, notes = bitget_v2_history.load(DATA / "journal_verified.json")
    assert len(trips) == 53 and notes == {}
    assert bitget_v2_history.parse.skipped["hand_entered"] == 0
    assert (DATA / "LICENSE").exists() and "MPL" in (DATA / "SOURCE.md").read_text(encoding="utf-8")


def test_default_trader_list_has_no_h():
    assert os.environ.get("LOOP_ENABLE_JOURNAL") != "1"
    assert [t["id"] for t in service.TRADERS] == ["A", "B", "C", "D", "E", "G", "F"]


def _ids(flag):
    env = dict(os.environ)
    env.pop("LOOP_ENABLE_JOURNAL", None)
    if flag:
        env["LOOP_ENABLE_JOURNAL"] = "1"
    code = ("from app import service as s;"
            "print(','.join(t['id'] for t in s.TRADERS));"
            "r=[t for t in s.traders() if t['id']=='H'];"
            "print(r[0]['n_trips'], r[0]['provenance'], r[0]['label'][:40]) if r else print('none')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout.split("\n")
    return out[0], out[1]


def test_enabled_only_with_env_flag():
    off_ids, off_h = _ids(False)
    on_ids, on_h = _ids(True)
    assert "H" not in off_ids.split(",") and off_h == "none"
    assert on_ids.split(",")[-2:] == ["G", "F"] or "H" in on_ids.split(",")
    assert on_h.startswith("53 REAL_PLATFORM_PUBLIC Real Bitget futures positions")
