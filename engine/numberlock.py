"""Number-lock: every numeral in a sentence must come from the facts payload.

Engines freeze a facts dict first; text (template or LLM) may only contain
numbers that match a fact at the precision shown. A sentence with an unknown
number is refused and replaced by the plain template.
"""
from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?")
# a magnitude glued to the numeral changes its value: "7k" is 7000 and "1e5" is 100000, so they are
# checked at their real size (otherwise the 0..10 allow-list would let "7k" or "3e6" through)
SCALE = re.compile(r"(?:[eE]([-+]?\d{1,3})(?![\w.])|([kKmMbB])(?![A-Za-z])|(千|万|亿))")
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "千": 1e3, "万": 1e4, "亿": 1e8}


class NumberLockError(ValueError):
    pass


def numerals(text: str) -> list[tuple[str, float, int]]:
    """(raw, value, decimals shown) for each number token."""
    out = []
    for m in NUM.finditer(text):
        raw = m.group(0)
        clean = raw.replace("$", "").replace(",", "").replace("+", "")
        try:
            val = float(clean)
        except ValueError:
            continue
        dec = len(clean.split(".")[1]) if "." in clean else 0
        s = SCALE.match(text, m.end())
        if s:
            if s.group(1):
                e = int(s.group(1))
                mult = 10.0 ** e if e <= 308 else float("inf")      # an absurd exponent can never be backed
            else:
                mult = _MULT[(s.group(2) or s.group(3)).lower()]
            raw, val, dec = raw + s.group(0), val * mult, 0
        out.append((raw, val, dec))
    return out


def verify(text: str, facts: list[float], allow: tuple[float, ...] = ()) -> None:
    """Raise NumberLockError if any numeral in `text` matches no fact at its displayed precision."""
    bad = []
    for raw, val, dec in numerals(text):
        if val in allow:
            continue
        tol = 0.5 * 10 ** (-dec) + 1e-9
        if not any(abs(abs(f) - abs(val)) <= tol or abs(f - val) <= tol for f in facts):
            bad.append(raw)
    if bad:
        raise NumberLockError(f"numbers not backed by a computed fact: {bad}")
