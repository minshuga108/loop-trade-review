"""Record the Loop walkthrough as a silent captioned video (Playwright Chromium, 1280x720).

    .venv\\Scripts\\python.exe scripts\\record_demo.py [--out C:\\Users\\neon_\\bitget\\demo_video]

Starts the app on a free local port with a throw-away record/anchor/call-log (env vars), drives the VIDEO_SCRIPT.md
flow with human-like pacing, burns an on-screen caption per scene (the narration text, nothing new), and writes
loop_demo.webm, captions.txt and scene-end frames.  An .mp4 is made only if ffmpeg is already on PATH.
Does not touch the real record.  Needs no key and no login.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "deploy_data" / "real_bitget" / "doge_trades_analysis.csv"
W, H = 1280, 720

# (title, narration exactly from VIDEO_SCRIPT.md, minimum seconds on this scene)
N = {
    "home": "This is Loop. It reviews a trader's own trades. This is a public wallet, hand-picked and labelled illustrative. In one look: one habit, what it cost in dollars, and what the rule court decided.",
    "ask": "I ask in plain words. The answer is computed from the fills, not written by a model: every number is locked to a computed fact. The pattern is sizing up after a loss, with a range that is honest about how little data there is.",
    "court": "Here is what a rule would have changed. On the trades it was built from it looks good. On trades it never saw it does not hold up, so the court says no. A tool that always says yes is fooling itself.",
    "arm": "To show what a pass looks like, this simulated trader has a costly habit built in. The rule is tested on later trades, every proposal is counted, and this one passes. Nothing is armed until I click. Now it is guarding my orders. Paper only.",
    "gate": "I ask the gate about an idea. Last trade lost and this size breaks my own rule, so it is blocked, with a checklist built from my own losses and a live Bitget order-book cost. The gate never places an order.",
    "zh": "I can ask what would make this wrong, and in Chinese. It tells me what it did not test.",
    "weekly": "The weekly review follows the fupan template: what happened, the priority finding, what would make it wrong, tomorrow's plan, what changed, and what we assumed or are missing.",
    "import": "Bring your own history: a real Bitget futures export is read in memory for this session only, is not stored, and needs no key.",
    "evidence": "Everything we got wrong is public. The court admits more false rules than it should in some cases, and power is low on short histories. That is why the honest answer is often 'not enough trades yet'.",
}

CAPTION_JS = """
(text) => {
  let d = document.getElementById('__cap');
  if (!d) {
    d = document.createElement('div'); d.id = '__cap';
    d.style.cssText = 'position:fixed;left:50%;bottom:18px;transform:translateX(-50%);width:min(1100px,92vw);' +
      'box-sizing:border-box;padding:12px 20px;background:rgba(15,18,24,.88);color:#fff;font:600 21px/1.35 system-ui,Segoe UI,sans-serif;' +
      'text-align:center;border-radius:10px;z-index:2147483647;pointer-events:none;box-shadow:0 4px 18px rgba(0,0,0,.35)';
    document.documentElement.appendChild(d);
  }
  d.textContent = text; d.style.display = text ? 'block' : 'none';
}
"""
CURSOR_INIT = """
(() => {
  const mk = () => {
    if (document.getElementById('__cur') || !document.documentElement) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.style.cssText = 'position:fixed;left:0;top:0;width:18px;height:18px;margin:-3px 0 0 -3px;border-radius:50%;' +
      'background:rgba(255,80,60,.85);border:2px solid #fff;box-shadow:0 0 6px rgba(0,0,0,.6);z-index:2147483646;pointer-events:none';
    document.documentElement.appendChild(c);
  };
  addEventListener('mousemove', (e) => { mk(); const c = document.getElementById('__cur'); if (c) c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; }, true);
})();
"""


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Users\neon_\bitget\demo_video")
    ap.add_argument("--speed", type=float, default=1.0, help="multiply every pause (default 1.0)")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    frames = out / "frames"; frames.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="loop_demo_"))
    port = free_port(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, LOOP_RECORD_PATH=str(tmp / "record" / "record.jsonl"), LOOP_RECORD_SALT="demo-salt",
               LOOP_ANCHOR_DIR=str(tmp / "anchors"), LOOP_BITGET_CALL_LOG=str(tmp / "bitget_calls.jsonl"),
               LOOP_RATELIMIT="off")
    log = open(tmp / "server.log", "w")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    problems: list[str] = []
    caps: list[str] = []
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=2); break
            except Exception:
                time.sleep(0.5)
        else:
            print("server did not start"); return 1

        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp / "vid"),
                                record_video_size={"width": W, "height": H}, color_scheme="light")
            ctx.add_init_script("try{localStorage.setItem('lang','en');localStorage.removeItem('theme')}catch(e){}")
            ctx.add_init_script(CURSOR_INIT)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
            pg.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
            pg.on("console", lambda m: problems.append(f"console.error: {m.text}") if m.type == "error" else None)
            t_start = time.time()
            pos = [200, 200]

            def wait(s):
                pg.wait_for_timeout(int(s * 1000 * a.speed))

            def move(sel):
                el = pg.locator(sel).first
                el.scroll_into_view_if_needed()
                wait(0.4)
                bx = el.bounding_box()
                x, y = bx["x"] + bx["width"] / 2, bx["y"] + min(bx["height"] / 2, 20)
                pg.mouse.move(x, y, steps=25)
                pos[:] = [x, y]
                wait(0.5)

            def click(sel):
                move(sel); pg.locator(sel).first.click(); wait(0.6)

            def type_into(sel, text):
                click(sel); pg.locator(sel).first.press_sequentially(text, delay=95); wait(0.6)

            def smooth_scroll(sel, block="start"):
                pg.evaluate("(s) => document.querySelector(s).scrollIntoView({behavior:'smooth', block:'%s'})" % block, sel)
                wait(1.4)

            def scene(name, min_s, fn):
                text = N[name]
                caps.append(text)
                pg.evaluate(CAPTION_JS, text)
                t0 = time.time()
                fn()
                left = min_s * a.speed - (time.time() - t0)
                if left > 0:
                    pg.wait_for_timeout(int(left * 1000))
                pg.screenshot(path=str(frames / f"{len(caps):02d}_{name}.png"))
                print(f"scene {name}: {time.time() - t0:.1f}s")

            def recaption(name):
                pg.evaluate(CAPTION_JS, N[name])

            def goto_home():
                pg.goto(base + "/")
                pg.wait_for_selector("#onelook", timeout=90000)
                pg.wait_for_selector("#chips button")
                pg.evaluate(CAPTION_JS, N["home"])

            def s_home():
                goto_home()
                wait(2)
                pg.mouse.move(640, 300, steps=30)
                wait(2)
                move("#onelook .verdicts, #onelook")
                wait(3)

            def last_answer():
                pg.wait_for_selector(".msg:not(.me)", timeout=60000)
                wait(1.5)

            def s_ask():
                smooth_scroll("#ask")
                click("#chips button:nth-child(1)")
                last_answer()
                det = pg.locator("#asklog details, #chatlog details, .msg details").last
                if det.count():
                    det.locator("summary").first.scroll_into_view_if_needed()
                    move(".msg details summary")
                    pg.locator(".msg details summary").last.click(); wait(3)

            def s_court():
                smooth_scroll("#hero-chart", "center")
                wait(3)
                click("#tg"); wait(3)
                click("#tg"); wait(3)
                move("#hero-chart .nums")
                wait(3)

            def s_arm():
                pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); wait(1.2)
                click("button[data-id='F']")
                pg.wait_for_selector("#rbgo", timeout=60000); wait(2.5)
                smooth_scroll("#rbcard")
                click("#rbgo")
                pg.wait_for_selector("#rblist .rule", timeout=60000); wait(3)
                click("#rblist button[data-a='arm']"); wait(3)

            def s_gate():
                smooth_scroll("#gate", "center")
                type_into("#gi", "Buy $200k RNVDA")
                click("#gloss")
                click(".gatebtn")
                pg.wait_for_selector("#gres *", timeout=60000); wait(7)
                pg.screenshot(path=str(frames / "05a_gate_blocked.png"))
                click("#gloss"); click(".gatebtn"); wait(5)

            def ask_text(q):
                smooth_scroll("#ask")
                type_into("#ci", q)
                n = pg.locator(".msg:not(.me)").count()
                pg.keyboard.press("Enter")
                pg.wait_for_function("(n) => document.querySelectorAll('.msg:not(.me)').length > n", arg=n, timeout=60000)
                wait(3)

            def s_zh():
                ask_text("what would make this wrong?")
                wait(2)
                ask_text("我最大的坏习惯是什么？")
                wait(2)

            def s_weekly():
                ask_text("show my weekly review"); wait(1)
                pg.evaluate("document.querySelectorAll('.msg:not(.me)').length && document.querySelectorAll('.msg:not(.me)')[document.querySelectorAll('.msg:not(.me)').length-1].scrollIntoView({behavior:'smooth',block:'start'})")
                wait(4)
                for _ in range(2):
                    pg.mouse.wheel(0, 200); wait(3)

            def s_import():
                pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); wait(1.2)
                click("#importbtn")
                pg.wait_for_selector("#importfile")
                move("#importfile")
                pg.set_input_files("#importfile", str(CSV)); wait(1.5)
                click("#importgo")
                pg.wait_for_selector("#onelook", timeout=60000); wait(2)
                pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); wait(2)
                pg.mouse.wheel(0, 300); wait(3)

            def s_evidence():
                pg.goto(base + "/evidence")
                pg.wait_for_selector("#main table, #main section, #main h2", timeout=60000)
                pg.evaluate(CAPTION_JS, N["evidence"])
                wait(2.5)
                for _ in range(2):
                    pg.mouse.wheel(0, 320); wait(2.5)

            scene("home", 15, s_home)
            scene("ask", 25, s_ask)
            scene("court", 28, s_court)
            scene("arm", 28, s_arm)
            scene("gate", 32, s_gate)
            scene("zh", 18, s_zh)
            scene("weekly", 22, s_weekly)
            scene("import", 15, s_import)
            scene("evidence", 16, s_evidence)
            wait(1)
            total = time.time() - t_start
            ctx.close()
            vid = Path(pg.video.path())
            b.close()
        dest = out / "loop_demo.webm"
        shutil.copy(vid, dest)
        (out / "captions.txt").write_text(
            "Loop demo narration (read each line aloud while its caption is on screen)\n\n" +
            "\n\n".join(f"{i}. {t}" for i, t in enumerate(caps, 1)) + "\n", encoding="utf-8")
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-y", "-i", str(dest), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out / "loop_demo.mp4")], check=False)
        print(f"video {dest} about {total:.0f}s; frames in {frames}")
        print("problems:", problems or "none")
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
