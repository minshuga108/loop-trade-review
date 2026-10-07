# Submission text (paste into the form; every number must be re-checked against the file named beside it before sending)

## Form fields

- **Competition Track:** AI Trading Desk
- **Competition Sub-theme (free text, type exactly):** Review & Self-Evolution
- **Project Name:** Loop *(working name; change before sending)*
- **One-line Project Summary (140 characters max):** Your Bitget fills in. Your costly habits priced in dollars, court-tested on your own trades, armed as rules before your next order.
  *(131 characters, computed by claims.py)*

## Project Description (five parts; judges weigh the first three most)

### 1. Thesis
Journals die because they are manual, their "leak" numbers are assumed, and nobody tests whether a new rule would have worked on trades it was not built from. Loop is a review desk for traders of Bitget's tokenized US stocks and stock perps. It reads a trader's own fills, prices each costly habit in dollars from measured results, and sends every proposed rule to a court that judges it only on later trades, counts every rule tried, and says "not enough trades yet" when that is the honest answer. A rule that passes becomes part of a versioned rulebook after one click, feeds a checklist whose effect is measured, and guards the next order idea. We built the review loop because Bitget asks how AI can help a trader "review and iterate their research framework": the framework must change because of evidence, and be able to say when it has none.

### 2. Target user and product value
Retail and pro discretionary traders of stock perps and rTokens on Bitget: roughly 20 to 200 trades a month, accounts of about $5k to $200k, who already export their fills and have no time to review them. Existing journals fail them in three ways: manual entry, assumed costs, and no test of whether a rule works on their own fills. Loop imports the export (or a read-only key), finds habits that survive a within-trader test, shows what they cost, and keeps the trader in control: nothing is armed without a click, and nothing places an order.

### 3. Validation data and key metrics (label: observed / estimated / targeted)
- **Observed** (computed, reproducible): on 300 simulated traders per cell the walk-forward court wrongly accepted a rule for a trader with no leak 1% of the time at 600 trips (a trip is a completed round-trip trade; the bar is about 1%) on independent simulated data. On serially dependent or drifting data, an earlier version of the court wrongly accepted 49.0% under autocorrelated returns and 92.7% under all four stresses, while the current court does so 0.0% and 0.3% of the time (VALIDATION.md section 4b). The court also caught a real costly leak 19% / 55% / 92% of the time at 150 / 300 / 600 trips (`court_results.json`, `scripts/measure_court.py`); a look-ahead cheat is rejected in 100 of 100 planted runs (SUITE_RESULTS.md); the chat intent router scored 118 of 120 on a blind set written by its own author (eval/RESULTS.md, optimistic) and 146 of 200 (73.0%) on a set written by a different author (eval/INDEPENDENT_RESULTS.md); after fixing its misses it scored 165 of 200 (82.5%) on a second independent set the first time it was scored (our honest estimate; eval/INDEPENDENT_2_RESULTS.md). We then added Chinese patterns for that set's misses and it re-scored 175 of 200 (87.5%), but that set is now tuned on and no longer blind, so we do not quote the higher number as an estimate; first byte 1.18 s and first-screen weight 184 KB across 10 assets from `scripts/cold_visit.py` against the live deploy (budget <= 1.5 s and < 1 MB); 1207 automated tests collected by pytest at render time (`python -m pytest -q`; `scripts/render_docs.py --check` recounts them).
- **Observed on real wallets:** 5 public Hyperliquid wallets plus 1 Bitget futures export (a trading bot's account, not a human trader) reviewed. On the 6 real wallets the court accepted at least one rule on 1 (wallet D had 2 of 4 proposed rules accepted: cap at 1.0x median after a loss (held-out effect +$7,498), cap at 1.5x median after a loss (held-out effect +$6,303)) and accepted none on the other 5; the remaining proposals were rejected or underpowered. Rejections and underpowered results are shown, not hidden.
- **Observed with users:** targeted, not yet observed (5 non-team testers with 5 fixed tasks targeted in post-submission validation; no simulated or mock metrics recorded).
- **Targeted, not observed:** Activation = first finding within 60 seconds of opening the page; Retention = a second weekly review opened. Trading volume, AUM and incremental fee are not applicable to a read-only review tool; Risk: read-only, no write scope, paper only.
- **Not yet validated:** a real Bitget trader's history end to end (importers are tested on real Bitget rows from other accounts).

### 4. Progress
Built and tested: the ledger and importers (Bitget UTA v3 API, Bitget website CSV, public wallets), 7 habit tests (plus fee drag and the required win rate), dollar pricing, the walk-forward rule court with a trial-count ledger and a look-ahead guard, the rulebook (versions, hash-chained log, human approval), a measured checklist, the Rule Gate with a live Bitget order-book cost line, the weekly 复盘 report, chat in English and Chinese with a number lock, a public append-only record anchored with OpenTimestamps, a judge cockpit, a selftest page, and an MCP server with 6 read-only tools. Bitget tools actually used: public market endpoints (instruments, order book, tickers, market states) for the cost line, the UTA v3 history schema for importers, and bitget-signal technical-analysis (the skill's own indicator code run locally on Bitget public candles) answered 28 of 28 logged calls on 8 symbols; its hosted data skills (sentiment, news, macro) answered 0 of 19 logged data calls (evidence/bitget_calls.jsonl, /evidence); Agent Hub funding-rate history calls also answered (see /evidence). Models: Qwen (qwen3.8-max) only to classify unclear questions when a key is present; no model computes a number or decides. The demo also includes wallet G, a real Bitget futures export from a trading bot (not a human trader), and an Import panel where a visitor can load their own Bitget CSV for the session (not stored). Not built / next: a real human Bitget trader's history in the demo, scheduled weekly push (Telegram, Feishu, WeChat Work), signed report exports, user accounts, a forward paper record graded on outcomes.
Problems hit: the first demo story ("loss-chasing wallet") did not survive a stricter unit of analysis, so the demo uses the wallet that passes the test and says so; Bitget's MCP data calls returned 503 on 2026-10-05, so nothing depends on them.

### 5. Your take on AI trading (optional)
AI is most useful in trading as an auditor that cannot flatter you: it should compute, test and refuse, and let the human decide. The most valuable thing a review tool can say is "this rule did not hold up on trades it never saw".

## Role of the LLM / AI in your project
Qwen (model `qwen3.8-max`, via Alibaba Cloud DashScope / hackathon base URL): used only for optional NL question remapping, on questions the typed parser cannot place. The hosted deployment has a key configured (the status strip shows "Qwen: on", daily cap 400 calls, 1.5 s deadline); if the model is slow, over its cap or unreachable, the deterministic template path answers instead. It never writes numbers into an answer and never decides anything: every number comes from computed facts and is checked before it is shown. Everything else (habit detection, pricing, the court, the rulebook, the gate, the report) is deterministic code. The router is tested on a blind English and Chinese question set; every number in an answer is checked against a computed fact before it is shown.

## Submission Material Links (one per line, labelled)
- Demo (no login): `https://loop-trade-review.onrender.com`
- Project repo (public, complete README): `https://github.com/minshuga108/loop-trade-review`
- Run record: research-task walkthrough (3 minutes or less): `https://loop-trade-review.onrender.com/video`
- Judge cockpit: `https://loop-trade-review.onrender.com/cockpit`
- Public forward record and verification: `https://loop-trade-review.onrender.com/record`
- What we got wrong: `https://github.com/minshuga108/loop-trade-review/blob/main/LOSSES.md`
- Self-assessment: `https://github.com/minshuga108/loop-trade-review/blob/main/SELF_ASSESSMENT.md`
- Independent validation (cross-checks against scipy, statsmodels and arch, planted-bias power table, PBO; 13 of 13 p-values agree, 24 of 24 court verdicts reproduced): `https://github.com/minshuga108/loop-trade-review/blob/main/VALIDATION.md`

## X post (owner posts; must include #BitgetHackathon and @Bitget_AI and quote https://x.com/Bitget_AI/status/2100519318824055159)
> Loop: a trade-review desk for Bitget stock perps and rTokens. It prices your costly habits in dollars, then tests every proposed rule on trades it never saw, counts every rule it tried, and says "not enough trades yet" when that is the truth. Paper only, read only, no keys. 🧪
> Demo (no login): `https://loop-trade-review.onrender.com` · 3-min walkthrough: `https://loop-trade-review.onrender.com/video`
> #BitgetHackathon @Bitget_AI
> (quote-post the announcement above)

## Checklist before pressing submit
Team lead Bitget UID entered; sub-theme typed exactly "Review & Self-Evolution"; all links open logged out in a clean browser; the X post is public and quotes the announcement; every number above re-checked; K3 credits / Demo Day / Playbook interest boxes answered; S1 participation answered truthfully.
