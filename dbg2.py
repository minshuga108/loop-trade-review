from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("response", lambda r: errs.append((r.status, r.url)) if r.status>=400 else None)
    pg.goto("http://127.0.0.1:8077/"); pg.wait_for_selector("#rbgo"); pg.click("button[data-id='F']"); pg.wait_for_timeout(2500)
    pg.click("#rbgo"); pg.wait_for_timeout(6000)
    print(errs); print(pg.inner_text("#rbmsg")); print(pg.inner_text("#rblist")[:200])
    b.close()
