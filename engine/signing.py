"""HMAC-SHA256 signature for exported reports (R12 stretch). A signature, not zero-knowledge.

The server holds a secret in env LOOP_SIGNING_KEY; if it is unset, exports are not signed and
verification answers "unsigned"/"key unavailable" honestly. What it proves: the file was produced
by a server holding that key and has not been changed since. What it does not prove: that the
numbers are right (they are computed from fills and number-locked separately), or anything to a
party that does not trust this server (an HMAC needs the same secret to verify).

Format: the signed body, a newline, then one final line
    <!-- loop-signature v1 hmac-sha256 key:<key id> sig:<64 hex> -->
key id = first 12 hex of SHA-256(key), so a key rotation is visible without revealing the key.
Line endings are normalised to "\\n" before signing and verifying.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

MARK = "\n<!-- loop-signature v1 "
LINE_RE = re.compile(r"^<!-- loop-signature v1 hmac-sha256 key:([0-9a-f]{12}) sig:([0-9a-f]{64}) -->\s*$")


def _key(key: str | None = None) -> bytes | None:
    k = key if key is not None else os.environ.get("LOOP_SIGNING_KEY", "")
    return k.encode() if k else None


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:12]


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sign(text: str, key: str | None = None) -> tuple[str, dict]:
    """Return (text with signature line, info). Without a key the text is returned unsigned."""
    k = _key(key)
    body = _norm(text).rstrip("\n")
    if k is None:
        return body + "\n", {"signed": False, "reason": "LOOP_SIGNING_KEY is not set on this server, so this export is unsigned"}
    sig = hmac.new(k, body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}\n<!-- loop-signature v1 hmac-sha256 key:{key_id(k)} sig:{sig} -->\n", {"signed": True, "key_id": key_id(k), "sig": sig}


def verify(text: str, key: str | None = None) -> dict:
    t = _norm(text).rstrip("\n")
    pos = t.rfind(MARK)
    if pos < 0:
        return {"status": "UNSIGNED", "detail": "no Loop signature line found: this file is unverified"}
    body, line = t[:pos], t[pos + 1:]
    m = LINE_RE.match(line)
    if not m:
        return {"status": "ALTERED", "detail": "the signature line is malformed or has text after it"}
    k = _key(key)
    if k is None:
        return {"status": "KEY_UNAVAILABLE", "detail": "this server has no signing key, so it cannot check the signature"}
    if m.group(1) != key_id(k):
        return {"status": "OTHER_KEY", "detail": f"signed with key {m.group(1)}, this server holds key {key_id(k)}"}
    good = hmac.compare_digest(hmac.new(k, body.encode("utf-8"), hashlib.sha256).hexdigest(), m.group(2))
    return {"status": "VERIFIED" if good else "ALTERED", "key_id": m.group(1),
            "detail": "signature matches: unchanged since export" if good else "signature does not match: altered after export"}
