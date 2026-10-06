"""Self-contained printable HTML for the weekly review (R12). Same sections as the Markdown.

No external requests: inline CSS, system fonts, no scripts, no images. Light theme only, because
it is meant to be printed or saved as PDF from the browser.
"""
from __future__ import annotations

import html
import re


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(^|\s)_(.+?)_(?=\s|$)", r"\1<em>\2</em>", s)
    return s


def md_to_html(md: str) -> str:
    """The small Markdown subset report.build writes: #/## headings, -/  - lists, **bold**, _italic_."""
    out: list[str] = []
    depth = 0
    for raw in md.split("\n"):
        m = re.match(r"^( *)- (.*)$", raw)
        if m:
            want = 1 + len(m.group(1)) // 2
            while depth < want:
                out.append("<ul>")
                depth += 1
            while depth > want:
                out.append("</ul>")
                depth -= 1
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue
        while depth:
            out.append("</ul>")
            depth -= 1
        h = re.match(r"^(#{1,3}) (.*)$", raw)
        if h:
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{_inline(h.group(2))}</h{lvl}>")
        elif raw.strip():
            out.append(f"<p>{_inline(raw)}</p>")
    while depth:
        out.append("</ul>")
        depth -= 1
    return "\n".join(out)


CSS = """
:root{color-scheme:light}
body{margin:0;background:#fbfaf6;color:#15212b;font:15px/1.55 Georgia,"Times New Roman",serif}
main{max-width:760px;margin:0 auto;padding:32px 20px 48px}
h1{font-size:26px;line-height:1.2;margin:0 0 6px}
h2{font:600 13px/1.3 "Segoe UI",system-ui,sans-serif;text-transform:uppercase;letter-spacing:.04em;color:#5d6b76;
   border-top:1px solid #d9d5ca;padding-top:14px;margin:22px 0 6px}
p,li{margin:4px 0} ul{margin:4px 0 4px 20px;padding:0}
em{color:#5d6b76}
.meta{font:12.5px/1.5 "Segoe UI",system-ui,sans-serif;color:#5d6b76;border-top:1px solid #d9d5ca;margin-top:28px;padding-top:10px}
@media print{body{background:#fff} main{padding:0} h2{break-after:avoid} li{break-inside:avoid}}
"""


def render(md: str, title: str, meta_lines: list[str]) -> str:
    meta = "".join(f"<div>{html.escape(x)}</div>" for x in meta_lines)
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>\n<body><main>\n{md_to_html(md)}\n"
            f"<div class=\"meta\">{meta}</div>\n</main></body></html>")
