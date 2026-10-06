# Detectors 2: notes

New files only (no existing file edited): `engine/detectors2.py`, `engine/structural_gap.py`, `engine/winrate.py`,
`engine/ledger_drift.py`, `engine/planted2.py` (SIM_PLANTED fixtures), and tests
`tests/test_detectors2.py` (14), `tests/test_structural_gap_winrate.py` (12), `tests/test_ledger_drift.py` (24).
50 new tests, all pass (~27 s).

## What each module does
- **overtrading_clusters**: UTC days whose trip count exceeds the trader's own 90th percentile (active days only).
  Within-trader permutation test that mean net pnl per trip is lower on those days. Gates: 20 active days,
  20 trips per group, effect floor 0.25 SD of the trader's trip pnl, p < 0.05.
- **fee_drag**: fees / gross profit (sum of pre-fee pnl on trips that made money before fees), bootstrap interval,
  no p-value (status DESCRIPTIVE/UNDERPOWERED). Also reports fees / total gross pnl when that is positive.
  `trip_fees(fills, trips)` re-segments fills exactly like `ledger.to_round_trips` (keyed by symbol, open time,
  first order id); trips without fills get NaN and are dropped and counted, never guessed.
- **revenge_reentry**: same-symbol trip opened within 15 min of a losing close with first-order notional >= 1.4x
  the trader's median; permutation test of its net pnl (dollars) against other same-symbol re-entries within
  15 min. `extra` shows mean return per notional for both groups so size vs decision quality can be read apart.
- **structural_gap**: `tag_stop_exits` -> NOT_TRIGGERED / HONOURED / BEHAVIOURAL_BREACH / STRUCTURAL_GAP.
  Gap tolerance 0.2% of stop, exit grace 60 s (pre-registered). `behavioural_score` excludes gaps but returns
  their cost. Needs 10 eligible stops.
- **winrate**: breakeven win rate = avg loss / (avg win + avg loss) on net results; moving-block bootstrap
  (block = ceil(sqrt(n))) intervals for required, actual and margin; same again without the single best trade.
- **ledger_drift**: classifies financial-records rows into FUNDING (SCHEMA.md S5 regex), TRADE (cross-check only,
  not added, to avoid double counting fills), LIQUIDATION_FEE, TRANSFER (incl. funding-wallet `groupType`),
  REBATE_AIRDROP_OTHER, UNCLASSIFIED. Residual = balance change - explained; UNEXPLAINED above 0.1% of start
  equity (configurable). Residual is never plugged. Decimal arithmetic. Tested on the real ccxt funding row
  (reconciles to 0) and the 4 real funding-wallet rows (incl. one with blank `type`).

## Honest limitations
- Permutation tests shuffle trip labels, so they treat trips as exchangeable; same-day trips may be correlated
  (overtrading) and a day-level permutation would be more conservative.
- The 1.4x median in revenge_reentry uses the full-history median (descriptive, slight look-ahead); it is not used
  as a trading rule.
- The revenge test is on dollars, so a bigger size with the same per-notional edge but negative mean would also
  flag; read `extra` returns before calling it a decision problem.
- `tag_stop_exits` needs the trip window and exit price beyond the spec's (trip id, stop, side); the caller must
  supply prints; nothing here fetches prices. A gap followed by a late exit is tagged BEHAVIOURAL_BREACH.
- ledger_drift: whether `amount` excludes the row's `fee` is [inferred]; whether LIQ_FEE is already inside fill
  fees is [UNVERIFIED] (if it is, it would be double counted and show up as residual). Only one real
  financial-records row was available to test against.
- Pre-existing tests that read `../data/...` relative to the cwd fail when run from this worktree (path depth),
  and 6 app/chat tests fail even from the main checkout with this worktree on PYTHONPATH; unrelated to these files.
