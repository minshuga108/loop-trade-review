"""Measure a deployed Loop URL the way a first-time judge meets it.

    python scripts/cold_visit.py https://your-host.example            # HTTP checks
    python scripts/cold_visit.py https://your-host.example --browser  # plus Playwright, desktop and 400 px phone

HTTP checks (fresh client, no cookies, no auth): time to first byte of '/',
total HTML + same-origin JS/CSS bytes, no login wall, /api/health ok.
Browser checks (Playwright Chromium, fresh context each time): time until the
first trader card and the first curve render, and whether the page scrolls
horizontally, on a desktop viewport and a 400 px-wide phone viewport; also the
overflow check on /cockpit and /selftest.

Budgets: first byte 1.5 s, first-screen weight under 1 MB, no login.
Prints a pass/fail table; exit code 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import httpx

BUDGET_TTFB_S = 1.5
BUDGET_BYTES = 1_000_000
BUDGET_RENDER_S = 5.0            # first trader card and curve visible (browser variant)
VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "phone": {"width": 400, "height": 860}}
ASSET_RX = re.compile(r"""<(?:script[^>]+src|link[^>]+href)\s*=\s*["']([^"']+)["']""", re.I)


def same_origin_assets(html: str, base: str) -> list[str]:
    host = urlparse(base).netloc
    out = []
    for u in ASSET_RX.findall(html):
        full = urljoin(base, u)
        if urlparse(full).netloc == host and full not in out:
            out.append(full)
    return out


def measure_http(base: str, client: httpx.Client | None = None) -> dict:
    """client may be any httpx.Client (tests pass a FastAPI TestClient; nothing touches the network)."""
    own = client is None
    c = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": "loop-cold-visit/1"})
    try:
        root = urljoin(base.rstrip("/") + "/", "")
        t0 = time.perf_counter()
        with c.stream("GET", root) as r:
            ttfb = None
            body = b""
            for chunk in r.iter_bytes():
                if ttfb is None:
                    ttfb = time.perf_counter() - t0
                body += chunk
            total_s = time.perf_counter() - t0
            if ttfb is None:
                ttfb = total_s
            status, history, final_url, cookies = r.status_code, list(r.history), str(r.url), r.headers.get_list("set-cookie")
        html = body.decode("utf-8", "replace")
        assets = []
        for u in same_origin_assets(html, root):
            a = c.get(u)
            assets.append({"url": u, "status": a.status_code, "bytes": len(a.content)})
        weight = len(body) + sum(a["bytes"] for a in assets)
        try:
            h = c.get(urljoin(root, "api/health"))
            health_ok = h.status_code == 200 and h.json().get("ok") is True
        except Exception:
            health_ok = False
        login_wall = (status in (401, 403) or "login" in urlparse(final_url).path.lower()
                      or 'type="password"' in html.lower() or bool(history and urlparse(final_url).netloc != urlparse(root).netloc))
        return {"status": status, "ttfb_s": ttfb, "total_s": total_s, "html_bytes": len(body), "assets": assets,
                "weight_bytes": weight, "health_ok": health_ok, "no_login": status == 200 and not login_wall,
                "sets_cookie": bool(cookies), "final_url": final_url}
    finally:
        if own:
            c.close()


def http_checks(m: dict) -> list[dict]:
    return [
        {"check": "first byte of '/'", "value": f"{m['ttfb_s']:.3f} s", "budget": f"<= {BUDGET_TTFB_S} s", "pass": m["ttfb_s"] <= BUDGET_TTFB_S},
        {"check": "first-screen weight (HTML + same-origin JS/CSS)", "value": f"{m['weight_bytes']:,} B", "budget": f"< {BUDGET_BYTES:,} B", "pass": m["weight_bytes"] < BUDGET_BYTES},
        {"check": "loads with no cookie, login or key", "value": f"HTTP {m['status']}", "budget": "200, no login wall", "pass": m["no_login"]},
        {"check": "/api/health ok", "value": str(m["health_ok"]), "budget": "True", "pass": m["health_ok"]},
        {"check": "every same-origin asset loads", "value": f"{sum(a['status'] == 200 for a in m['assets'])} of {len(m['assets'])}", "budget": "all", "pass": all(a["status"] == 200 for a in m["assets"])},
    ]


def browser_checks(base: str, headless: bool = True) -> list[dict]:
    from playwright.sync_api import sync_playwright

    out = []
    root = base.rstrip("/") + "/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            for name, vp in VIEWPORTS.items():
                ctx = browser.new_context(viewport=vp, is_mobile=(name == "phone"), has_touch=(name == "phone"))   # fresh: no cookies, no storage
                page = ctx.new_page()
                t0 = time.perf_counter()
                page.goto(root, wait_until="commit")
                try:
                    page.wait_for_selector("#picker button", timeout=BUDGET_RENDER_S * 4000)
                    t_card = time.perf_counter() - t0
                except Exception:
                    t_card = None
                try:
                    page.wait_for_selector("#main svg path", timeout=BUDGET_RENDER_S * 4000)
                    t_curve = time.perf_counter() - t0
                except Exception:
                    t_curve = None
                out.append({"check": f"{name}: first trader card visible", "value": "never" if t_card is None else f"{t_card:.2f} s",
                            "budget": f"<= {BUDGET_RENDER_S} s", "pass": t_card is not None and t_card <= BUDGET_RENDER_S})
                out.append({"check": f"{name}: P&L curve drawn", "value": "never" if t_curve is None else f"{t_curve:.2f} s",
                            "budget": f"<= {BUDGET_RENDER_S} s", "pass": t_curve is not None and t_curve <= BUDGET_RENDER_S})
                for path in ("", "cockpit", "selftest"):
                    if path:
                        page.goto(root + path, wait_until="networkidle")
                    else:
                        page.wait_for_load_state("networkidle")
                    sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                    out.append({"check": f"{name}: /{path} has no horizontal scroll", "value": f"scrollWidth {sw}, viewport {cw}",
                                "budget": "scrollWidth <= viewport", "pass": sw <= cw})
                ctx.close()
        finally:
            browser.close()
    return out


def print_table(rows: list[dict]) -> None:
    w = max(len(r["check"]) for r in rows)
    wv = max(len(r["value"]) for r in rows)
    for r in rows:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['check']:<{w}}  {r['value']:<{wv}}  budget {r['budget']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="deployed base URL, e.g. https://loop.example.com")
    ap.add_argument("--browser", action="store_true", help="also run the Playwright checks (desktop and 400 px phone)")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    a = ap.parse_args(argv)
    if not a.url.startswith(("http://", "https://")):
        ap.error("url must start with http:// or https://")
    rows = http_checks(measure_http(a.url))
    if a.browser:
        rows += browser_checks(a.url, headless=not a.headed)
    print(f"Cold visit: {a.url}")
    print_table(rows)
    ok = all(r["pass"] for r in rows)
    print(f"\n{sum(r['pass'] for r in rows)} of {len(rows)} checks passed: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
