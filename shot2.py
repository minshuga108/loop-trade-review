from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1366, "height": 900})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.goto("http://127.0.0.1:8077/"); pg.wait_for_selector("#chips button")
    pg.click("#chips button:nth-child(1)"); pg.wait_for_selector(".msg:not(.me)")
    pg.fill("#ci", "我最大的坏习惯是什么？"); pg.press("#ci", "Enter"); pg.wait_for_timeout(1500)
    pg.click("#chips button:nth-child(3)"); pg.wait_for_timeout(2500)
    pg.screenshot(path="shot_chat.png", full_page=True)
    print("errors:", errs)
    print(pg.inner_text("#chatlog")[:600].encode("ascii","replace").decode())
    b.close()
