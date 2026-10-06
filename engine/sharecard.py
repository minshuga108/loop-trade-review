"""Share card (M23): a 1200x630 SVG built only from a computed review payload.

Editorial look: off-white paper with an SVG grain filter, ink type, one yellow-green accent.
Every number on it is copied from the review dict (the same one the page shows); the provenance
label is always printed so a quoted card cannot pass a public wallet or a simulated trader off as
someone's real account. No external fonts or images: the file renders offline.
"""
from __future__ import annotations

import textwrap
from xml.sax.saxutils import escape

W, H = 1200, 630
PAPER, INK, MUTED, ACCENT = "#f4f1e8", "#16191d", "#5b5f63", "#b9d531"
DET = {"size_after_loss": "Opening size after a loss", "hold_asymmetry": "Holding losers longer than winners",
       "overtrading_clusters": "Trading more on the busiest days", "revenge_reentry": "Re-entering soon after a loss"}


def _usd(x: float) -> str:
    return ("-$" if x < 0 else "+$") + f"{abs(round(x)):,.0f}"


def facts(review: dict) -> dict:
    hl, tr = review["headline"], review["trader"]
    f = hl["finding"]
    if f:
        finding = (f"{DET.get(f['detector'], f['detector'])}: {f['ratio']:.2f}x "
                   f"(95% range {f['ci'][0]:.2f} to {f['ci'][1]:.2f}, p={f['p']:.3f})")
    else:
        finding = "No habit passed the test for this trader. That is a result, not a gap."
    p = hl["priced"]
    priced = (f"{p['rule'].capitalize()}: {_usd(p['all_history_effect'])} over the whole history, "
              f"{_usd(p['held_out_effect'])} on trades the rule never saw")
    c = hl["court"]
    verdict = (f"Rule court: {c['proposed']} proposed, {c['tested']} tested, {c['accepted']} accepted on unseen trades. "
               f"This rule: {p['status'].lower()}.")
    return {"wallet": tr["id"], "finding": finding, "priced": priced, "verdict": verdict,
            "provenance": tr["provenance"], "label": tr["label"]}


def _lines(x: float, y: float, text: str, width: int, size: int, color: str, weight: str = "400",
           family: str = "Georgia, 'Times New Roman', serif", lh: float = 1.22) -> tuple[str, float]:
    out = []
    for i, ln in enumerate(textwrap.wrap(text, width)):
        out.append(f'<text x="{x}" y="{y + i * size * lh:.0f}" font-family="{family}" font-size="{size}" '
                   f'font-weight="{weight}" fill="{color}">{escape(ln)}</text>')
    return "".join(out), y + len(out) * size * lh


def svg(review: dict, url: str | None = None) -> str:
    f = facts(review)
    sans = "'Segoe UI', Helvetica, Arial, sans-serif"
    head, _ = _lines(64, 92, f"LOOP  ·  TRADE REVIEW  ·  WALLET {f['wallet']}", 80, 20, MUTED, "600", sans)
    for fs in (46, 40, 34, 28):                   # shrink the headline until nothing runs into the provenance band
        fin, y = _lines(64, 178, f["finding"], int(2116 / fs), fs, INK, "600")
        pri, y2 = _lines(96, y + 34, f["priced"], 70, 26, INK)
        ver, y3 = _lines(64, y2 + 30, f["verdict"], 92, 22, MUTED, "400", sans)
        if y3 <= 520:
            break
    prov, _ = _lines(64, 556, f"{f['provenance']}  ·  {f['label']}", 112, 17, MUTED, "400", sans)
    foot = escape("Every number computed from fills by the review engine; none typed by hand." + (f"  {url}" if url else ""))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(f['finding'], {'"': '&quot;'})}">
<title>{escape(f['finding'])}</title>
<defs><filter id="grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="7" stitchTiles="stitch"/>
<feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" tableValues="0 0.10"/></feComponentTransfer></filter></defs>
<rect width="{W}" height="{H}" fill="{PAPER}"/><rect width="{W}" height="{H}" filter="url(#grain)"/>
<rect x="0" y="0" width="{W}" height="14" fill="{ACCENT}"/>
<line x1="64" y1="112" x2="{W - 64}" y2="112" stroke="{INK}" stroke-width="1.5"/>
{head}{fin}
<rect x="64" y="{y + 6:.0f}" width="10" height="{max(y2 - y - 12, 24):.0f}" fill="{ACCENT}"/>
{pri}{ver}
<line x1="64" y1="526" x2="{W - 64}" y2="526" stroke="{INK}" stroke-width="1"/>
{prov}<text x="64" y="606" font-family="{sans}" font-size="15" fill="{MUTED}">{foot}</text>
</svg>"""
