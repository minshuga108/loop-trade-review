"""/video page, /media range serving and traversal safety, snapshot file, claims URLs, keep-warm helper."""
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

import claims
from app.main import app

c = TestClient(app, raise_server_exceptions=False)
ROOT = Path(__file__).resolve().parents[1]
VID = "/media/loop_demo.webm"


def test_video_page_and_links():
    r = c.get("/video")
    assert r.status_code == 200 and "/media/loop_demo.webm" in r.text and 'href="/"' in r.text
    assert "This is Loop." in r.text and "这是 Loop" in r.text               # both languages' transcript
    home = c.get("/").text
    assert 'href="/video"' in home and "snapshot.js" in home


def test_media_full_and_range():
    size = (ROOT / "deploy_data/media/loop_demo.webm").stat().st_size
    r = c.get(VID)
    assert r.status_code == 200 and r.headers["content-type"] == "video/webm"
    assert r.headers["accept-ranges"] == "bytes" and len(r.content) == size
    r = c.get(VID, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100 and r.headers["content-range"] == f"bytes 0-99/{size}"
    r = c.get(VID, headers={"Range": "bytes=-10"})
    assert r.status_code == 206 and len(r.content) == 10
    r = c.get(VID, headers={"Range": f"bytes={size - 5}-"})
    assert r.status_code == 206 and len(r.content) == 5
    assert c.get(VID, headers={"Range": f"bytes={size}-"}).status_code == 416
    assert c.get(VID, headers={"Range": "bytes=abc"}).status_code == 416


def test_media_traversal_and_types():
    for bad in ["../main.py", "..%2Fmain.py", "%2e%2e%2fmain.py", "..%5Cmain.py", "nope.webm",
                "loop_demo.webm%00.txt", ".hidden.webm", "README.md", "loop_demo.exe"]:
        assert c.get("/media/" + bad).status_code in (404, 400, 422), bad
    assert c.post(VID).status_code == 405


def test_snapshot_file_is_complete():
    s = json.loads((ROOT / "app/static/snapshot.json").read_text(encoding="utf-8"))
    assert s["generated"] and s["traders"]
    for t in s["traders"]:
        assert t["id"] in s["review"] and f"{t['id']}|cap" in s["toggle"] and f"{t['id']}|halt" in s["toggle"]
    assert c.get("/static/snapshot.json").status_code == 200


def test_snapshot_js_falls_back_and_banners():
    js = (ROOT / "app/static/snapshot.js").read_text(encoding="utf-8")
    assert "Live server unreachable, showing snapshot from" in js and "/static/snapshot.json" in js
    assert "status < 500" in js                                                  # only outages fall back, not 4xx


def test_claims_urls_rendered():
    assert claims.VIDEO_URL == claims.LIVE_URL + "/video"
    for name in ("README.md", "SUBMISSION.md"):
        t = (ROOT / name).read_text(encoding="utf-8")
        assert "<DEMO URL>" not in t and "<VIDEO URL>" not in t and "<REPO URL>" not in t
        assert claims.LIVE_URL in t
    assert claims.REPO_URL in (ROOT / "SUBMISSION.md").read_text(encoding="utf-8")


def test_keep_warm_importable_and_once_flag():
    spec = importlib.util.spec_from_file_location("keep_warm", ROOT / "scripts/keep_warm.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert callable(m.ping) and "--once" in (ROOT / "scripts/keep_warm.py").read_text(encoding="utf-8")
