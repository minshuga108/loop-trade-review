"""In-memory rate limiting and request-size guard (pure ASGI middleware, one process).

Token buckets, generous enough that a person clicking around never meets them, tight enough
that one client cannot keep the court (seconds of CPU per call) busy for everyone:

- per IP:          burst 400, refill 20 per second   (all routes)
- per session:     burst 200, refill 10per second    (X-Session or Mcp-Session-Id, when sent)
- heavy, per IP:   burst 60, refill 1 per second      (routes that run the court or a permutation test)

Over the limit the answer is 429 with Retry-After (whole seconds until a token is back).
/api/health is never limited (host health checks must not fail under load).

The IP is the ASGI client address. Behind a proxy, uvicorn's --proxy-headers puts the real
client there (the Dockerfile sets it); with --forwarded-allow-ips='*' a client can spoof
X-Forwarded-For, so the per-IP bucket is a speed bump, not a wall. Per-process memory only:
several workers or replicas would each keep their own buckets.

Also here: request bodies above MAX_BODY bytes (4 MB for /api/import only) get 413 (checked on Content-Length and while
streaming), and an X-Session header that is not 1..128 visible ASCII characters gets 400.
Set LOOP_RATELIMIT=off to disable the buckets (tests and the load script use it explicitly).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import OrderedDict

MAX_BODY = 64 * 1024
MAX_BODY_BY_PATH = {"/api/import": 4 * 1024 * 1024}   # the UI promises 2 MB / 30,000 rows (importer.py enforces both); 4 MB leaves room for JSON escaping


def body_limit(path: str) -> int:
    return MAX_BODY_BY_PATH.get(path, MAX_BODY)
MAX_KEYS = 20_000
EXEMPT = ("/api/health",)
SESSION_RE = re.compile(r"^[\x21-\x7e]{1,128}$")
HEAVY_PREFIXES = ("/api/rulebook/",)          # GET runs the checklist permutation test; POST propose runs the court
HEAVY_EXACT = ("/api/selftest/run",)

LIMITS = {"ip": (400.0, 20.0), "session": (200.0, 10.0), "heavy": (60.0, 1.0)}   # (burst, refill per second)


def enabled() -> bool:
    return os.environ.get("LOOP_RATELIMIT", "on").lower() not in ("off", "0", "false", "no")


class Buckets:
    """Token buckets keyed by string, LRU-bounded so a flood of keys cannot grow memory without end."""

    def __init__(self, burst: float, rate: float, max_keys: int = MAX_KEYS, clock=time.monotonic):
        self.burst, self.rate, self.max_keys, self.clock = burst, rate, max_keys, clock
        self._b: "OrderedDict[str, tuple[float, float]]" = OrderedDict()
        self._lock = threading.Lock()

    def take(self, key: str, cost: float = 1.0) -> float:
        """Spend `cost` tokens. Returns 0.0 when allowed, else the seconds until it would be."""
        now = self.clock()
        with self._lock:
            tokens, last = self._b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._b[key] = (tokens - cost, now)
                wait = 0.0
            else:
                self._b[key] = (tokens, now)
                wait = (cost - tokens) / self.rate
            self._b.move_to_end(key)
            while len(self._b) > self.max_keys:
                self._b.popitem(last=False)
            return wait

    def reset(self) -> None:
        with self._lock:
            self._b.clear()


BUCKETS = {k: Buckets(*v) for k, v in LIMITS.items()}


def reset() -> None:
    for b in BUCKETS.values():
        b.reset()


def is_heavy(method: str, path: str, query: bytes) -> bool:
    if path in HEAVY_EXACT or path.startswith(HEAVY_PREFIXES):
        return True
    if path.startswith("/api/toggle/") and b"rule=cap" in query:
        return True
    return False


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return None


async def _send_json(send, status: int, body: dict, extra: list[tuple[bytes, bytes]] = ()) -> None:
    raw = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), *extra]})
    await send({"type": "http.response.body", "body": raw})


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in EXEMPT:
            return await self.app(scope, receive, send)

        sid = _header(scope, b"x-session")
        if sid is not None and not SESSION_RE.match(sid):
            return await _send_json(send, 400, {"detail": "X-Session must be 1 to 128 visible ASCII characters"})

        limit = body_limit(path)
        cl = _header(scope, b"content-length")
        if cl is not None:
            try:
                too_big = int(cl) > limit
            except ValueError:
                return await _send_json(send, 400, {"detail": "bad Content-Length"})
            if too_big:
                return await _send_json(send, 413, {"detail": f"request body larger than {limit} bytes"})

        if enabled():
            ip = (scope.get("client") or ("unknown", 0))[0] or "unknown"
            waits = [BUCKETS["ip"].take(ip)]
            sess = sid or _header(scope, b"mcp-session-id")
            if sess:
                waits.append(BUCKETS["session"].take(sess[:128]))
            if is_heavy(scope.get("method", "GET"), path, scope.get("query_string", b"")):
                waits.append(BUCKETS["heavy"].take(ip))
            wait = max(waits)
            if wait > 0:
                retry = str(max(1, math.ceil(wait))).encode()
                return await _send_json(send, 429, {"detail": "Too many requests. Please slow down and retry shortly."},
                                        [(b"retry-after", retry)])

        if cl is None and scope.get("method") in ("POST", "PUT", "PATCH", "DELETE"):
            # no Content-Length (chunked): read up to the cap here, then replay it to the app
            chunks, seen = [], 0
            while True:
                msg = await receive()
                if msg["type"] != "http.request":
                    return                                # client went away
                chunks.append(msg.get("body", b""))
                seen += len(chunks[-1])
                if seen > limit:
                    return await _send_json(send, 413, {"detail": f"request body larger than {limit} bytes"})
                if not msg.get("more_body"):
                    break
            body, replayed = b"".join(chunks), False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        await self.app(scope, receive, send)
