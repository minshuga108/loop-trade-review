"""Bitget skill / MCP context for a review: at most ONE labelled line, "context, not evidence".

Never on the request path. A background refresher (same pattern as app/costs.py) asks the
Bitget AI tools that need no key, caches what answered, and requests only read the cache.
Every outbound call is appended to a JSONL call log, so any count of "Bitget operations
called" is generated from that log, never typed.

Sources, in the order a review line is chosen (the first one with something for that
symbol and trade day wins; only one line is ever attached):

  1. bitget-mcp-server (https://agent.bitget.com/mcp), do_query equity_calendar:
     an earnings date within EARNINGS_WINDOW_D days of the trade day.
  2. bitget-signal technical-analysis skill (its own MIT Python, vendored unmodified in
     engine/vendor/bitget_signal_ta) run on Bitget public daily candles, exactly as the
     skill's Template A does: RSI(14) on the trade day.
  3. Agent Hub `market` verb, operation getFundingRateHistory
     (GET /api/v3/market/history-fund-rate, the call `bgc market --action
     fundingRateHistory` makes): mean funding on the trade day for the stock perp.
  4. bitget-signal sentiment-analyst, sentiment_index(action="current") on the skill's
     MCP host (https://datahub.noxiaohao.com/mcp): only for a trade day within one day
     of the fetch, because it is a "now" reading.

States a caller can see: "ok", "stale" (older than STALE_S), "none for this trade",
"no Bitget skill answered at <time>", "not asked yet". A source that failed is listed
as down with the status it returned. Nothing here places, previews or signs an order.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
CALL_LOG = Path(os.environ.get("LOOP_BITGET_CALL_LOG") or ROOT / "evidence" / "bitget_calls.jsonl")
TA_DIR = Path(__file__).parent / "vendor" / "bitget_signal_ta"

API = "https://api.bitget.com"
MCP_URL = "https://agent.bitget.com/mcp"
SIGNAL_URL = "https://datahub.noxiaohao.com/mcp"

REFRESH_S = 900          # one pass every 15 minutes
STALE_S = 3 * 3600
PAUSE_S = 0.25           # between calls inside one pass
EARNINGS_WINDOW_D = 5
MAX_WATCH = 24
CRYPTO = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "HYPE", "SUI", "LTC", "TRX", "TON"}
DEFAULT_WATCH = ["NVDA", "TSLA", "AAPL", "MSTR", "SPY", "QQQ", "BTC", "ETH"]
TA_CONFIG = {"RSI": {"period": 14}}
LABEL = "context, not evidence"

SOURCE_NAMES = {
    "bitget-mcp": "bitget-mcp-server (agent.bitget.com/mcp)",
    "signal-ta": "bitget-signal technical-analysis skill (local, Bitget public candles)",
    "agenthub-funding": "Agent Hub market verb: getFundingRateHistory",
    "signal-sentiment": "bitget-signal sentiment-analyst (skill MCP host)",
}

# --------------------------------------------------------------------------- call log

_LOG_LOCK = threading.Lock()


def log_call(*, source: str, operation: str, ok: bool, status: str, latency_ms: int, origin: str = "product",
             path: Path | None = None) -> None:
    """Append one row per outbound Bitget-tool call. Failure to write never breaks the caller."""
    p = Path(path or CALL_LOG)
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "origin": origin, "source": source,
           "operation": operation, "ok": bool(ok), "status": str(status), "latency_ms": int(latency_ms)}
    try:
        with _LOG_LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def read_call_log(path: Path | None = None) -> list[dict]:
    p = Path(path or CALL_LOG)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# --------------------------------------------------------------------------- MCP helpers


def parse_mcp_body(text: str) -> Any:
    """JSON-RPC reply sent either as plain JSON or as an SSE stream ("data: {...}" lines)."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except ValueError:
        pass
    last = None
    for line in t.splitlines():
        if line.startswith("data:"):
            try:
                last = json.loads(line[5:].strip())
            except ValueError:
                continue
    return last if last is not None else t[:2000]


def tool_payload(body: Any) -> Any:
    """The tool's own answer inside result.content[0].text, decoded if it is JSON."""
    if not isinstance(body, dict):
        return None
    res = body.get("result") or {}
    content = res.get("content") or []
    if res.get("structuredContent") is not None:
        return res["structuredContent"]
    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    if not texts:
        return None
    t = "\n".join(texts)
    try:
        return json.loads(t)
    except ValueError:
        return t


def classify_tool_result(status: Any, body: Any) -> tuple[str, str]:
    """-> (verdict, note). verdict is one of answers / empty / error / needs key."""
    if status != 200:
        return "error", f"HTTP {status}"
    if not isinstance(body, dict):
        return "error", "reply is not JSON-RPC"
    if body.get("error"):
        return "error", f"JSON-RPC error {str(body['error'])[:160]}"
    res = body.get("result") or {}
    p = tool_payload(body)
    text = p if isinstance(p, str) else json.dumps(p) if p is not None else ""
    low = text.lower()
    if any(k in low for k in ("api key required", "apikey required", "unauthorized", "invalid api key", "missing api key")):
        return "needs key", "tool says a key is needed"
    if isinstance(p, dict):
        sc = p.get("status_code")
        if p.get("success") is False or (isinstance(sc, int) and sc >= 400):
            return "error", f"tool returned success=false, upstream status_code {sc}"
        if "error" in p and (p.get("error") is not None) and len(p) <= 3:
            return "error", f"tool returned error {str(p.get('error'))[:120]!r}"
    if res.get("isError"):
        return "error", "isError true: " + text[:160]
    if isinstance(p, str) and re.match(r"^\s*(error|failed)", low):
        return "error", text[:160]
    if p in (None, "", [], {}):
        return "empty", "tool answered with nothing"
    if isinstance(p, (dict, list)):
        data, errors = _scan(p)
        if not data and errors:
            return "error", f"no data; {errors} error field(s) in the answer (e.g. {{'error': ''}})"
        if not data:
            return "empty", "every list in the answer is empty"
    return "answers", ""


_META_KEYS = {"feed", "url", "source", "symbol", "action", "status", "success", "status_code"}


def _scan(x: Any, key: str = "") -> tuple[int, int]:
    """-> (data leaves, error fields). A non-empty 'error' or '*_error' key, or one set to '', counts as an error;
    meta keys (feed name, url) are not data."""
    data = err = 0
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "error" or k.endswith("_error"):
                err += v is not None
                continue
            d, e = _scan(v, k)
            data, err = data + d, err + e
    elif isinstance(x, list):
        for v in x:
            d, e = _scan(v, key)
            data, err = data + d, err + e
    elif x not in (None, "") and not isinstance(x, bool) and key not in _META_KEYS:
        data = 1                      # a lone boolean (yield_curve_inverted: false next to empty rates) is not data
    return data, err


class McpClient:
    """Minimal streamable-HTTP MCP client: initialize, then tools/call. Logs every POST."""

    def __init__(self, http: httpx.Client, url: str, source: str, origin: str = "product"):
        self.http, self.url, self.source, self.origin = http, url, source, origin
        self.sid: str | None = None
        self.n = 0
        self.server: dict | None = None

    def _post(self, msg: dict, op: str, classify: Callable[[Any, Any], tuple[str, str]] | None = None):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        t0 = time.perf_counter()
        try:
            r = self.http.post(self.url, json=msg, headers=h)
        except Exception as e:
            log_call(source=self.source, operation=op, ok=False, status=type(e).__name__,
                     latency_ms=int((time.perf_counter() - t0) * 1000), origin=self.origin)
            return type(e).__name__, None, "error", repr(e)[:160]
        ms = int((time.perf_counter() - t0) * 1000)
        if r.headers.get("mcp-session-id"):
            self.sid = r.headers["mcp-session-id"]
        body = parse_mcp_body(r.text) if r.text else None
        verdict, note = (classify(r.status_code, body) if classify else
                         (("answers", "") if r.status_code in (200, 202) else ("error", f"HTTP {r.status_code}")))
        log_call(source=self.source, operation=op, ok=verdict == "answers", status=str(r.status_code), latency_ms=ms,
                 origin=self.origin)
        return r.status_code, body, verdict, note

    def initialize(self) -> bool:
        self.n += 1
        st, body, verdict, _ = self._post({"jsonrpc": "2.0", "id": self.n, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "loop", "version": "1"}}}, "initialize")
        info = ((body or {}).get("result") or {}).get("serverInfo") if isinstance(body, dict) else None
        if st != 200 or not info:
            return False
        self.server = info
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, "notifications/initialized")
        return True

    def call(self, name: str, args: dict, op: str | None = None) -> tuple[str, Any, str, Any]:
        """-> (verdict, payload, note, status)."""
        self.n += 1
        st, body, verdict, note = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                                              "params": {"name": name, "arguments": args}},
                                             op or f"tools/call {name}", classify_tool_result)
        return verdict, tool_payload(body), note, st


# --------------------------------------------------------------------------- Bitget REST (public)


def _rest(http: httpx.Client, path: str, params: dict, source: str, op: str, origin: str = "product") -> Any:
    t0 = time.perf_counter()
    try:
        r = http.get(API + path, params=params)
    except Exception as e:
        log_call(source=source, operation=op, ok=False, status=type(e).__name__,
                 latency_ms=int((time.perf_counter() - t0) * 1000), origin=origin)
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    try:
        body = r.json()
    except ValueError:
        body = None
    ok = r.status_code == 200 and isinstance(body, dict) and body.get("code") == "00000" and body.get("data") not in (None, [])
    log_call(source=source, operation=op, ok=ok, status=str(r.status_code) + (f"/{body.get('code')}" if isinstance(body, dict) else ""),
             latency_ms=ms, origin=origin)
    if not ok:
        raise RuntimeError(f"{path}: HTTP {r.status_code} {str(body)[:160]}")
    return body["data"]


# --------------------------------------------------------------------------- technical-analysis skill


_TA_LOCK = threading.Lock()


def _ta_manager(ta_src: str | None = None):
    d = str(Path(ta_src) if ta_src else TA_DIR)
    with _TA_LOCK:
        if d not in sys.path:
            sys.path.insert(0, d)
        from kline_indicator_utils import IndicatorManager  # type: ignore  # the skill's own module
    return IndicatorManager(show_indicators=False)


def ta_on_candles(rows: list[list], ta_src: str | None = None) -> dict[str, float]:
    """Run the skill's IndicatorManager on Bitget v2 candle rows. -> {YYYY-MM-DD: RSI14}."""
    import pandas as pd
    rows = sorted(rows, key=lambda r: int(r[0]))
    df = pd.DataFrame([r[:8] for r in rows], columns=["timestamp", "open", "high", "low", "close", "volume", "quoteVol", "amount"][:len(rows[0][:8])])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    out = _ta_manager(ta_src).calculate_and_export(TA_CONFIG, df, tail=len(df))
    series = out["indicators"]["RSI"]["series"]
    vals = next(iter(series.values()))
    days = [datetime.fromtimestamp(int(r[0]) / 1000, timezone.utc).date().isoformat() for r in rows]
    return {d: round(v, 1) for d, v in zip(days, vals) if v is not None}


def candle_symbol(base: str) -> str:
    return f"{base}USDT" if base in CRYPTO else f"R{base}USDT"


def run_technical_analysis(symbol: str, ta_src: str | None = None, http: httpx.Client | None = None,
                           origin: str = "probe", limit: int = 300) -> dict:
    """Template A of the skill: Bitget v2 spot daily candles -> RSI(14). Returns a small dict."""
    own = http is None
    http = http or httpx.Client(timeout=10.0)
    try:
        # The skill's doc says granularity "1d"; the live API rejects it (code 400171) and wants "1day".
        data = _rest(http, "/api/v2/spot/market/candles", {"symbol": symbol, "granularity": "1day", "limit": str(limit)},
                     "bitget-signal", f"technical-analysis candles {symbol} 1day", origin=origin)
        by_day = ta_on_candles(data, ta_src)
        last = max(by_day) if by_day else None
        return {"ok": bool(by_day), "symbol": symbol, "days": len(by_day), "last_day": last,
                "rsi14_last": by_day.get(last) if last else None}
    finally:
        if own:
            http.close()


# --------------------------------------------------------------------------- the adapter


@dataclass
class SourceState:
    key: str
    name: str
    state: str = "not asked yet"         # answering / down / not asked yet
    last_try: str | None = None
    last_ok: str | None = None
    detail: str = ""


@dataclass
class Cache:
    sources: dict[str, SourceState] = field(default_factory=lambda: {k: SourceState(k, v) for k, v in SOURCE_NAMES.items()})
    rsi: dict[str, dict[str, float]] = field(default_factory=dict)        # base -> day -> RSI14
    rsi_symbol: dict[str, str] = field(default_factory=dict)
    funding: dict[str, dict[str, list[float]]] = field(default_factory=dict)  # base -> day -> rates
    earnings: dict[str, list[str]] = field(default_factory=dict)          # base -> [YYYY-MM-DD]
    sentiment: dict | None = None
    fetched_at: dict[str, float] = field(default_factory=dict)            # "<source>:<base>" -> epoch
    last_pass: float | None = None
    passes: int = 0


CACHE = Cache()
WANT: list[str] = []
_LOCK = threading.Lock()
_started = False


def base_of(symbol: str | None) -> str | None:
    """'xyz:NVDA', 'RNVDAUSDT', 'rNVDA', 'NVDAUSDT', 'NVDA-PERP' -> 'NVDA'."""
    if not symbol:
        return None
    s = str(symbol).strip()
    s = s.split(":")[-1]
    s = re.sub(r"(/?USDT|/?USDC|-PERP|-USD|_PERP)$", "", s, flags=re.I)
    # rNVDA -> NVDA. Upper-case R is only stripped for known stocks (RNVDA), so RUNE stays RUNE.
    if len(s) > 1 and (s[0] == "r" and s[1:].isupper() or s[0] == "R" and s[1:].upper() in DEFAULT_WATCH):
        s = s[1:]
    s = s.upper()
    return s if re.fullmatch(r"[A-Z0-9]{1,10}", s) else None


def want(symbol: str | None) -> None:
    """Register interest (cheap, no network). The next background pass fetches it."""
    b = base_of(symbol)
    if b and b not in DEFAULT_WATCH:
        with _LOCK:
            if b not in WANT and len(WANT) < MAX_WATCH:
                WANT.append(b)


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def _mark(c: Cache, key: str, ok: bool, detail: str = "") -> None:
    s = c.sources[key]
    now = _iso(time.time())
    s.last_try = now
    if ok:
        s.state, s.last_ok, s.detail = "answering", now, detail
    else:
        s.state, s.detail = "down", detail[:200]


_DATE_KEYS = ("date", "report_date", "reportDate", "earnings_date", "earningsDate", "fiscal_date_ending", "announce_date")


def _dates_in(payload: Any) -> list[str]:
    found: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in _DATE_KEYS and isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
                    found.add(v[:10])
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(payload)
    return sorted(found)


def refresh_once(http: httpx.Client | None = None, watch: list[str] | None = None, cache: Cache | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> Cache:
    """One background pass over every source. Each source failing is recorded, never raised."""
    c = cache or CACHE
    own = http is None
    http = http or httpx.Client(timeout=8.0, headers={"User-Agent": "loop/1 (read-only)"})
    with _LOCK:
        bases = list(dict.fromkeys((watch or DEFAULT_WATCH) + ([] if watch else WANT)))
    try:
        # 2. technical-analysis skill on Bitget public candles
        ok_any, err = False, ""
        for b in bases:
            sym = candle_symbol(b)
            try:
                data = _rest(http, "/api/v2/spot/market/candles", {"symbol": sym, "granularity": "1day", "limit": "300"},
                             "bitget-signal", f"technical-analysis candles {sym} 1day")
                c.rsi[b] = ta_on_candles(data)
                c.rsi_symbol[b] = sym
                c.fetched_at[f"signal-ta:{b}"] = time.time()
                ok_any = True
            except Exception as e:
                err = f"{sym}: {str(e)[:120]}"
            sleep(PAUSE_S)
        _mark(c, "signal-ta", ok_any, "" if ok_any else err)

        # 3. Agent Hub market verb getFundingRateHistory (stock perps / crypto perps)
        ok_any, err = False, ""
        for b in bases:
            sym = f"{b}USDT"
            try:
                data = _rest(http, "/api/v3/market/history-fund-rate", {"category": "USDT-FUTURES", "symbol": sym, "limit": "100"},
                             "agenthub", f"market getFundingRateHistory {sym}")
                per_day: dict[str, list[float]] = {}
                for row in (data or {}).get("resultList", []) if isinstance(data, dict) else []:
                    d = datetime.fromtimestamp(int(row["fundingRateTimestamp"]) / 1000, timezone.utc).date().isoformat()
                    per_day.setdefault(d, []).append(float(row["fundingRate"]))
                if per_day:
                    c.funding[b] = per_day
                    c.fetched_at[f"agenthub-funding:{b}"] = time.time()
                    ok_any = True
            except Exception as e:
                err = f"{sym}: {str(e)[:120]}"
            sleep(PAUSE_S)
        _mark(c, "agenthub-funding", ok_any, "" if ok_any else err)

        # 1. bitget-mcp-server equity_calendar (stocks only); stop at the first failure in a pass
        m = McpClient(http, MCP_URL, "bitget-mcp")
        if not m.initialize():
            _mark(c, "bitget-mcp", False, "initialize failed")
        else:
            ok_any, err = False, ""
            for b in [x for x in bases if x not in CRYPTO]:
                verdict, payload, note, st = m.call("do_query", {"entry_id": "equity_calendar", "params": {"symbol": b}},
                                                    f"do_query equity_calendar {b}")
                if verdict == "answers":
                    c.earnings[b] = _dates_in(payload)
                    c.fetched_at[f"bitget-mcp:{b}"] = time.time()
                    ok_any = True
                else:
                    err = f"equity_calendar {b}: {verdict} ({note})"
                    break
                sleep(PAUSE_S)
            _mark(c, "bitget-mcp", ok_any, "" if ok_any else err)

        # 4. bitget-signal sentiment-analyst: one "now" reading per pass
        s = McpClient(http, SIGNAL_URL, "bitget-signal")
        if not s.initialize():
            _mark(c, "signal-sentiment", False, "initialize failed")
        else:
            verdict, payload, note, st = s.call("sentiment_index", {"action": "current"}, "sentiment_index current")
            if verdict == "answers":
                c.sentiment = {"payload": payload, "at": time.time()}
                _mark(c, "signal-sentiment", True)
            else:
                _mark(c, "signal-sentiment", False, f"sentiment_index: {verdict} ({note})")
    finally:
        c.last_pass = time.time()
        c.passes += 1
        if own:
            http.close()
    return c


def start_refresher() -> None:
    global _started
    if _started or os.environ.get("LOOP_NO_REFRESH"):
        return
    _started = True

    def loop():
        while True:
            try:
                refresh_once()
            except Exception:
                pass
            time.sleep(REFRESH_S)
    threading.Thread(target=loop, daemon=True, name="bitget-context-refresher").start()


def _day(x: Any) -> date | None:
    if isinstance(x, datetime):
        return x.astimezone(timezone.utc).date() if x.tzinfo else x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, (int, float)):
        return datetime.fromtimestamp(x / 1000 if x > 1e11 else x, timezone.utc).date()
    if isinstance(x, str) and re.match(r"\d{4}-\d{2}-\d{2}", x):
        return date.fromisoformat(x[:10])
    return None


def _piece(c: Cache, key: str, base: str, text: str, operation: str, value: Any, day: date, now: float) -> dict:
    fetched = c.fetched_at.get(f"{key}:{base}") or (c.sentiment or {}).get("at")
    age = now - fetched if fetched else None
    return {"available": True, "label": LABEL, "state": "stale" if age and age > STALE_S else "ok",
            "text": text, "value": value, "source": key, "source_name": SOURCE_NAMES[key], "operation": operation,
            "symbol": base, "trade_day": day.isoformat(), "fetched_at": _iso(fetched), "age_s": round(age) if age else None,
            "provenance": "Bitget AI tool answer cached by a background pass; not used by any detector or verdict"}


def context_for(symbol: str | None, trade_day: Any, cache: Cache | None = None, now: float | None = None) -> dict:
    """At most one labelled piece of context for (symbol, trade day). Reads the cache only."""
    c = cache or CACHE
    now = now or time.time()
    want(symbol)
    base, day = base_of(symbol), _day(trade_day)
    srcs = {k: asdict(v) for k, v in c.sources.items()}
    answering = [k for k, v in c.sources.items() if v.state == "answering"]
    if c.last_pass is None:
        return {"available": False, "label": LABEL, "state": "not asked yet",
                "text": "No Bitget skill has been asked yet (the background pass has not run).", "sources": srcs}
    if not answering:
        return {"available": False, "label": LABEL, "state": "none answered",
                "text": f"No Bitget skill answered at {_iso(c.last_pass)}.", "sources": srcs}
    if base and day:
        if "bitget-mcp" in answering:
            near = [d for d in c.earnings.get(base, []) if abs((date.fromisoformat(d) - day).days) <= EARNINGS_WINDOW_D]
            if near:
                d = min(near, key=lambda x: abs((date.fromisoformat(x) - day).days))
                delta = (date.fromisoformat(d) - day).days
                when = "on the trade day" if delta == 0 else f"{abs(delta)} day(s) {'after' if delta > 0 else 'before'} this trade"
                return _piece(c, "bitget-mcp", base, f"{base} earnings date {d}, {when}.", "do_query equity_calendar",
                              {"earnings_date": d, "days_from_trade": delta}, day, now)
        if "signal-ta" in answering and day.isoformat() in c.rsi.get(base, {}):
            v = c.rsi[base][day.isoformat()]
            zone = "overbought zone (above 70)" if v > 70 else "oversold zone (below 30)" if v < 30 else "neutral zone"
            if day.isoformat() == max(c.rsi[base]):
                zone += "; that daily candle was still open when fetched"
            return _piece(c, "signal-ta", base, f"Daily RSI(14) on {c.rsi_symbol.get(base, base)} was {v} on the trade day: {zone}.",
                          "technical-analysis RSI(14) on 1day candles", {"rsi14": v, "candles": c.rsi_symbol.get(base)}, day, now)
        if "agenthub-funding" in answering and day.isoformat() in c.funding.get(base, {}):
            rates = c.funding[base][day.isoformat()]
            mean = sum(rates) / len(rates)
            return _piece(c, "agenthub-funding", base, f"{base}USDT perp funding averaged {mean * 1e4:.2f} bp per interval "
                          f"on the trade day ({len(rates)} settlements).", "market getFundingRateHistory",
                          {"mean_rate": mean, "n": len(rates)}, day, now)
        if "signal-sentiment" in answering and c.sentiment and abs((datetime.fromtimestamp(c.sentiment["at"], timezone.utc).date() - day).days) <= 1:
            p = c.sentiment["payload"]
            val = p.get("value") if isinstance(p, dict) else None
            cls = p.get("classification") or p.get("value_classification") if isinstance(p, dict) else None
            return _piece(c, "signal-sentiment", base, f"Market sentiment index at fetch time: {val} ({cls}).",
                          "sentiment_index current", {"value": val, "classification": cls}, day, now)
    return {"available": False, "label": LABEL, "state": "none for this trade",
            "text": (f"Bitget skills answered at {_iso(c.last_pass)} ({', '.join(answering)}), "
                     f"but none has context for {base or symbol} on {day or trade_day}."), "sources": srcs}


def attach(review: dict, symbol: str | None, trade_day: Any, cache: Cache | None = None) -> dict:
    """Return a copy of a review dict with exactly one 'bitget_context' entry. Never raises."""
    try:
        ctx = context_for(symbol, trade_day, cache)
    except Exception as e:  # the review must never fail because of context
        ctx = {"available": False, "label": LABEL, "state": "error", "text": f"context adapter error: {type(e).__name__}"}
    return {**review, "bitget_context": ctx}


def status(cache: Cache | None = None) -> dict:
    c = cache or CACHE
    return {"last_pass": _iso(c.last_pass), "passes": c.passes, "refresher": "on" if _started else (
        "off (LOOP_NO_REFRESH is set)" if os.environ.get("LOOP_NO_REFRESH") else "not started"),
        "sources": [asdict(v) for v in c.sources.values()],
        "symbols": {"rsi": sorted(c.rsi), "funding": sorted(c.funding), "earnings": sorted(c.earnings)}}
