from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1366, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:8077/")
    pg.wait_for_selector("#chips button")
    pg.wait_for_timeout(1500)
    pg.click("#langbtn")
    pg.wait_for_timeout(1500)
    pg.screenshot(path="shot_zh.png", full_page=True)
    left = pg.evaluate("""() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); const out = []; let n;
      while ((n = w.nextNode())) { const t = n.nodeValue.trim(); if (t && /[A-Za-z]{4,}/.test(t) && !/[一-鿿]/.test(t)) out.push(t.slice(0, 70)); } return out.slice(0, 40); }""")
    print("errors:", errs)
    print("still English:", [x.encode("ascii", "replace").decode() for x in left])
    b.close()
