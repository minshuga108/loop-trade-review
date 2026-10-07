"""Read-only Bitget PUBLIC market data (v2 mix): ticker, funding (current + history), open interest, candles,
recent fills, account long/short ratio.

Rules: GET only, no key, no signature. TTL cache, short timeout, one in-flight request per key. Offline (or LOOP_NO_REFRESH
without an explicit configure()) returns a clean 'not available' result; a value is never invented or carried past its TTL
as if it were fresh. Every result carries provenance REAL_PLATFORM_PUBLIC, fetch time and latency.

Probe tiers per endpoint:  attempted -> reachable (got an HTTP reply) -> answering (code 00000 and parseable rows)
                           -> changed_answer (a gate verdict context, chat answer or report line actually used it).
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from datetime import datetime, timezone

import httpx

BASE = "https://api.bitget.com"
PROVENANCE = "REAL_PLATFORM_PUBLIC"
TIMEOUT_S = 2.5
TTL_S = {"ticker": 10, "funding": 60, "funding_history": 300, "open_interest": 30, "candles": 120, "fills": 10, "long_short": 300}
PATHS = {"ticker": "/api/v2/mix/market/ticker", "funding": "/api/v2/mix/market/current-fund-rate",
         "funding_history": "/api/v2/mix/market/history-fund-rate", "open_interest": "/api/v2/mix/market/open-interest",
         "candles": "/api/v2/mix/market/candles", "fills": "/api/v2/mix/market/fills",
         "long_short": "/api/v2/mix/market/account-long-short"}
NAMES = {"ticker": "Futures ticker", "funding": "Current funding rate", "funding_history": "Funding rate history",
         "open_interest": "Open interest", "candles": "Candles (1h)", "fills": "Recent public fills", "long_short": "Account long/short ratio"}

_CLIENT: httpx.Client | None = None
_FORCE = False
_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[float, dict]] = {}
_FLIGHT: dict[tuple, threading.Lock] = {}
_PROBE: dict[str, dict] = {k: {"attempted": 0, "reachable": 0, "answering": 0, "changed_answer": 0, "last_at": None,
                               "last_latency_ms": None, "last_error": None} for k in PATHS}


def configure(client: httpx.Client | None = None, force: bool = True) -> None:
    """Tests inject a mocked client; production never calls this."""
    global _CLIENT, _FORCE
    _CLIENT, _FORCE = client, force


def reset() -> None:
    with _LOCK:
        _CACHE.clear()
        _FLIGHT.clear()
        for p in _PROBE.values():
            p.update(attempted=0, reachable=0, answering=0, changed_answer=0, last_at=None, last_latency_ms=None, last_error=None)


def enabled() -> bool:
    return _FORCE or not os.environ.get("LOOP_NO_REFRESH")


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def _f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def perp_symbol(symbol: str | None) -> str | None:
    """'BTC', 'btcusdt', 'RNVDAUSDT' -> 'BTCUSDT' / 'NVDAUSDT' (the perp). None if it is not a plain ticker."""
    from engine import bitget_context as bc
    b = bc.base_of(symbol)
    return f"{b}USDT" if b else None


def _params(kind: str, sym: str) -> dict:
    if kind == "long_short":
        return {"symbol": sym, "period": "1h"}
    p = {"symbol": sym, "productType": "USDT-FUTURES"}
    if kind == "funding_history":
        p["pageSize"] = "10"
    elif kind == "candles":
        p.update(granularity="1H", limit="24")
    elif kind == "fills":
        p["limit"] = "20"
    return p


def _parse(kind: str, data) -> dict | None:
    """Raw 'data' -> a small dict of floats, or None when the shape is not what Bitget documents."""
    try:
        if kind == "ticker":
            r = data[0]
            out = {k: _f(r.get(k)) for k in ("lastPr", "bidPr", "askPr", "bidSz", "askSz", "high24h", "low24h", "change24h",
                                              "usdtVolume", "markPrice", "indexPrice", "fundingRate")}
            return out if out["lastPr"] and out["bidPr"] and out["askPr"] else None
        if kind == "funding":
            r = data[0]
            rate = _f(r.get("fundingRate"))
            return None if rate is None else {"rate": rate, "interval_h": _f(r.get("fundingRateInterval")) or 8.0,
                                              "next_update_ms": int(r["nextUpdate"]) if r.get("nextUpdate") else None}
        if kind == "funding_history":
            rows = [{"rate": _f(r.get("fundingRate")), "t_ms": int(r["fundingTime"])} for r in data]
            rows = [r for r in rows if r["rate"] is not None]
            return {"rows": rows} if rows else None
        if kind == "open_interest":
            r = data["openInterestList"][0]
            size = _f(r.get("size"))
            return None if size is None else {"size": size, "ts_ms": int(data["ts"]) if data.get("ts") else None}
        if kind == "candles":
            rows = [{"t_ms": int(r[0]), "o": _f(r[1]), "h": _f(r[2]), "l": _f(r[3]), "c": _f(r[4])} for r in data]
            rows = sorted((r for r in rows if None not in (r["o"], r["h"], r["l"], r["c"])), key=lambda r: r["t_ms"])
            return {"rows": rows} if len(rows) >= 2 else None
        if kind == "fills":
            rows = [{"price": _f(r.get("price")), "size": _f(r.get("size")), "side": r.get("side")} for r in data]
            rows = [r for r in rows if r["price"] and r["size"]]
            return {"rows": rows} if rows else None
        if kind == "long_short":
            rows = [{"long": _f(r.get("longAccountRatio")), "short": _f(r.get("shortAccountRatio")), "ratio": _f(r.get("longShortAccountRatio")),
                     "t_ms": int(r["ts"])} for r in data]
            rows = [r for r in rows if None not in (r["long"], r["short"], r["ratio"])]
            return {"rows": rows} if rows else None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    return None


def _unavailable(kind: str, sym: str, why: str) -> dict:
    return {"ok": False, "kind": kind, "symbol": sym, "reason": why, "provenance": PROVENANCE, "fetched_at": None, "latency_ms": None,
            "cached": False, "endpoint": PATHS.get(kind)}


def _fetch(kind: str, sym: str) -> dict:
    probe = _PROBE[kind]
    probe["attempted"] += 1
    client = _CLIENT or httpx.Client(timeout=TIMEOUT_S)
    t0 = time.perf_counter()
    try:
        r = client.get(BASE + PATHS[kind], params=_params(kind, sym), timeout=TIMEOUT_S)
    except Exception as e:                                   # offline, DNS, timeout: say so, invent nothing
        probe["last_error"] = type(e).__name__
        return _unavailable(kind, sym, f"Bitget did not reply ({type(e).__name__})")
    finally:
        if _CLIENT is None:
            client.close()
    ms = round((time.perf_counter() - t0) * 1000)
    probe.update(reachable=probe["reachable"] + 1, last_latency_ms=ms, last_at=_iso(time.time()))
    try:
        body = r.json()
    except ValueError:
        probe["last_error"] = f"HTTP{r.status_code} non-JSON"
        return _unavailable(kind, sym, f"HTTP {r.status_code}, not JSON")
    if not isinstance(body, dict) or body.get("code") != "00000":
        msg = str(body.get("msg", ""))[:80] if isinstance(body, dict) else ""
        probe["last_error"] = f"code {body.get('code') if isinstance(body, dict) else '?'}"
        return _unavailable(kind, sym, f"Bitget answered with an error: {msg or probe['last_error']}")
    parsed = _parse(kind, body.get("data"))
    if parsed is None:
        probe["last_error"] = "empty or unexpected shape"
        return _unavailable(kind, sym, "Bitget returned no usable rows for this symbol")
    probe["answering"] += 1
    probe["last_error"] = None
    return {"ok": True, "kind": kind, "symbol": sym, "data": parsed, "provenance": PROVENANCE, "fetched_at": _iso(time.time()),
            "fetched_ts": time.time(), "latency_ms": ms, "cached": False, "endpoint": PATHS[kind]}


def get(kind: str, symbol: str | None) -> dict:
    """One endpoint for one symbol. Cached for TTL_S[kind]; concurrent callers share a single request."""
    sym = perp_symbol(symbol)
    if kind not in PATHS or not sym:
        return _unavailable(kind, str(symbol), "no usable symbol")
    if not enabled():
        return _unavailable(kind, sym, "live market calls are switched off in this process")
    key = (kind, sym)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < TTL_S[kind]:
            return {**hit[1], "cached": True}
        flight = _FLIGHT.setdefault(key, threading.Lock())
    with flight:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and time.time() - hit[0] < TTL_S[kind]:
                return {**hit[1], "cached": True}
        res = _fetch(kind, sym)
        if res["ok"]:
            with _LOCK:
                _CACHE[key] = (time.time(), res)
        return res


def mark_changed(*kinds: str) -> None:
    for k in kinds:
        if k in _PROBE:
            _PROBE[k]["changed_answer"] += 1


def probe_status() -> dict:
    rows = []
    for k, p in _PROBE.items():
        tier = ("changed an answer" if p["changed_answer"] else "answering" if p["answering"] else
                "reachable" if p["reachable"] else "attempted" if p["attempted"] else "not attempted")
        rows.append({"id": k, "name": NAMES[k], "path": PATHS[k], "tier": tier, **p})
    return {"provenance": PROVENANCE, "enabled": enabled(), "endpoints": rows}


# ------------------------------------------------------------------ derived facts
def _pct(x: float, dp: int = 4) -> str:
    return f"{x * 100:+.{dp}f}%"


def funding_meaning(rate: float, interval_h: float) -> str:
    h = f"{interval_h:g}h"
    if rate > 0:
        return f"funding {_pct(rate, 3)}/{h}: a long pays, a short receives"
    if rate < 0:
        return f"funding {_pct(rate, 3)}/{h}: a short pays, a long receives"
    return f"funding 0.000%/{h}: nobody pays"


def spread_bps(t: dict) -> float:
    mid = (t["bidPr"] + t["askPr"]) / 2
    return round((t["askPr"] - t["bidPr"]) / mid * 1e4, 2)


def volatility(candles: dict) -> dict:
    rows = candles["rows"]
    rets = [math.log(b["c"] / a["c"]) for a, b in zip(rows, rows[1:]) if a["c"] > 0 and b["c"] > 0]
    if len(rets) < 2:
        return {}
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    hi, lo = max(r["h"] for r in rows), min(r["l"] for r in rows)
    return {"hourly_sd_pct": round(sd * 100, 3), "range_pct": round((hi - lo) / lo * 100, 2), "hours": len(rows)}


def gate_context(symbol: str | None) -> dict:
    """Funding + open interest for the symbol in an idea, labelled context, never evidence."""
    fr, oi = get("funding", symbol), get("open_interest", symbol)
    label = "context, not evidence"
    if not fr["ok"] and not oi["ok"]:
        return {"available": False, "label": label, "provenance": PROVENANCE,
                "text": "Live Bitget funding and open interest are not available right now.", "reason": fr.get("reason")}
    parts, facts = [], {}
    sym = (fr if fr["ok"] else oi)["symbol"]
    if fr["ok"]:
        d = fr["data"]
        parts.append(funding_meaning(d["rate"], d["interval_h"]))
        facts["funding_rate"] = d["rate"]
    if oi["ok"]:
        parts.append(f"open interest {oi['data']['size']:,.2f} contracts")
        facts["open_interest"] = oi["data"]["size"]
    ok = [(k, r) for k, r in (("funding", fr), ("open_interest", oi)) if r["ok"]]
    mark_changed(*[k for k, _ in ok])
    return {"available": True, "label": label, "provenance": PROVENANCE, "symbol": sym, "text": f"{sym} perp: " + "; ".join(parts) + ".",
            "facts": facts, "fetched_at": _iso(max(r["fetched_ts"] for _, r in ok)), "latency_ms": max(r["latency_ms"] for _, r in ok)}


# ------------------------------------------------------------------ chat
_MARKET = re.compile(r"(funding|open interest|\boi\b|spread|volatil|long.?short|资金费|持仓量|未平仓|点差|价差|波动|多空比)", re.I)
_OWN = re.compile(r"\b(my|mine|i paid|did i|i lost)\b|我的|我付|我交易", re.I)
_COIN = re.compile(r"(?<![A-Za-z])r?(BTC|ETH|SOL|XRP|DOGE|BNB|ADA|AVAX|LINK|HYPE|SUI|LTC|TRX|TON|NVDA|TSLA|AAPL|MSTR|SPY|QQQ)(?![A-Za-z])", re.I)       # not \b: a CJK character is a word character, so "BTC现在" has no boundary


_NOW = re.compile(r"(doing now|right now|currently|at the moment|how(?:'s| is| are) |\bprice\b|\bnow\b|现在怎么样|现在多少|现在如何|行情|价格|多少钱)", re.I)
_HIST = re.compile(r"(largest|biggest|worst|best|loss|losses|lost|\btrades?\b|history|last (week|month)|最大|最差|最好|亏|赚|交易|历史)", re.I)


def is_market_question(message: str) -> bool:
    """A live market quantity AND a coin, and not a question about the trader's own record.
    A plain "now / price / how is BTC" question with a coin also counts, unless it asks about past trades."""
    if not _COIN.search(message) or _OWN.search(message):
        return False
    return bool(_MARKET.search(message) or (_NOW.search(message) and not _HIST.search(message)))


def chat_answer(message: str, lang: str) -> dict:
    zh = lang == "zh"
    sym = _COIN.search(message).group(1).upper()
    m = message.lower()
    want = []
    if re.search(r"funding|资金费", m):
        want.append("funding")
    if re.search(r"open interest|\boi\b|持仓量|未平仓", m):
        want.append("open_interest")
    if re.search(r"spread|点差|价差", m):
        want.append("ticker")
    if re.search(r"volatil|波动", m):
        want.append("candles")
    if re.search(r"long.?short|多空比", m):
        want.append("long_short")
    general = not want
    if general:
        want = ["ticker", "funding"]
    results = {k: get(k, sym) for k in want}
    lines, facts, used = [], {}, []
    for k, r in results.items():
        if not r["ok"]:
            continue
        d = r["data"]
        if k == "funding":
            facts["funding_rate_pct"] = round(d["rate"] * 100, 4)
            lines.append((f"{sym} 当前资金费率 {d['rate'] * 100:+.4f}%/{d['interval_h']:g}小时：" +
                          ("多头支付，空头收取。" if d["rate"] > 0 else "空头支付，多头收取。" if d["rate"] < 0 else "无人支付。"))
                         if zh else f"{sym} " + funding_meaning(d["rate"], d["interval_h"]).replace("funding", "funding now", 1) + ".")
        elif k == "open_interest":
            facts["open_interest"] = d["size"]
            lines.append(f"{sym} 未平仓合约量 {d['size']:,.2f} 张。" if zh else f"{sym} open interest is {d['size']:,.2f} contracts.")
        elif k == "ticker":
            sp = spread_bps(d)
            if general:
                facts["last_price"] = d["lastPr"]
                lines.append(f"{sym} 永续最新价 {d['lastPr']:g}" if zh else f"{sym} perp last price {d['lastPr']:g}")
                if d.get("change24h") is not None:
                    facts["change_24h_pct"] = round(d["change24h"] * 100, 2)
                    lines[-1] += (f"，24 小时涨跌 {d['change24h'] * 100:+.2f}%。" if zh else f", {d['change24h'] * 100:+.2f}% over 24 hours.")
                else:
                    lines[-1] += "。" if zh else "."
            facts["spread_bps"] = sp
            lines.append(f"{sym} 永续买卖价差 {sp} 个基点（买 {d['bidPr']:g}，卖 {d['askPr']:g}）。" if zh else
                         f"{sym} perp spread now is {sp} bps (bid {d['bidPr']:g}, ask {d['askPr']:g}).")
            facts.update(bid=d["bidPr"], ask=d["askPr"])
        elif k == "candles":
            v = volatility(d)
            if not v:
                continue
            facts.update(hourly_sd_pct=v["hourly_sd_pct"], range_pct=v["range_pct"], hours=v["hours"])
            lines.append(f"{sym} 过去 {v['hours']} 小时：小时收益标准差 {v['hourly_sd_pct']}%，区间 {v['range_pct']}%。" if zh else
                         f"{sym} over the last {v['hours']} hours: hourly return std dev {v['hourly_sd_pct']}%, high-low range {v['range_pct']}%.")
        elif k == "long_short":
            last = d["rows"][-1]
            facts.update(long_account_pct=round(last["long"] * 100, 2), short_account_pct=round(last["short"] * 100, 2))
            lines.append(f"{sym} 账户多空占比：多 {last['long'] * 100:.2f}%，空 {last['short'] * 100:.2f}%。" if zh else
                         f"{sym} accounts: {last['long'] * 100:.2f}% long, {last['short'] * 100:.2f}% short.")
        used.append(k)
    if lines:
        mark_changed(*used)
        stamp = max(results[k]["fetched_at"] for k in used)
        lat = max(results[k]["latency_ms"] for k in used)
        text = " ".join(lines) + (f" 真实 Bitget 公开数据，取自 {stamp}，延迟 {lat} 毫秒。这是背景信息，不是证据，也不是建议。" if zh else
                                  f" Real Bitget public data, fetched {stamp}, {lat} ms. Context, not evidence, and not advice.")
        shown = [{"fact": k, "value": v} for k, v in facts.items()]
    else:
        text = ("目前拿不到 Bitget 的实时行情，所以我不给数字。稍后再问。" if zh else
                "Live Bitget market data is not available right now, so I will not give a number. Try again shortly.")
        shown = []
    from engine.numberlock import NumberLockError, verify
    stamp_digits = tuple(float(i) for i in range(0, 11)) + (24.0,)
    try:
        # the fetch timestamp and latency are quoted too; they are not market claims, so strip them before the lock
        body = re.sub(r"\d{4}-\d{2}-\d{2}T[\d:+]+|\d+ (ms|毫秒)", "", text)
        verify(body, [float(v) for v in facts.values()], allow=stamp_digits)
        lock = "passed"
    except NumberLockError as e:
        text, lock = (("这个回答包含无法由取得的数据支持的数字，已被拒绝。" if zh else "That answer had a number I could not back with a fetched fact, so I refused it."),
                      f"refused: {e}")
    from . import llm
    return {"intent": "market", "lang": lang, "kind": "text", "text": text, "facts": shown, "number_lock": lock, "llm": llm.label(),
            "interpreted": "市场背景（实时公开数据）" if zh else "market context (live public data)",
            "market_sources": [PATHS[k] for k in used], "market_provenance": PROVENANCE if used else None}


# ------------------------------------------------------------------ weekly report
def funding_line(trips, lang: str = "en") -> str | None:
    """Funding paid vs received on the trader's own symbols, ONLY if the trips carry a funding field. Else None (omit the line)."""
    vals = [(t.symbol, getattr(t, "funding", None)) for t in trips]
    vals = [(s, v) for s, v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    paid = -sum(v for _, v in vals if v < 0)
    got = sum(v for _, v in vals if v > 0)
    syms = len({s for s, _ in vals})
    return (f"资金费：在你交易的 {syms} 个品种上，付出 {paid:,.2f}，收到 {got:,.2f}（来自你自己的成交记录）。" if lang == "zh" else
            f"Funding on your own {syms} symbols: paid {paid:,.2f}, received {got:,.2f} (from your own fills).")
