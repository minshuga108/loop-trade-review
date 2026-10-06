# Bitget AI tools: what answered without a key (2026-10-05, 22:18-22:22 UTC)

Raw file: `evidence/bitget_tools_20261005T222154Z.json` (every request, status, latency, trimmed reply).
Call log: `evidence/bitget_calls.jsonl` (one row per outbound call; `origin` = `probe` or `product`).
Re-run: `python scripts/probe_bitget_tools.py`. Live page: `/evidence`, JSON: `/api/evidence`.

Rules followed: public read-only calls only. No keys, no logins, no orders, no paper orders, no dry-run orders.
One call at a time with a 0.6 s pause.

## Verdict per tool path

| Path | How it was called | Verdict |
|---|---|---|
| (a) `bgc`, the official CLI | `npx -y @bitget-ai/bitget-agent-cli@3.0.0 --read-only market --action ...` | **Answers.** 6 of 6 market calls (tickers RNVDAUSDT and NVDAUSDT, orderbook, candles, fundingRate, fundingRateHistory). A private read (`account_overview`) returns "Private endpoint requires API credentials." |
| (b) bitget-mcp-server | JSON-RPC POST to `https://agent.bitget.com/mcp` | **Handshake only.** `initialize` (server 4.0.5), `tools/list` (guide, do_query) and `guide` answer. All 4 data calls (`equity_price_quote`, `equity_calendar`, `equity_fundamental_metrics`, `sentiment_market_fear_greed`) return `success:false, status_code:503`. Plain GET: 400 "Missing session ID". REST mirror: HTTP 503. Same as 2026-10-04 and 10-05. |
| (c) bitget-signal, 4 server skills | JSON-RPC POST to `https://datahub.noxiaohao.com/mcp` (the host the npm package installs; not a Bitget domain) | **No data.** Handshake and `tools/list` (19 tools) answer. All 8 data calls (2 per skill: sentiment-analyst, news-briefing, macro-analyst, market-intel) come back after 15-30 s with `{"error": ""}`, empty feeds, or `ConnectTimeout`. |
| (c) bitget-signal technical-analysis | The skill's own MIT Python (`kline_indicator_utils.py`), run locally on Bitget public candles, as its Template A says | **Answers.** RSI(14) on RNVDAUSDT daily, 300 candles, 1.5 s. It needs no server. |
| (d) Agent Hub surface | `bgc --full discover --domain <d>` for 7 domains | **Answers.** 103 operations; **16 are public**, all in `market`. Every trade, account, funds, subaccount, loan and tax operation needs a key. |

## Exact calls (from the JSON file)

| Path | Call | Status | Latency | Verdict | Note |
|---|---|---|---|---|---|
| bgc | market tickers RNVDAUSDT (`GET /api/v3/market/tickers`) | exit 0 | 3824 ms | answers | latency includes npx start-up |
| bgc | market tickers NVDAUSDT | exit 0 | 2565 ms | answers | |
| bgc | market orderbook RNVDAUSDT limit 5 | exit 0 | 2537 ms | answers | |
| bgc | market candles NVDAUSDT 1D limit 5 | exit 0 | 2687 ms | answers | |
| bgc | market fundingRate NVDAUSDT | exit 0 | 2737 ms | answers | |
| bgc | market fundingRateHistory NVDAUSDT (`GET /api/v3/market/history-fund-rate`) | exit 0 | 2472 ms | answers | |
| bgc | account_overview --coin USDT | exit 0 | 2173 ms | needs key | "Private endpoint requires API credentials." |
| bgc | discover --domain market/trade/account/funds/subaccount/loan/tax | exit 0 | 2.0-2.2 s each | answers | introspection only |
| bitget-mcp | initialize | 200 | 554 ms | answers | serverInfo bitget-mcp-server 4.0.5 |
| bitget-mcp | tools/list | 200 | 188 ms | answers | guide, do_query |
| bitget-mcp | guide {category: equity} | 200 | 223 ms | answers | catalog, not data |
| bitget-mcp | do_query equity_price_quote {symbol: NVDA} | 200 | 211 ms | error | success=false, status_code 503 |
| bitget-mcp | do_query equity_calendar {symbol: NVDA} | 200 | 196 ms | error | same |
| bitget-mcp | do_query equity_fundamental_metrics {symbol: NVDA} | 200 | 227 ms | error | same |
| bitget-mcp | do_query sentiment_market_fear_greed | 200 | 205 ms | error | same |
| bitget-mcp | GET /mcp | 400 | 188 ms | error | "Bad Request: Missing session ID" |
| bitget-mcp | GET /api/v1/equity/price/quote?symbol=NVDA | 503 | 172 ms | error | nginx 503 page |
| bitget-signal | initialize | 200 | 405 ms | answers | serverInfo market-data-mcp 1.26.0 |
| bitget-signal | tools/list | 200 | 189 ms | answers | 19 tools |
| bitget-signal | sentiment-analyst: sentiment_index {action: current} | 200 | 30205 ms | error | `{"alt_me_error": ""}` |
| bitget-signal | sentiment-analyst: derivatives_sentiment long_short BTCUSDT 4h | 200 | 15192 ms | error | `{"error": ""}` |
| bitget-signal | news-briefing: news_feed latest (4 feeds) | 200 | 20236 ms | error | each feed `error: "", items: []` |
| bitget-signal | news-briefing: tradfi_news news | 200 | 15178 ms | error | `{"error": ""}` |
| bitget-signal | macro-analyst: rates_yields rates_snapshot | 200 | 20277 ms | error | 11 rates, each `{"error": ""}` |
| bitget-signal | macro-analyst: macro_indicators latest_release cpi | 200 | 20206 ms | error | `{"error": ""}` |
| bitget-signal | market-intel: crypto_market global | 200 | 30181 ms | error | isError: ConnectTimeout |
| bitget-signal | market-intel: defi_analytics stablecoins | 200 | 20191 ms | error | `{"error": ""}` |
| bitget-signal | technical-analysis: RSI(14) on RNVDAUSDT 1day | local | 1529 ms | answers | RSI 69.3 on 2026-10-05 (candle still open) |

## How "answers" is decided

The verdict is set by code (`engine/bitget_context.classify_tool_result`), not by hand. HTTP 200 is not enough. A reply with
`success:false`, an upstream `status_code` of 400 or more, `isError:true`, or only `error` fields and no data counts as an **error**.
Example: `rates_snapshot` returns 11 `{"error": ""}` fields plus `yield_curve_inverted: false`, which is an error, not an answer.
A path only counts as answering if a **data** call answered. Handshakes (`initialize`, `tools/list`, `guide`, `discover`) are listed
but never counted.

## What the product uses

`engine/bitget_context.py` runs in the background (never on the request path) and attaches at most one line, labelled
"context, not evidence", to a review. It tries these sources in order: MCP earnings date, then the technical-analysis skill's
RSI on the trade day, then Agent Hub funding on the trade day, then the sentiment-analyst reading. Today MCP and sentiment are
down, so the line comes from the technical-analysis skill or the Agent Hub funding history. One real background pass (22:17 UTC)
called 4 distinct data operations and 2 answered (`technical-analysis candles 1day` for 8 symbols, `market getFundingRateHistory`
for 8 symbols). `do_query equity_calendar` got 503 and `sentiment_index` timed out after 8 s. These counts come from the log.

Doc bug found: the technical-analysis SKILL.md says granularity `1d`. The live API rejects it (code 400171) and needs `1day`.
