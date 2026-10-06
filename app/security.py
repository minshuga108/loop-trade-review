"""Security headers on every response, and HEAD answered like GET without a body (pure ASGI).

Content-Security-Policy: scripts only from this origin plus the exact inline <script> blocks
shipped in app/static/*.html (allowed by their SHA-256, computed at start-up, so an injected
inline script or event-handler attribute does not run). Styles may be inline (the pages use
style attributes); no plugins, no foreign frames, no foreign fetches, <base> locked.

Framing: same origin only (X-Frame-Options SAMEORIGIN + frame-ancestors 'self'). On Hugging
Face Spaces (SPACE_ID is set there) the app is shown inside huggingface.co, so that origin is
added to frame-ancestors and X-Frame-Options is left out (it cannot express an allow-list).
LOOP_FRAME_ANCESTORS overrides the list (space-separated CSP sources).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

STATIC = Path(__file__).parent / "static"
_INLINE = re.compile(rb"<script>(.*?)</script>", re.S)


def inline_script_hashes(static_dir: Path = STATIC) -> list[str]:
    out = []
    for p in sorted(static_dir.glob("*.html")):
        for body in _INLINE.findall(p.read_bytes()):
            body = body.replace(b"\r\n", b"\n").replace(b"\r", b"\n")     # browsers hash the parsed text: newlines are LF
            h = "'sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode() + "'"
            if h not in out:
                out.append(h)
    return out


def frame_ancestors() -> tuple[str, bool]:
    """(CSP frame-ancestors sources, whether X-Frame-Options can be sent)."""
    env = os.environ.get("LOOP_FRAME_ANCESTORS")
    if env:
        return env.strip(), False
    if os.environ.get("SPACE_ID"):
        return "'self' https://huggingface.co https://*.hf.space", False
    return "'self'", True


def build_headers() -> list[tuple[bytes, bytes]]:
    fa, xfo = frame_ancestors()
    csp = "; ".join([
        "default-src 'self'",
        "script-src 'self' " + " ".join(inline_script_hashes()),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        f"frame-ancestors {fa}",
    ])
    hs = [(b"content-security-policy", csp.encode()), (b"x-content-type-options", b"nosniff"),
          (b"referrer-policy", b"strict-origin-when-cross-origin"), (b"cross-origin-opener-policy", b"same-origin"),
          (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()")]
    if xfo:
        hs.append((b"x-frame-options", b"SAMEORIGIN"))
    return hs


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app
        self.headers = build_headers()
        self._names = {k for k, _ in self.headers}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        head = scope.get("method") == "HEAD"
        if head:                                   # uptime pingers often use HEAD; answer it like GET, minus the body
            scope = {**scope, "method": "GET"}

        async def send_wrapper(msg):
            if msg["type"] == "http.response.start":
                kept = [(k, v) for k, v in msg.get("headers", []) if k.lower() not in self._names]
                msg = {**msg, "headers": kept + self.headers}
            elif head and msg["type"] == "http.response.body":
                msg = {**msg, "body": b""}
            await send(msg)

        await self.app(scope, receive, send_wrapper)
