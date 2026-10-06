"""Real-browser checks (Playwright Chromium) against an in-process uvicorn on a free port.

1. With the security headers and rate limits ON, the first screen loads, the chat answers,
   the gate answers, the rule toggle and the language switch work, and no page logs a
   console error or a CSP violation.
2. XSS: <script>, <img onerror> and attribute-breaking strings are pushed through every path
   that reaches innerHTML (trader label and blurb, chat answer fields, gate idea, reasons and
   checklist, the user's own echoed message). No injected element may appear in the DOM and
   no injected code may run.

Skipped when Playwright or its Chromium is not installed.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")
import uvicorn  # noqa: E402

from app import chat as chat_mod  # noqa: E402
from app import ratelimit, service  # noqa: E402
from app.main import app  # noqa: E402

MARK = "window.__xss=(window.__xss||0)+1"
PAYLOADS = [f"<script>{MARK}</script>", f"<img src=x onerror=\"{MARK}\">", f"\"><svg onload=\"{MARK}\">",
            f"'><img src=x onerror='{MARK}'>", f"<iframe srcdoc=\"<script>{MARK}</script>\"></iframe>"]
P = " ".join(PAYLOADS)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    th.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                       # pragma: no cover - no browser on this machine
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


def wait_js(page, expr: str, timeout: int = 30_000) -> None:
    """Poll an expression through page.evaluate (CDP), which the page's CSP does not govern;
    page.wait_for_function compiles its predicate with eval, which our CSP rightly refuses."""
    end = time.monotonic() + timeout / 1000
    while time.monotonic() < end:
        if page.evaluate(expr):
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {expr}")


def _watch(page):
    problems = []
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    return problems


def test_pages_work_with_security_headers_and_rate_limits_on(base_url, browser, monkeypatch):
    monkeypatch.setenv("LOOP_RATELIMIT", "on")
    ratelimit.reset()
    page = browser.new_page()
    problems = _watch(page)
    resp = page.goto(base_url + "/")
    assert "content-security-policy" in resp.headers
    page.wait_for_selector("#onelook", timeout=60_000)
    page.fill("#ci", "What is my biggest costly habit?")
    page.press("#ci", "Enter")
    wait_js(page, "document.querySelectorAll('#chatlog .msg').length >= 2", timeout=30_000)
    assert "Interpreted as" in page.inner_text("#chatlog")
    page.fill("#gi", "Buy $20k rNVDA")
    page.click("#gf button")
    wait_js(page, "document.querySelector('#gres').textContent.includes('Read:')", timeout=30_000)
    page.select_option("#rk", "cap")
    wait_js(page, "document.querySelector('#rk') && document.querySelector('#rk').value === 'cap'", timeout=60_000)
    page.wait_for_selector("#onelook", timeout=60_000)
    page.click("#langbtn")                                   # was an inline onclick; now wired in i18n.js
    wait_js(page, "document.documentElement.lang === 'zh-CN'", timeout=10_000)
    page.click("#langbtn")
    for path, sel in (("/cockpit", "#sources table"), ("/record", "#nums .num"), ("/selftest", "#first")):
        page.goto(base_url + path)
        page.wait_for_selector(sel, timeout=30_000)
    page.close()
    # Known and not header-related: /cockpit probes /verify to see whether that page ships in this build;
    # while it does not, the probe's 404 is logged by Chromium. Everything else must be clean.
    probe = [p for p in problems if p.endswith("/verify") and p.startswith("HTTP 404")]
    rest = [p for p in problems if p not in probe and not (probe and "status of 404" in p)]
    assert not rest, problems


@pytest.fixture
def poisoned(monkeypatch):
    """Every server string that reaches innerHTML carries the payloads."""
    monkeypatch.setattr(service, "LABEL", P)
    monkeypatch.setattr(service, "LABEL_PLANTED", P)
    traders = [dict(t, blurb=P) for t in service.TRADERS]
    monkeypatch.setattr(service, "TRADERS", traders)
    service._REVIEW_CACHE.clear()
    service._load.cache_clear()

    real_answer = chat_mod.answer

    def answer(tid, message, history=None, sid="default"):
        out = real_answer(tid, message, history, sid)
        out.update(text=P + " " + out.get("text", ""), interpreted=P, number_lock=P, next=[P, "habit"],
                   facts=[{"fact": P, "value": P}], steps=[{"name": P, "ms": P}])
        return out
    monkeypatch.setattr(chat_mod, "answer", answer)

    real_gate = service.gate_check

    def gate_check(sid, tid, text, after_loss=None):
        out = real_gate(sid, tid, text, after_loss)
        out["idea"] = {"side": P, "symbol": P, "notional": P}
        out["reasons"] = [P]
        out["checklist"] = [{"id": "x", "text": P}]
        out["note"] = P
        out["state"] = P
        out["check_line"] = {"available": False, "reason": P}
        return out
    monkeypatch.setattr(service, "gate_check", gate_check)
    yield
    service._REVIEW_CACHE.clear()
    service._load.cache_clear()


def _assert_clean(page):
    assert page.evaluate("window.__xss === undefined"), "injected code ran"
    injected = page.evaluate("""() => ({
        img: document.querySelectorAll('img[src="x"]').length,
        svg: [...document.querySelectorAll('svg')].filter(s => s.getAttribute('onload')).length,
        iframe: document.querySelectorAll('iframe').length,
        scripts: [...document.querySelectorAll('script')].filter(s => s.textContent.includes('__xss')).length,
        handlers: [...document.querySelectorAll('*')].filter(e => [...e.attributes].some(a => a.name.startsWith('on'))).length })""")
    assert injected == {"img": 0, "svg": 0, "iframe": 0, "scripts": 0, "handlers": 0}, injected


def test_xss_payloads_never_become_markup(base_url, browser, poisoned):
    page = browser.new_page()
    problems = _watch(page)
    page.goto(base_url + "/")
    page.wait_for_selector("#onelook", timeout=60_000)
    assert "<script>" in page.inner_text("#strip") and "<img" in page.inner_text("#picker")   # shown as text
    page.fill("#ci", "habit " + PAYLOADS[1])                 # the user's own message, echoed into the log
    page.press("#ci", "Enter")
    wait_js(page, "document.querySelectorAll('#chatlog .msg').length >= 2", timeout=30_000)
    page.click("#chatlog details summary")
    page.fill("#gi", "Buy $20k rNVDA " + PAYLOADS[0])
    page.click("#gf button")
    wait_js(page, "document.querySelector('#gres').textContent.includes('Read:')", timeout=30_000)
    assert "<svg" in page.inner_text("#gres")
    page.click("#chatlog button[data-q]")                  # a "next" chip whose text is the payload
    wait_js(page, "document.querySelectorAll('#chatlog .msg').length >= 4", timeout=30_000)
    _assert_clean(page)
    page.close()
    assert not [p for p in problems if "Content Security Policy" in p or "pageerror" in p], problems
