# Check line: execution-cost module, honest limits

Files: `engine/market.py` (public Bitget client), `engine/execution.py` (depth walk, order rules, slicing, TWAP-like benchmark), `engine/cost_report.py` (card structure, depth ranking, session and funding labels), `scripts/capture_books.py` (JSONL recorder), `tests/test_market_execution.py` + `tests/fixtures/market/` (recorded public replies, 2026-10-05 ~19:35 UTC, US regular session).

## Endpoints (each checked with one live GET, no key)
| Purpose | Path | Notes |
|---|---|---|
| Instrument rules | `GET /api/v3/market/instruments?category=SPOT\|USDT-FUTURES&symbol=` | minOrderAmount, pricePrecision, quantityPrecision, minOrderQty, status, isReality. SPOT rows have NO fee fields. |
| Spot fee | `GET /api/v2/spot/public/symbols?symbol=` | takerFeeRate (standard rate, before VIP/BGB discounts). |
| Ticker | `GET /api/v3/market/tickers?category=&symbol=` | strings; perps add markPrice, indexPrice, fundingRate. |
| Book | `GET /api/v3/market/orderbook?category=&symbol=&limit=` | numbers (not strings); empty book = `{"a":[],"b":[]}`; doc max limit 200. |
| Candles | `GET /api/v3/market/candles?category=&symbol=&interval=&limit=` | arrays of strings. |
| Sessions | `GET /api/v3/reality/market/states` | windows labelled "EST"; read as America/New_York [inferred, CRIT5 2.2]. |
Unknown symbol: code `40034`, `data: null` (raised as `BitgetAPIError`).

## What the numbers are
- `cost_bps` = depth-walk VWAP versus mid on ONE snapshot, fees excluded. `all_in_bps` adds the taker fee only when the fee is known AND the book fills the whole order.
- `fill_fraction` < 1 means the visible book cannot absorb the order; the remainder is reported as `unfilled_usdt`, never assumed to clear.
- Slicing: child <= participation x visible depth within 50 bps on the side taken; "slower mode" if that depth is under 3x the order. 10% participation, 50 bps and 3x are POLICY choices from the brief, not measured.
- Two labelled extremes instead of a refill model: `OPTIMISTIC_FULL_REFILL_ASSUMED` (each child sees the full snapshot again) and `PESSIMISTIC_NO_REFILL` (whole parent walked through the snapshot). Real outcomes are NOT guaranteed to fall between them.
- TWAP benchmark is "Bitget-TWAP-like": equal slices, one per minute, priced on the same snapshot. Bitget's actual TWAP settings (interval, randomisation, limits) are not modelled.
- Deep vs thin: ranked live by the thinner side's depth within 50 bps; "deep" means >= 3x the order size. Nothing is hard-coded per symbol; the tier changes with size.

## Provenance
- Real Bitget book (live or read back from a capture) = `REPLAY_NATIVE`; synthetic books (tests, demo/paptrading) = `SIM_PAPER`. Estimates inherit the book's label. `may_calibrate()` refuses every `SIM_*` label.
- These are predictions. Only observed fills compared against them can calibrate anything (VERIFY_paper_fills.md 5.2 rules apply: min-N, walk-forward, session buckets).

## Proof run of the recorder (2026-10-05 19:41-19:43 UTC, Mon US regular session, limit 50, 15 s)
54 snapshots, 0 errors, 6 symbols x 9 rounds (`data/snapshots/books_20261005T194112Z.jsonl`, 90 KB, gitignored). Buy 5,000 USDT depth-walk cost across the 9 snapshots: RSPY 0.7-1.9 bps, RNVDA 1.9-3.3, RTSLA 1.8-4.2, RQQQ 2.3-4.0, RMSTR 8.4-15.3, RAAPL 12.3-22.5 (fees excluded). Ask depth within 50 bps: RNVDA 674-713k USDT, RQQQ 527-563k, RSPY 477-508k, RTSLA 412-459k, RMSTR 23-39k, RAAPL 18-25k. Two minutes of one weekday afternoon: an illustration that the code works, not a statistic. And see limitation 3: on weekdays this book may not be where orders fill.

## Limitations (all of them that I know)
1. Snapshots are point-in-time. No queue position, no latency, no hidden or iceberg liquidity, no price drift between snapshot and send, no timing risk across a TWAP window (mid is frozen).
2. No own impact beyond the walk itself: we do not model how other participants react to our order, and we do not know how fast levels refill.
3. **The public book is not the weekday price.** In the recorded US regular session (2026-10-05 19:35 UTC) every rToken sampled (RNVDA, RTSLA, RSPY, RQQQ, RAAPL, RMSTR) had a ticker touch INSIDE the public book's touch (e.g. RNVDA ticker 239.82/239.83 vs book 239.77/239.94). Bitget says US-session rToken liquidity connects to brokerage infrastructure (VERIFY_paper_fills 4a). The card flags this (`ticker_vs_book`); the depth-walk cost may overstate weekday cost, and weekday rToken cost cannot be validated from public prints (there are none).
4. The validation evidence for the depth walk (VERIFY_paper_fills 4a: covers 74-78% of real prints at +0 bps, 93-97% within +2 bps) is weekend native rNVDA flow only, 7 file-days. It says nothing about other symbols, weekdays, or perps.
5. The visible native book is short: limit=200 on RNVDA spot returned ~56 levels per side. Orders bigger than the whole visible side report unfilled remainder, not a price.
6. Book sizes are assumed to be in base units (consistent with CRIT5 notionals; doc not re-read).
7. Order rules: the price band (`buyLimitPriceRatio`) is NOT enforced or interpreted (semantics undocumented). Whether Bitget checks the minimum order before or after quantity-step rounding was not verified (no orders placed); we reject conservatively when rounding drops the notional under the minimum. Spot market buys are treated as quote-sized (CRIT5 2.1), so no step rounding applies to them.
8. Fees: spot uses the standard public rate (0.1% on RNVDA), not the user's VIP/BGB rate. Perp fee comes from the instrument row.
9. Sessions: weekend = Sat/Sun on the New York calendar. US holidays are out of scope. The "EST" label from Bitget is read as America/New_York local time [inferred].
10. Funding: the only zero claim is CRIT5 3.1's measurement (settlement slots Sat 08:00 to Mon 08:00 UTC were 0 in 13 of 13 weeks on NVDAUSDT, TSLAUSDT, SPYUSDT). It is empirical, not documented; other symbols are flagged as unmeasured; an 8h 00/08/16 UTC grid is assumed (5 of 325 stock perps use 4h).
11. Candle volumes for rTokens during US hours (e.g. RNVDA ~219k units per minute) are far above anything in the native book; their meaning (likely includes routed/underlying volume) is not documented. They are parsed, not interpreted.
12. The capture script polls sequentially at whatever cadence is chosen; failed calls are written as `error` lines and never back-filled. Captures go to `data/snapshots/` (gitignored).
