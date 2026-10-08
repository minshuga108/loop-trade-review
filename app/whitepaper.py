"""/whitepaper: WHITEPAPER.md (rendered from its template by scripts/render_docs.py) as a readable, mobile-safe HTML page.

The markdown is converted on the server by a small converter that covers exactly what the document uses (headings,
paragraphs, lists, tables, fenced code, bold, italic, inline code, links). English only. No script is served.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = "WHITEPAPER.md"
_cache: dict = {"mt": None, "html": None}

CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--code:#f3f4f6;--link:#0b5cad}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--fg:#e6e8eb;--muted:#9aa4af;--line:#2d333b;--code:#1a2028;--link:#6cb2ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:46rem;margin:0 auto;padding:20px 16px 64px}
nav{font-size:14px;color:var(--muted);margin-bottom:12px}
a{color:var(--link)}
h1{font-size:1.9rem;line-height:1.25;margin:.4em 0 .6em}
h2{font-size:1.4rem;margin:2em 0 .5em;padding-top:.4em;border-top:1px solid var(--line)}
h3{font-size:1.12rem;margin:1.6em 0 .4em}
p,li{overflow-wrap:anywhere}
li{margin:.3em 0}
code{background:var(--code);padding:.1em .35em;border-radius:4px;font:.88em ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
pre{background:var(--code);padding:12px 14px;border-radius:6px;overflow-x:auto;font-size:.82rem;line-height:1.5}
pre code{background:none;padding:0;overflow-wrap:normal}
.tbl{overflow-x:auto;margin:1em 0;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;font-size:.85rem;min-width:100%}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--code)}
footer{margin-top:3em;color:var(--muted);font-size:14px;border-top:1px solid var(--line);padding-top:12px}
"""


def _inline(s: str) -> str:
    out, pos = [], 0
    for m in re.finditer(r"`([^`]+)`", s):
        out.append(_inline_plain(s[pos:m.start()]))
        out.append(f"<code>{html.escape(m.group(1))}</code>")
        pos = m.end()
    out.append(_inline_plain(s[pos:]))
    return "".join(out)


def _inline_plain(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]*)\)", lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', s)
    s = re.sub(r"(?<![\"'=>])(https?://[^\s<)]+[^\s<).,;:])", r'<a href="\1">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", s)
    return s


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        if line.startswith("```"):
            flush()
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            continue
        m = re.match(r"(#{1,3}) (.*)", line)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if line.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush()
            head = _cells(line)
            i += 2
            rows = []
            while i < n and lines[i].startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            t = "<div class=\"tbl\"><table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
            for r in rows:
                t += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
            out.append(t + "</tbody></table></div>")
            continue
        if re.match(r"^- ", line):
            flush()
            items = []
            while i < n and re.match(r"^- ", lines[i]):
                cur = [lines[i][2:]]
                i += 1
                while i < n and lines[i].startswith("  ") and lines[i].strip():
                    cur.append(lines[i].strip())
                    i += 1
                items.append(" ".join(cur))
            out.append("<ul>" + "".join(f"<li>{_inline(t)}</li>" for t in items) + "</ul>")
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


def title_of(md: str) -> str:
    m = re.search(r"^# (.+)$", md, re.M)
    return m.group(1).strip() if m else "Loop whitepaper"


def page_html(md: str) -> str:
    title = title_of(md)
    body = markdown_to_html(md)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>Whitepaper: {html.escape(title)}</title><style>{CSS}</style></head><body><div class=\"wrap\">"
            "<nav><a href=\"/\">Back to the review</a> &middot; <a href=\"/validation\">Validation</a> &middot; "
            "<a href=\"/wrong\">What we got wrong</a></nav>"
            f"{body}<footer>Read-only. No login, no key, no order path. This page is rendered from "
            "<code>WHITEPAPER.md</code>, whose numbers are filled in from the repository's results files.</footer>"
            "</div></body></html>")


def render() -> str:
    p = ROOT / DOC
    if not p.exists():
        return page_html("# Whitepaper\n\nWHITEPAPER.md is not in this build.")
    mt = p.stat().st_mtime
    if _cache["mt"] != mt:
        _cache.update(mt=mt, html=page_html(p.read_text(encoding="utf-8")))
    return _cache["html"]


def router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse
    r = APIRouter()

    @r.get("/whitepaper", include_in_schema=False)
    def whitepaper():
        return HTMLResponse(render())
    return r
