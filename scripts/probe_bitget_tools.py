"""Probe every Bitget AI tool path that can be reached WITHOUT credentials and save what answered.

Writes evidence/bitget_tools_<UTC timestamp>.json and appends one row per call to the
Bitget call log (engine/bitget_context.CALL_LOG, origin "probe").

Rules kept here: public read-only calls only; no keys, no logins, no orders, no paper
orders, no dry-run orders. One request at a time with a pause between calls.

    python scripts/probe_bitget_tools.py [--no-bgc] [--ta-src <dir with kline_indicator_utils.py>]

Paths probed:
  (a) bgc, the official CLI (npx -y @bitget-ai/bitget-agent-cli@3.0.0 --read-only market ...)
  (b) bitget-mcp-server, https://agent.bitget.com/mcp (JSON-RPC over streamable HTTP)
  (c) bitget-signal's five research skills: four call the MCP host the package installs
      (https://datahub.noxiaohao.com/mcp); technical-analysis runs locally on Bitget public candles
  (d) Agent Hub: `bgc --full discover` per domain, counting [PUBLIC] vs [PRIVATE] operations,
      plus one private read with no key to record what it says
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import bitget_context as bc  # noqa: E402

EVIDENCE = ROOT / "evidence"
PAUSE_S = 0.6
SAMPLE_CHARS = 600
BGC_PKG = "@bitget-ai/bitget-agent-cli@3.0.0"
MCP_URL = "https://agent.bitget.com/mcp"
SIGNAL_URL = "https://datahub.noxiaohao.com/mcp"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def trim(x, n: int = SAMPLE_CHARS) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f"... [{len(s) - n} more chars]"


def record(rows: list, *, path: str, tool: str, operation: str, request: dict, status, latency_ms: int,
           sample, verdict: str, note: str = "") -> dict:
    row = {"path": path, "tool": tool, "operation": operation, "request": request, "status": status,
           "latency_ms": latency_ms, "sample": trim(sample), "verdict": verdict, "note": note, "at": now_iso()}
    rows.append(row)
    bc.log_call(source=path, operation=f"{tool}:{operation}", ok=(verdict == "answers"), status=str(status),
                latency_ms=latency_ms, origin="probe")
    print(f"[{verdict:>9}] {path:<14} {tool}:{operation} status={status} {latency_ms} ms", flush=True)
    time.sleep(PAUSE_S)
    return row


# --------------------------------------------------------------------------- (a) bgc


def bgc(rows: list, args: list[str], operation: str, *, expect_data: bool = True) -> dict | None:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    cmd = [npx or "npx", "-y", BGC_PKG, *args]
    shown = "npx -y " + BGC_PKG + " " + " ".join(args)
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90, encoding="utf-8",
                           env={**__import__("os").environ, "BITGET_API_KEY": "", "BITGET_SECRET_KEY": "", "BITGET_PASSPHRASE": ""})
    except Exception as e:  # npx missing, timeout
        record(rows, path="bgc", tool="bgc", operation=operation, request={"argv": shown}, status="spawn-failed",
               latency_ms=int((time.perf_counter() - t0) * 1000), sample=repr(e), verdict="error")
        return None
    ms = int((time.perf_counter() - t0) * 1000)
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    body = None
    try:
        body = json.loads(p.stdout)
    except Exception:
        pass
    endpoint = body.get("endpoint") if isinstance(body, dict) else None
    data = body.get("data") if isinstance(body, dict) else None
    low = out.lower()
    if "requires api credentials" in low or (p.returncode != 0 and any(k in low for k in ("credential", "passphrase"))):
        verdict = "needs key"
    elif p.returncode == 0 and data not in (None, [], {}):
        verdict = "answers"
    elif p.returncode == 0:
        verdict = "empty"
    else:
        verdict = "error"
    record(rows, path="bgc", tool="bgc", operation=operation,
           request={"argv": shown, "endpoint": endpoint}, status=f"exit {p.returncode}", latency_ms=ms,
           sample=out, verdict=verdict, note="latency includes npx start-up (package cached after first run)")
    return body


# --------------------------------------------------------------------------- (b)/(c) MCP over HTTP


class Mcp:
    def __init__(self, url: str, client: httpx.Client):
        self.url, self.c, self.sid, self.n = url, client, None, 0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        return h

    def rpc(self, method: str, params: dict | None = None, notify: bool = False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        t0 = time.perf_counter()
        r = self.c.post(self.url, json=msg, headers=self._headers())
        ms = int((time.perf_counter() - t0) * 1000)
        if r.headers.get("mcp-session-id"):
            self.sid = r.headers["mcp-session-id"]
        return msg, r.status_code, ms, bc.parse_mcp_body(r.text)


def mcp_tool_verdict(status: int, body) -> tuple[str, str]:
    return bc.classify_tool_result(status, body)


def probe_mcp(rows: list, client: httpx.Client, url: str, path: str, calls: list[tuple[str, dict, str]]) -> dict:
    m = Mcp(url, client)
    out = {"tools": []}
    try:
        msg, st, ms, body = m.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                                 "clientInfo": {"name": "loop-evidence-probe", "version": "1"}})
    except Exception as e:
        record(rows, path=path, tool="mcp", operation="initialize", request={"url": url, "body": {"method": "initialize"}},
               status="no-connection", latency_ms=0, sample=repr(e), verdict="error")
        return out
    info = (body or {}).get("result", {}).get("serverInfo") if isinstance(body, dict) else None
    record(rows, path=path, tool="mcp", operation="initialize", request={"url": url, "body": msg}, status=st, latency_ms=ms,
           sample=body, verdict="answers" if st == 200 and info else "error")
    out["serverInfo"] = info
    try:
        m.rpc("notifications/initialized", notify=True)
    except Exception:
        pass
    msg, st, ms, body = m.rpc("tools/list", {})
    tools = ((body or {}).get("result") or {}).get("tools", []) if isinstance(body, dict) else []
    out["tools"] = [t.get("name") for t in tools]
    record(rows, path=path, tool="mcp", operation="tools/list", request={"url": url, "body": msg}, status=st, latency_ms=ms,
           sample={"tool_names": out["tools"]}, verdict="answers" if tools else "error")
    for name, args, label in calls:
        try:
            msg, st, ms, body = m.rpc("tools/call", {"name": name, "arguments": args})
        except Exception as e:
            record(rows, path=path, tool=name, operation=label, request={"url": url, "tool": name, "arguments": args},
                   status="no-connection", latency_ms=0, sample=repr(e), verdict="error")
            continue
        verdict, note = mcp_tool_verdict(st, body)
        record(rows, path=path, tool=name, operation=label, request={"url": url, "tool": name, "arguments": args},
               status=st, latency_ms=ms, sample=body, verdict=verdict, note=note)
    return out


# --------------------------------------------------------------------------- (c) technical-analysis, local


def probe_ta(rows: list, ta_src: str | None) -> None:
    t0 = time.perf_counter()
    req = {"skill": "technical-analysis (bitget-signal 1.2.0, Template A)",
           "candles": "GET https://api.bitget.com/api/v2/spot/market/candles?symbol=RNVDAUSDT&granularity=1day&limit=100",
           "config": bc.TA_CONFIG}
    try:
        res = bc.run_technical_analysis("RNVDAUSDT", ta_src=ta_src)
        verdict = "answers" if res.get("ok") else "error"
        sample = res
    except Exception as e:
        verdict, sample = "error", repr(e)
    record(rows, path="bitget-signal", tool="technical-analysis", operation="RSI(14) on RNVDAUSDT 1day", request=req,
           status="local", latency_ms=int((time.perf_counter() - t0) * 1000), sample=sample, verdict=verdict,
           note="runs the skill's own MIT Python (kline_indicator_utils) on Bitget public candles; no server involved")


# --------------------------------------------------------------------------- (d) Agent Hub surface


def probe_agent_hub(rows: list) -> dict:
    surface = {}
    for dom in ["market", "trade", "account", "funds", "subaccount", "loan", "tax"]:
        body = bgc(rows, ["--full", "discover", "--domain", dom], f"discover --domain {dom}")
        tools = ((body or {}).get("data") or {}).get("tools", []) if isinstance(body, dict) else []
        pub = [t["name"] for t in tools if str(t.get("description", "")).startswith("[PUBLIC]")]
        surface[dom] = {"operations": len(tools), "public": len(pub), "public_ops": pub,
                        "writes": sum(bool(t.get("isWrite")) for t in tools)}
    return surface


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-bgc", action="store_true")
    ap.add_argument("--ta-src", default=None)
    a = ap.parse_args()
    rows: list = []
    started = now_iso()
    result: dict = {"generated_at": started, "rules": "public read-only calls only; no keys, no logins, no orders, no paper or dry-run orders"}

    # (a) bgc market verb
    if not a.no_bgc:
        ro = ["--read-only"]
        bgc(rows, ro + ["market", "--action", "tickers", "--category", "SPOT", "--symbol", "RNVDAUSDT"], "market tickers RNVDAUSDT")
        bgc(rows, ro + ["market", "--action", "tickers", "--category", "USDT-FUTURES", "--symbol", "NVDAUSDT"], "market tickers NVDAUSDT")
        bgc(rows, ro + ["market", "--action", "orderbook", "--category", "SPOT", "--symbol", "RNVDAUSDT", "--limit", "5"], "market orderbook RNVDAUSDT")
        bgc(rows, ro + ["market", "--action", "candles", "--category", "USDT-FUTURES", "--symbol", "NVDAUSDT", "--interval", "1D", "--limit", "5"], "market candles NVDAUSDT 1D")
        bgc(rows, ro + ["market", "--action", "fundingRate", "--symbol", "NVDAUSDT"], "market fundingRate NVDAUSDT")
        bgc(rows, ro + ["market", "--action", "fundingRateHistory", "--category", "USDT-FUTURES", "--symbol", "NVDAUSDT", "--limit", "5"], "market fundingRateHistory NVDAUSDT")
        # one private READ with no key, to record exactly what a keyless caller gets
        bgc(rows, ro + ["account_overview", "--coin", "USDT"], "account_overview (private read, no key)")
        result["agent_hub_surface"] = probe_agent_hub(rows)

    with httpx.Client(timeout=20.0, headers={"User-Agent": "loop-evidence-probe/1 (read-only)"}) as c:
        # (b) bitget-mcp-server
        result["mcp"] = probe_mcp(rows, c, MCP_URL, "bitget-mcp", [
            ("guide", {"category": "equity"}, "guide equity"),
            ("do_query", {"entry_id": "equity_price_quote", "params": {"symbol": "NVDA"}}, "equity_price_quote NVDA"),
            ("do_query", {"entry_id": "equity_calendar", "params": {"symbol": "NVDA"}}, "equity_calendar NVDA"),
            ("do_query", {"entry_id": "equity_fundamental_metrics", "params": {"symbol": "NVDA"}}, "equity_fundamental_metrics NVDA"),
            ("do_query", {"entry_id": "sentiment_market_fear_greed", "params": {}}, "sentiment_market_fear_greed"),
        ])
        # plain GET on the MCP URL and the REST mirror
        for label, url in [("plain GET /mcp", MCP_URL), ("REST mirror equity quote", "https://agent.bitget.com/api/v1/equity/price/quote?symbol=NVDA")]:
            t0 = time.perf_counter()
            try:
                r = c.get(url)
                st, txt = r.status_code, r.text
            except Exception as e:
                st, txt = "no-connection", repr(e)
            record(rows, path="bitget-mcp", tool="http", operation=label, request={"method": "GET", "url": url}, status=st,
                   latency_ms=int((time.perf_counter() - t0) * 1000), sample=txt,
                   verdict="answers" if st == 200 and "503" not in txt[:300] else "error")
        # (c) bitget-signal: the four server-backed skills, each with the first call its SKILL.md makes
        result["bitget_signal"] = probe_mcp(rows, c, SIGNAL_URL, "bitget-signal", [
            ("sentiment_index", {"action": "current"}, "sentiment-analyst: sentiment_index current"),
            ("derivatives_sentiment", {"action": "long_short", "symbol": "BTCUSDT", "period": "4h"}, "sentiment-analyst: long_short BTCUSDT 4h"),
            ("news_feed", {"action": "latest", "feeds": "cointelegraph,coindesk,decrypt,blockworks", "limit": 5}, "news-briefing: news_feed latest"),
            ("tradfi_news", {"action": "news", "limit": 5}, "news-briefing: tradfi_news news"),
            ("rates_yields", {"action": "rates_snapshot"}, "macro-analyst: rates_yields rates_snapshot"),
            ("macro_indicators", {"action": "latest_release", "indicator": "cpi"}, "macro-analyst: macro_indicators cpi"),
            ("crypto_market", {"action": "global"}, "market-intel: crypto_market global"),
            ("defi_analytics", {"action": "stablecoins"}, "market-intel: defi_analytics stablecoins"),
        ])
    probe_ta(rows, a.ta_src)

    result["calls"] = rows
    summary: dict = {}
    for r in rows:
        s = summary.setdefault(r["path"], {"calls": 0, "answers": 0, "verdicts": {}})
        s["calls"] += 1
        s["answers"] += r["verdict"] == "answers"
        s["verdicts"][r["verdict"]] = s["verdicts"].get(r["verdict"], 0) + 1
    result["summary"] = summary
    result["finished_at"] = now_iso()
    EVIDENCE.mkdir(exist_ok=True)
    out = EVIDENCE / f"bitget_tools_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", out.relative_to(ROOT))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
