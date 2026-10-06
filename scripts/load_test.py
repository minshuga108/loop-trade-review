"""Load test: N concurrent users doing the main flow against a freshly started local uvicorn.

    python scripts/load_test.py                 # 50 users, 2 rounds each, rate limits ON
    python scripts/load_test.py --users 50 --rounds 3 --cold --json out.json

Standard library only (threads + http.client). The server is started here with the venv's
python (`sys.executable -m uvicorn app.main:app`) on an unused port, LOOP_NO_REFRESH=1 (no
calls to Bitget) and a throwaway record file, and stopped at the end.

Each user has its own X-Session and its own X-Forwarded-For address (uvicorn trusts that
header from 127.0.0.1 by default), so the per-IP and per-session rate limits act as they would
for 50 different people. One round of the flow:

    GET /  GET /static/rulebook.js  GET /static/i18n.js  GET /api/traders
    GET /api/review/T  GET /api/toggle/T?rule=halt  GET /api/rulebook/T
    POST /api/chat (habit)  GET /api/toggle/T?rule=cap  POST /api/gate/T  POST /api/chat (order idea)

Without --cold the script first waits until every trader's review is cached (the server warms
them in the background at start), so the numbers are steady state; --cold starts at once.
Prints p50 / p95 / max latency and error counts per endpoint and overall.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADERS = ["A", "B", "C", "D", "E", "F"]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_server(port: int, extra_env: dict | None = None) -> subprocess.Popen:
    env = dict(os.environ, LOOP_NO_REFRESH="1", PYTHONUNBUFFERED="1",
               LOOP_RECORD_PATH=str(Path(tempfile.mkdtemp(prefix="loop-load-")) / "record.jsonl"))
    env.update(extra_env or {})
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
                             "--workers", "1", "--log-level", "warning"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def request(port: int, method: str, path: str, body: dict | None = None, headers: dict | None = None, timeout: float = 120.0):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        raw = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json"} if raw is not None else {}
        h.update(headers or {})
        t0 = time.perf_counter()
        conn.request(method, path, body=raw, headers=h)
        r = conn.getresponse()
        data = r.read()
        return r.status, (time.perf_counter() - t0) * 1000, data
    finally:
        conn.close()


def wait_ready(port: int, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if request(port, "GET", "/api/health", timeout=2)[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not start")


def wait_warm(port: int, timeout: float = 300) -> float:
    t0 = time.time()
    for t in TRADERS:
        while time.time() - t0 < timeout:
            st, ms, _ = request(port, "GET", f"/api/review/{t}", headers={"X-Forwarded-For": "10.250.0.1"})
            if st == 200:
                break
            time.sleep(0.5)
    return time.time() - t0


def flow(tid: str) -> list[tuple[str, str, str, dict | None]]:
    return [("page /", "GET", "/", None), ("static rulebook.js", "GET", "/static/rulebook.js", None),
            ("static i18n.js", "GET", "/static/i18n.js", None), ("traders", "GET", "/api/traders", None),
            ("review", "GET", f"/api/review/{tid}", None), ("toggle halt", "GET", f"/api/toggle/{tid}?rule=halt", None),
            ("rulebook view", "GET", f"/api/rulebook/{tid}", None),
            ("chat habit", "POST", "/api/chat", {"trader": tid, "message": "What is my biggest costly habit?", "history": []}),
            ("toggle cap (court)", "GET", f"/api/toggle/{tid}?rule=cap", None),
            ("gate", "POST", f"/api/gate/{tid}", {"text": "Buy $20k rNVDA"}),
            ("chat order idea", "POST", "/api/chat", {"trader": tid, "message": "Buy $20k rNVDA, does it break my rules?", "history": []})]


def run(users: int, rounds: int, port: int, seed: int = 7) -> dict:
    lat: dict[str, list[float]] = defaultdict(list)
    status: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    lock = threading.Lock()
    rng = random.Random(seed)
    plan = [(u, rng.choice(TRADERS)) for u in range(users)]
    barrier = threading.Barrier(users)

    def user(u: int, tid: str):
        hdr = {"X-Session": f"load-{u}", "X-Forwarded-For": f"10.{u // 250}.{u % 250}.9"}
        barrier.wait()
        for _ in range(rounds):
            for name, m, path, body in flow(tid):
                try:
                    st, ms, _ = request(port, m, path, body, hdr)
                except Exception:
                    st, ms = -1, float("nan")
                with lock:
                    status[name][st] += 1
                    if st == 200:
                        lat[name].append(ms)

    t0 = time.perf_counter()
    ts = [threading.Thread(target=user, args=p) for p in plan]
    [t.start() for t in ts]
    [t.join() for t in ts]
    wall = time.perf_counter() - t0

    def pct(xs, q):
        if not xs:
            return None
        s = sorted(xs)
        return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)

    rows = {}
    for name, _, _, _ in flow("A"):
        xs = lat[name]
        st = dict(status[name])
        rows[name] = {"n": sum(st.values()), "ok": st.get(200, 0), "errors": sum(v for k, v in st.items() if k != 200),
                      "status": {str(k): v for k, v in sorted(st.items())}, "p50_ms": pct(xs, .5), "p95_ms": pct(xs, .95),
                      "max_ms": round(max(xs), 1) if xs else None, "mean_ms": round(statistics.fmean(xs), 1) if xs else None}
    allx = [x for v in lat.values() for x in v]
    total = {"requests": sum(r["n"] for r in rows.values()), "errors": sum(r["errors"] for r in rows.values()),
             "p50_ms": pct(allx, .5), "p95_ms": pct(allx, .95), "max_ms": round(max(allx), 1) if allx else None,
             "wall_s": round(wall, 1), "throughput_rps": round(sum(r["n"] for r in rows.values()) / wall, 1)}
    return {"users": users, "rounds": rounds, "endpoints": rows, "total": total}


def print_table(res: dict) -> None:
    print(f"\n{res['users']} users x {res['rounds']} rounds   (warm-up {res.get('warm_s', 0)} s)")
    print(f"{'endpoint':22} {'n':>5} {'err':>5} {'p50 ms':>9} {'p95 ms':>9} {'max ms':>9}  status")
    for name, r in sorted(res["endpoints"].items(), key=lambda kv: -(kv[1]["p95_ms"] or 0)):
        print(f"{name:22} {r['n']:>5} {r['errors']:>5} {r['p50_ms'] or '-':>9} {r['p95_ms'] or '-':>9} {r['max_ms'] or '-':>9}  {r['status']}")
    t = res["total"]
    print(f"{'ALL':22} {t['requests']:>5} {t['errors']:>5} {t['p50_ms']:>9} {t['p95_ms']:>9} {t['max_ms']:>9}  "
          f"wall {t['wall_s']} s, {t['throughput_rps']} req/s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--cold", action="store_true", help="start immediately, before the review cache is warm")
    ap.add_argument("--no-ratelimit", action="store_true")
    ap.add_argument("--json", help="write the result here")
    a = ap.parse_args(argv)
    port = free_port()
    proc = start_server(port, {"LOOP_RATELIMIT": "off"} if a.no_ratelimit else {"LOOP_RATELIMIT": "on"})
    try:
        wait_ready(port)
        warm = 0.0 if a.cold else round(wait_warm(port), 1)
        res = run(a.users, a.rounds, port)
        res["warm_s"], res["cold"], res["ratelimit"] = warm, a.cold, not a.no_ratelimit
        print_table(res)
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
        return 0 if res["total"]["errors"] == 0 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
