"""Screenshots of the first screen: desktop/phone x light/dark x en/zh, above the fold and full page,
plus the loading, degraded, planted-trader, control-trader and chat states.

    python scripts/redesign_shots.py http://127.0.0.1:8091 [tag,tag,...|states]

Writes to data/redesign (C:/Users/neon_/bitget/data/redesign by default; LOOP_SHOTS_OUT overrides).
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8091"
OUT = os.environ.get("LOOP_SHOTS_OUT", r"C:\Users\neon_\bitget\data\redesign")
TAGS = sys.argv[2].split(",") if len(sys.argv) > 2 else None
os.makedirs(OUT, exist_ok=True)
problems = []


def watch(pg, tag):
    pg.on("console", lambda m: problems.append(f"{tag} console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: problems.append(f"{tag} pageerror: {e}"))
    pg.on("response", lambda r: problems.append(f"{tag} HTTP {r.status} {r.url}") if r.status >= 400 else None)


with sync_playwright() as p:
    b = p.chromium.launch()
    for dev, w, h in (("desktop", 1366, 768), ("phone", 400, 800)):
        for scheme in ("light", "dark"):
            for lang in ("en", "zh"):
                tag = f"{dev}_{scheme}_{lang}"
                if TAGS and tag not in TAGS:
                    continue
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, device_scale_factor=1)
                ctx.add_init_script(f"try{{localStorage.setItem('lang','{lang}');localStorage.removeItem('theme')}}catch(e){{}}")
                pg = ctx.new_page()
                watch(pg, tag)
                pg.goto(BASE + "/")
                pg.wait_for_selector("#onelook", timeout=90000)
                pg.wait_for_timeout(2500)
                sw = pg.evaluate("document.documentElement.scrollWidth")
                cw = pg.evaluate("document.documentElement.clientWidth")
                fold = pg.evaluate("(() => { const r = document.querySelector('#ci').getBoundingClientRect(); return Math.round(r.bottom); })()")
                print(tag, "scrollWidth", sw, "clientWidth", cw, "ask-input bottom", fold, "viewport", h)
                pg.screenshot(path=os.path.join(OUT, f"after_{tag}_fold.png"))
                pg.screenshot(path=os.path.join(OUT, f"after_{tag}_full.png"), full_page=True)
                ctx.close()
    if not TAGS or "states" in TAGS:
        ctx = b.new_context(viewport={"width": 1366, "height": 768})
        pg = ctx.new_page()
        pg.route("**/api/traders", lambda route: route.abort())
        pg.goto(BASE + "/")
        pg.wait_for_selector(".down", timeout=20000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(OUT, "after_state_down.png"))
        pg.unroute_all(behavior="ignoreErrors")
        ctx.close()

        ctx = b.new_context(viewport={"width": 1366, "height": 768})
        pg = ctx.new_page()
        held = []
        pg.route("**/api/toggle/*", lambda route: held.append(route))      # never answered: the skeleton stays
        pg.goto(BASE + "/")
        pg.wait_for_selector(".sk", timeout=20000)
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(OUT, "after_state_skeleton.png"))
        pg.unroute_all(behavior="ignoreErrors")
        ctx.close()

        ctx = b.new_context(viewport={"width": 1366, "height": 768})
        pg = ctx.new_page()
        pg.route("**/api/review/*", lambda route: route.abort())
        pg.goto(BASE + "/")
        pg.wait_for_selector(".down", timeout=20000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(OUT, "after_state_trader_down.png"))
        pg.unroute_all(behavior="ignoreErrors")
        ctx.close()

        ctx = b.new_context(viewport={"width": 1366, "height": 768})
        pg = ctx.new_page()
        watch(pg, "states")
        pg.goto(BASE + "/")
        pg.wait_for_selector("#onelook", timeout=90000)
        pg.click("button[data-id='F']")
        pg.wait_for_timeout(3000)
        pg.screenshot(path=os.path.join(OUT, "after_state_planted_F.png"))
        pg.click("button[data-id='A']")
        pg.wait_for_timeout(3000)
        pg.screenshot(path=os.path.join(OUT, "after_state_control_A.png"))
        pg.click("button[data-id='B']")
        pg.wait_for_timeout(3000)
        pg.click("#chips button")
        pg.wait_for_timeout(4000)
        pg.evaluate("document.querySelector('#ask').scrollIntoView()")
        pg.screenshot(path=os.path.join(OUT, "after_state_chat.png"))
        ctx.close()
    if not TAGS or "phone_extra" in TAGS:
        ctx = b.new_context(viewport={"width": 400, "height": 800})
        pg = ctx.new_page()
        watch(pg, "phone_extra")
        pg.goto(BASE + "/")
        pg.wait_for_selector("#onelook", timeout=90000)
        pg.wait_for_timeout(1500)
        pg.evaluate("document.querySelector('#court').scrollIntoView()")
        pg.screenshot(path=os.path.join(OUT, "after_phone_light_en_court.png"))
        pg.click("#chips button")
        pg.wait_for_timeout(3500)
        pg.screenshot(path=os.path.join(OUT, "after_phone_light_en_chat.png"))
        print("phone_extra scrollWidth", pg.evaluate("document.documentElement.scrollWidth"))
        ctx.close()
    b.close()
print("problems:", json.dumps(problems, indent=1) if problems else "none")
