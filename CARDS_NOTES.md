# Review cards (R3, R10, R11, R12, M23, ledger drift, structural gap, rule decay)

New files: `app/cards_api.py` (APIRouter), `app/static/cards.js`, `app/static/cards.css`,
`engine/trend.py`, `engine/intent.py`, `engine/replay.py`, `engine/ledger_walk.py`,
`engine/signing.py`, `engine/report_html.py`, `engine/sharecard.py`, `tests/test_cards.py` (16 tests).

## The hook (already added in this branch)

`app/main.py`, directly after `app.include_router(mcp_server.router)` (it must come before the
`/api/report/{tid}` route so `/api/report/{tid}.md` and `.html` match first):

    from .cards_api import router as cards_router; app.include_router(cards_router)

`app/static/index.html`, directly after `<script src="/static/i18n.js"></script>`:

    <link rel="stylesheet" href="/static/cards.css"><script src="/static/cards.js"></script>

cards.js wraps the page's global `render` (and `bookAction`) and appends a "Review tools" section
under the page. It adds Chinese through `ZH_EXACT` / `ZH_PATTERNS` from i18n.js.

## What exists

| Card | Endpoints | Notes |
|---|---|---|
| Trade replay (R3) | `GET /api/trips/{tid}?finding=&limit=&offset=`, `GET /api/trip/{tid}/{index}` | "Open the trades" button on every habit row. Group membership uses the detectors' own labels (after_loss, losing, busiest_day, reentry, revenge). Filtered lists come worst net result first. Fills per trip (12 shown, the rest behind a toggle). Price path and MAE/MFE only from offline candles in `data/candles/<SYMBOL>.json` (`LOOP_CANDLES_DIR`), labelled approximate. None are stored today, so the card says so and draws nothing. |
| Trend and drift (R11) | `GET /api/trend/{tid}?habit=size_after_loss\|hold_asymmetry` | `engine/trend.py`: per-trip habit score against a local baseline that uses only earlier trips; 4 walk-forward windows with bootstrap ranges; two-sided CUSUM with reference period = first third. Its limit is H=5 SD, raised to the 95th percentile of 200 time-order shuffles of the trader's own scores. Siegmund ARL is reported. The before/after Welch test gives the MDE (80% power, 5% two-sided). Trades needed for the next test come from the power formula (target = the detector's effect floor: 1.25x size, 1.5x hold). If even the reference period is too noisy, it gives per-period n for a fresh equal test. |
| Ledger drift | `GET /api/ledger-drift/{tid}` | Demo wallets: honest NO_RECORDS. The demo uses the REAL ccxt rows: the futures funding row reconciles, and the funding-wallet walk finds -1.5 USDT with no row explaining it, pinned to the withdrawal row and assigned to no category. |
| Structural gap | `POST /api/structural-gap/sandbox` | SANDBOX: the visitor types the stop, the prints and the exit, plus an optional typed example. It uses `engine/structural_gap.tag_stop_exits` unchanged. |
| Rule decay | `GET /api/decay/{tid}`, `POST /api/decay/{tid}/{rule_id}/check` | For ARMED/PENDING rules. Real "since arming" = 0 trades, so UNDERPOWERED. The REPLAY treats the last 40% as post-arming (labelled: it overlaps the court's evidence). It shows the cumulative effect curve, 3 parts and `decay.cap_decay_check`. On RETIRE it calls `Rulebook.propose_retirement` (logged to the public record); confirming stays the owner's click. |
| Intent sandbox (R10) | `POST /api/intent/stamp`, `POST /api/intent/resolve`, `GET /api/intent`, `GET /api/intent/metrics/{tid}` | Per-session (X-Session), hash-chained with `engine/record.py`'s canonical + entry_hash, server time, SIM_PAPER. The outcome is appended once and never rewritten. Process/outcome grid; calibration (Brier and bins) only at 30 or more resolved, otherwise "N still needed". Imported histories: REFUSED with the reason. |
| Report export (R12) | `GET /api/report/{tid}.md`, `GET /api/report/{tid}.html[?download=1]`, `POST /api/report/verify` | The same `report.build` sections (number-locked). The HTML is self-contained (inline CSS, no scripts or URLs, CSP `default-src 'none'`). If `LOOP_SIGNING_KEY` is set, the last line is `<!-- loop-signature v1 hmac-sha256 key:<id> sig:<hex> -->`. Verify answers VERIFIED / ALTERED / UNSIGNED / KEY_UNAVAILABLE / OTHER_KEY. Called a signature, not zero-knowledge. |
| Share card (M23) | `GET /api/share/{tid}.svg` | 1200x630, off-white feTurbulence grain, one yellow-green accent (#b9d531). It shows the finding, the priced rule (whole history and unseen trades) and the court verdict, all from the review dict, plus the provenance and label. Copy link / Download SVG. |

## Limits (honest)

- Trend: on the demo wallets A and B the reference period has too few habit trips, so the answer is UNDERPOWERED. The shuffle-calibrated limit assumes exchangeable trips. Streaky trades make alarms more likely, so the UI says an alarm means "look here" and a change is claimed only when the interval excludes 1. The planted trader F raises a size alarm while the test finds no change. That is shown as is.
- Decay on demo data is a replay over trades the court also saw. It shows the mechanism, not an independent test.
- Ledger drift on the demo: no fills overlap the ccxt rows, so trade pnl and fees are 0 (stated). The -1.5 residual is reported, not explained. A withdrawal fee outside `amount` is a plausible cause, but it is not asserted.
- Replay: no offline candles exist for Hyperliquid symbols, so there is no price chart and no MAE/MFE.
- Intent sandbox, rulebook and decay state are in memory per session and reset on restart.
- HMAC verification needs the same server key. A third party cannot verify it without trusting this server.
- Calibration bins are 20-point bands; the Brier score is compared with always stating your own win rate.
- Tests: `tests/test_judge.py::test_losses_says_the_uncomfortable_parts` already failed before this work (LOSSES.md wording) and is untouched.
