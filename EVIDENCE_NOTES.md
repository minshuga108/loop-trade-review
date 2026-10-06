# Bitget tool evidence: notes and limits

New files only. Nothing existing was edited.

- `scripts/probe_bitget_tools.py` probes every keyless path and writes `evidence/bitget_tools_<UTC>.json`.
- `evidence/EVIDENCE.md` is the judge-readable result.
- `evidence/bitget_calls.jsonl` is the append-only call log.
- `engine/bitget_context.py` is the background adapter: one "context, not evidence" line per review.
- `engine/vendor/bitget_signal_ta/` holds the technical-analysis skill's Python, unmodified, with its MIT licence and sha256.
- `app/evidence_api.py` serves `GET /api/evidence`, `GET /api/evidence/context?symbol=&day=` and `GET /evidence`.
- `app/static/evidence.html` and `evidence.js` are the page. The script is external, so the CSP inline-hash count test stays at 4.
- `tests/test_bitget_evidence.py` has 28 tests, all on mocked transports (`httpx.MockTransport`).

## To wire it in (owner)

In `app/main.py`, after the other routers:

    from .evidence_api import router as evidence_router; app.include_router(evidence_router)  # noqa: E402,E702

To start the background pass, add this to `_startup()`:

    from engine import bitget_context; bitget_context.start_refresher()

(It respects `LOOP_NO_REFRESH`, like `costs.py`.)

To put the line on a review, `bitget_context.attach(review, symbol, trade_day)` returns a copy with one `bitget_context` key. It reads the cache only and never raises. I did not touch `service.py`, so no review carries the line yet.

## Limits (honest)

1. **The headline Bitget-native data comes from public REST.** The bitget-mcp-server (all data calls, 503) and the four server-backed bitget-signal skills (all data calls fail upstream) gave no data. What answers is the `bgc` market verb, the Agent Hub public market operations, and the technical-analysis skill, which runs locally on Bitget candles.
2. **The "skill" that answers is code we run ourselves.** technical-analysis is the skill's own MIT code run on Bitget's public candles. It is not a hosted service answering. The UI names it that way.
3. **The product does not call `bgc` at run time.** The Docker image has no Node. The adapter calls the same REST operation `bgc` runs: `getFundingRateHistory` at `GET /api/v3/market/history-fund-rate`, which `bgc` reports as its `endpoint`. The label says "Agent Hub market verb operation", not "bgc".
4. **Operation counts.** They group by operation, not by symbol, and exclude handshakes (`initialize`, `tools/list`, `guide`, `discover`). A failed call still counts as "called" but not as "answered". Today the product called 4 operations and 2 answered.
5. **Where the log rows came from.** The committed `bitget_calls.jsonl` holds rows from two probe runs (22:10 and 22:18 UTC) and one product pass (22:17 UTC), all made on the dev machine on 2026-10-05. The 22:10 run's JSON was replaced by the 22:18 run, which had the same verdicts and only a corrected label. Two earlier runs were discarded with their log rows because their classifier was wrong: it counted `{"error": ""}` replies as answers. On a server, the log grows from that host's own calls. It is not shared between hosts, and the container filesystem may be wiped on redeploy.
6. **RSI caveats.** RSI is computed on the rToken spot candles (`R<TICKER>USDT`) for stocks and on spot `<COIN>USDT` for crypto, not on the perp. If the trade day is the latest candle, the line says that candle was still open. The default watchlist is 8 symbols. `want()` adds up to 24 more from reviews (no network on the request path). An upper-case `R` prefix is stripped only for known stock tickers.
7. **Funding history is short.** It covers the last 100 settlements, about 33 days at 8 h. Older trade days get no funding line.
8. **Sentiment is a "now" reading.** It is shown only for trade days within one day of the fetch. Its timeout is 8 s in the product, while the host takes 15-30 s just to fail.
9. **Earnings parsing is untested against a live reply.** MCP `equity_calendar` has never answered, so the date-field names it looks for are a guess. It is tested only on a mocked reply.
10. **The bgc latency** in the probe includes npx start-up of about 2 s. Raw REST takes 0.2-0.4 s.
11. **Flaky existing test.** `tests/test_browser.py::test_pages_work_with_security_headers_and_rate_limits_on` failed once in the full run and passed when run alone. It depends on rate-limit timing and does not touch these files. Full suite: 939 passed, then 1 flaky failure.
12. **Doc bug found.** The technical-analysis SKILL.md says granularity `1d`, but the API returns 400171 and needs `1day`.
13. **Nothing here places, previews or signs an order.** That includes paper and dry-run orders.
