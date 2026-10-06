from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1366, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:8077/")
    pg.wait_for_selector("#rbgo")
    pg.click("button[data-id='F']")
    pg.wait_for_timeout(2500)
    pg.click("#rbgo")
    pg.wait_for_selector("#rblist .rule", timeout=30000)
    pg.click("#rblist button[data-a='arm']")
    pg.wait_for_timeout(1500)
    pg.fill("#gi", "Buy $200k RNVDA")
    pg.check("#gloss")
    pg.click(".gatebtn")
    pg.wait_for_timeout(1500)
    pg.locator("#rbcard").screenshot(path="shot_rulebook.png")
    print("errors:", errs)
    print(pg.inner_text("#gres")[:300].encode("ascii", "replace").decode())
    b.close()
