import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, w, h in (("desktop", 1366, 900), ("phone", 400, 900)):
        pg = b.new_page(viewport={"width": w, "height": h})
        pg.goto("http://127.0.0.1:8077/")
        pg.wait_for_selector("svg", timeout=20000)
        pg.screenshot(path=f"shot_{name}.png", full_page=True)
        print(name, "scrollWidth", pg.evaluate("document.documentElement.scrollWidth"), "clientWidth", pg.evaluate("document.documentElement.clientWidth"))
    pg = b.new_page(viewport={"width": 1366, "height": 900})
    pg.goto("http://127.0.0.1:8077/"); pg.wait_for_selector("svg")
    pg.click("button[data-id='F']"); pg.wait_for_timeout(2500)
    pg.screenshot(path="shot_planted.png", full_page=True)
    b.close()
