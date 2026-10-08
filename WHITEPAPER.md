# Loop: a trade review desk that tests its own rules

*Whitepaper. Rendered from `WHITEPAPER.template.md` by `scripts/render_docs.py`. Every number in this document is filled in from `claims.py`, which reads a results file or the running code; none is typed by hand, and `scripts/render_docs.py --check` fails when a number drifts.*

Live demo, no login and no key: https://loop-trade-review.onrender.com. Code: https://github.com/minshuga108/loop-trade-review.

## Abstract

Loop is a review desk for traders of Bitget's tokenized US stocks and stock perpetual futures. It reads a trader's own fills, groups them into round trips with fees included, tests 7 behavioural habits against that same trader's own history, and prices each costly habit in dollars. It then sends every proposed rule to a walk-forward court that judges the rule only on trades the rule was not built from, counts every rule tried, and answers "not enough trades yet" when that is the honest answer. A rule that passes waits for one human click before it joins a versioned, hash-chained rulebook. Armed rules and a short checklist then guard the next order idea through a Rule Gate that adds a live Bitget order-book cost line. Loop never places, previews or routes an order, and accepts no exchange keys.

The part we most want a reader to weigh is the evidence, and the evidence includes our failures. Our first court wrongly accepted a rule for a trader with no size habit 49.0% of the time when returns were autocorrelated, and 92.7% of the time under four stresses combined. After the fix the same two cells read 0.0% and 0.3%. Our statistics agree with independent code on 13 of 13 permutation p-values, 19 of 19 Holm adjustments and 24 of 24 court verdicts. On the real wallets in the demo the court accepted a rule on one wallet, and our own overfitting checks did not confirm it. There has been no real-user testing yet. This paper reports all of it.

## The problem

Most traders do not review their trades. A journal asks for manual entry of every trade and a written reason, and the people with the least time to review are the ones who most need it. Three further problems sit behind the missing habit of review.

**Habits cost real dollars, but the cost is usually assumed.** "Revenge trading costs you a lot" is a rule of thumb. The honest question is narrower: on this trader's own fills, what would the net result have been if opening size after a loss had been capped at the trader's usual size? That has an answer in dollars, with a range, and it can be computed from the fills.

**Pooling hides the truth.** A habit can look strong when many traders are thrown into one pile and disappear when each trader is compared only with themselves. We measured this ourselves on 60 public wallets: the pooled signal for bigger size after a loss had p = 0.0005, and the within-trader version had p = 0.51. A tool that pools will report a habit that most individuals do not have.

**Rules fail out of sample.** A rule found on the same trades that suggested it will usually look good by luck. Try enough rules and one always works on the past. Almost nobody checks whether a proposed fix would have helped on trades it did not come from, and almost nobody counts how many fixes were tried before one passed.

Loop is built around those three problems. It tests within the trader, prices in dollars, and refuses to arm a rule that has not earned it on unseen trades.

## Design principles

**Code does the maths; the language layer only reads the question.** Every statistic, price and verdict is computed by deterministic code over the trader's own trades. The chat accepts a question in English or Chinese and turns it into a strict structured query. An optional language model (Qwen) is consulted only for a question the deterministic parser cannot place. It may return a query that is validated against the same closed schema, or "not a data question". It never sees a number from the record, never writes a number and never decides anything. In the hosted build it is switched on with a deadline of 1.5 seconds per call and a daily cap of 400 calls across all visitors. Past the deadline or the cap, the deterministic path answers.

**Every number is locked and receipted.** Before an answer is shown, every numeral in the sentence is checked against the set of numbers the engine computed for that answer, at the precision shown. A sentence containing a number the engine did not compute is refused and replaced by a plain template. Under each answer a receipt lists the sources, the computation, the rows used out of the total, the lock result and a trace of the engine steps, including whether a template or the model phrased the sentence.

**Provenance labels on everything.** Every data set and answer carries one of six labels: real own fills, real public platform data, replay of a recorded order book, paper decisions, a counterfactual computed by Loop, or a planted self-test fixture. Anything simulated can never be shown as a person and never calibrates anything.

**A human approves every change.** A rule the court accepts is only a candidate. It is armed, retired or reverted only with a recorded human approval, and each change is appended to a hash-chained log.

**Paper and read-only.** The service has no write path to any exchange. It accepts no keys. Its health endpoint reports read-only mode, and the MCP server exposes 6 tools, all marked read-only, none of which can arm or retire a rule or place an order.

**Say "not enough" when that is true.** UNDERPOWERED is a first-class verdict next to FLAGGED, SUGGESTIVE and NOT_FLAGGED for habits, and next to ACCEPTED and REJECTED for rules. Loop only names timing and size patterns. It does not claim to know a trader's emotion or intent.

## Method

The pipeline in one line: fills, orders, round trips, habit tests, dollar pricing, rule court, human approval, rulebook, checklist, Rule Gate, public record, then weekly report, chat and MCP on top.

### Import and round trips

Loop reads Bitget UTA v3 history in JSON, the Bitget website CSV export of futures order history, and Hyperliquid fills CSV. The layout is detected from the header and anything else is refused with a plain message rather than guessed. A visitor's file is parsed in memory for that session only and is not stored. Fills become orders and orders become round trips, flat to flat on one symbol, with fees included. A trip that begins mid-position because the history window was cut is skipped, never guessed. De-duplication is idempotent, independent of order and safe against replayed fills, and property tests check this.

### The habit tests

Each test compares the trader with themselves, never with other people. A result is FLAGGED only when it clears a minimum sample, an effect-size floor and a within-trader permutation p-value. The tests are:

- size after a loss, measured against the trader's own trailing usual size (the median of the previous trades that did not follow a loss);
- hold asymmetry, whether losers are held longer than winners;
- overtrading days, whether heavy days do worse per trip;
- revenge re-entry, whether quick re-entries after a loss do worse;
- chasing a large prior move, with two price sources, Bitget candles or the trader's own fill prices;
- off-hours trading, outside US regular hours, which matters for stock perps and rTokens;
- averaging down, tested on profit before fees, because an add trades more size and pays more fee whatever the decision.

Fee drag and the required (breakeven) win rate are reported as descriptive measures with intervals. The family of tests is corrected with the Holm procedure. Before every test, per-trip returns are checked for serial dependence with a Ljung-Box test at the `1%` level. When dependence is found, labels are permuted in contiguous blocks with a block length chosen from the data, and otherwise the ordinary permutation is kept, so independent data is untouched.

### Dollar pricing

The costly habit is priced by replaying the trader's own trips with the rule applied: what would the net result have been if opening size after a loss had been capped at a stated multiple of the trader's usual size? The counterfactual uses only what was known when the trip opened, which is the outcome of the previous closed trip, and scales profit linearly with size, which is conservative for a cap. The result is shown as a dollar effect with a range, once over all history and once on held-out trades.

### The rule court

The history is cut into consecutive chunks in time order. For each chunk, the rule's baseline uses only earlier chunks, as a rolling window of recent trips, and the rule is judged on that chunk. The pooled out-of-sample effect is compared with a block-permutation null. A rule is accepted only when its out-of-sample effect is positive and its p-value is below the trial-adjusted threshold: `0.05` divided by the number of proposals. The demo proposes caps at several multiples of the usual size, so the trial ledger holds 4 proposals and the per-rule threshold is 0.0125. Every proposal, including those that fail, is counted, so fishing for a pass gets harder with each attempt.

Two guards sit on top of the statistics. The first is a dependence guard: when serial dependence is detected, the affected-trip count is discounted by the effective sample size and a gain is accepted only if the trader's sizes also show the size-up habit. The verdict reason says so in words. The second is a structural look-ahead guard. Every feature a rule may use is registered with a tag that says when it becomes known, an audit checks the tags, and a rule that peeks at its own trade's outcome or a later one is refused whatever its statistics say. We built it structurally because a statistical test alone can be fooled by a leaky rule.

A decay check watches armed rules after the fact, using only trades since arming, with thresholds fixed in advance. It proposes retirement and the owner decides.

### Rulebook, checklist and Rule Gate

A rule moves from ACCEPTED (court passed, waiting for the owner) to ARMED (owner clicked), then to PENDING_RETIREMENT and RETIRED. Court rejections are QUARANTINED with the reason. Every transition is appended to a hash-chained log in which each entry stores the hash of the one before it, so an edit to any earlier entry is visible.

The checklist is generated from the trader's own flagged habits and armed rules. Each item's effect is measured: trips that broke the item against trips that kept it, with a within-trader permutation, and only when both groups are large enough. Zero-effect items are shown as zero-effect.

The Rule Gate takes an order idea typed as text. The parser reads side, symbol and size only. The text is never echoed back or followed as an instruction. The gate checks the idea against armed rules and the checklist and returns one of CHECKS_PASSED, CHECKS_PASSED_WITH_NOTES, REVIEW_NEEDED or BLOCKED_BY_YOUR_RULES. Its cost line walks the live Bitget order book for the stated size, includes the taker fee, reads the instrument's minimum order, tick and step, and reports the cost against a limit. A background thread refreshes the books. The request path never calls Bitget, and if the cache is stale the card says so instead of inventing a cost. The gate never places, previews or routes an order.

### Public record, thesis card, weekly report

Gate decisions and rule events are written to an append-only public record. Each line holds the SHA-256 hash of its own content and of the line before it. A daily Merkle root over the day's hashes is anchored through OpenTimestamps. An anchor proves that the day's root existed before the Bitcoin block that includes it. It does not prove that every decision was logged, or that any decision was good.

The thesis card is a short bilingual summary of what the evidence says about one trader, assembled only from computed facts, with a SHA-256 hash over those facts and the date. Freezing it writes one entry to the record and arms nothing. Freezing again creates a new version and shows what changed in the evidence.

The weekly report follows the Chinese review ritual of what happened, why, and what to do tomorrow, in English or in 中文. It adds the priority finding, what would make it wrong, what the court did and what changed since the last review. Numbers are filled from the facts payload and checked by the number-lock. It exports as Markdown, printable HTML and a share card.

### Chat in English and 中文

A question passes through safety checks first: injection phrases, requests to place or close an order or move funds, and buy or sell advice are refused before any scoring. A deterministic router then picks an intent. Questions about the trader's data are parsed into a typed query over a closed set of metrics, executed by code, and rendered with the number-lock and a receipt. Follow-ups reuse the previous query. Ambiguity gets one clarifying question. Things the record cannot answer, such as price paths, advice or open positions, are refused with the reason and a list of what it can answer.

## Evidence

Passing our own planted traders proves that the machinery recovers what we put in. It does not prove that real traders behave like our generator. We say that wherever a planted result appears, and we separate evidence about the machinery from evidence about people.

### Independent cross-checks

Tolerances were fixed in the script before the first run. Our permutation p-values agree with `scipy` on 13 of 13, our shipped Holm adjustments agree with `statsmodels` on 19 of 19 (and on random p-vectors the largest difference is 0e+00), and our court verdicts agree with a re-implementation written from the documented rule on 24 of 24. Bootstrap intervals agree with `scipy` on 12 of 13; the one miss is explained in the section on where we lost. Our dependent-data intervals, checked against `arch`, are 0.89x to 1.03x as wide as the independent-data ones. Reference tool versions: scipy 1.18.1, statsmodels 0.15.0, arch 8.0.0, hypothesis 6.168.5.

| Quantity | Reference implementation | Compared | Agree | Tolerance (declared before running) |
|---|---|---|---|---|
| Detector p-values (permutation) | scipy.stats.permutation_test, 40,000 resamples | 13 | 13 | 3 combined Monte-Carlo SE + 1e-4 |
| Detector 95% CIs (bootstrap) | scipy.stats.bootstrap, 9,999 resamples | 13 | 12 | endpoints within 10% of the reference CI width |
| UNDERPOWERED gating | independent group counts | 5 | 5 | same decision |
| Holm adjusted p (shipped, per trader) | statsmodels multipletests(holm) | 19 | 19 | 5e-4 (max observed 5.6e-17) |
| Holm on random p-vectors | statsmodels multipletests(holm) | 3,000 | 3,000 | 1e-12 (max observed 0.0e+00) |
| Court walk-forward verdicts (effect, p, status) | our re-implementation from the docs, 100,000 permutations | 24 | 24 | effect within $0.01; p within 3 combined SE |
| After-loss labels | independent searchsorted implementation | 6 traders | 6 | identical arrays |
| All-history CI of the 1.5x rule | arch IIDBootstrap, 5,000 resamples | 6 | 6 | endpoints within 10% of width |

Hypothesis property tests (9 of them) check that round trips conserve net profit, that de-duplication is idempotent, that an after-loss label never depends on later trades, that the court's cap for the last chunk does not change when that chunk's own trades are rewritten, and that Holm adjustments are bounded, monotone and equal to `statsmodels`. The whole suite currently holds 1255 automated tests.

### Planted-bias power tables

We simulate traders with a known habit, or none, and count what the court and the detectors do. Each cell is 300 simulated traders; intervals are Wilson 95% intervals. All returns here are independent draws, so these cells say nothing about serially dependent data. That is the next section.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No leak: court wrongly accepts | 0.0% (0.0% to 1.3%) | 0.3% (0.1% to 1.9%) | 0.3% (0.1% to 1.9%) | 1.3% (0.5% to 3.4%) |
| Costless habit: court wrongly accepts | 0.0% (0.0% to 1.3%) | 0.7% (0.2% to 2.4%) | 1.0% (0.3% to 2.9%) | 1.0% (0.3% to 2.9%) |
| Costly leak: court correctly accepts (power) | 1.0% (0.3% to 2.9%) | 18.7% (14.7% to 23.5%) | 54.7% (49.0% to 60.2%) | 92.0% (88.4% to 94.6%) |

On a trader with no leak the court wrongly accepted 1.3% at the longest history, just above the nominal bar of its per-rule threshold, and the interval is wide enough that we do not claim better. A habit that costs nothing extra is wrongly accepted 1% at the longest history. A real costly leak is accepted 18.7% at the shorter history, 54.7% at the middle one and 92% at the longest. Power is low on short histories, which is why "not enough trades yet" is the normal answer at a few dozen trades.

For the size-after-loss detector, a planted three-times size-up is flagged 100% of the time and a one-and-a-half-times size-up 100% of the time at the middle history. A trader with no size habit is false-flagged 0% of the time. A small habit is often invisible: a planted size-up of one quarter is flagged only 46% of the time. That is why the product says "underpowered" rather than "clean".

The three newer detectors were measured the same way. On a planted costly habit, the chase detector flags 100% with Bitget candles as the price source and 46% with the trader's own fill prices as the series, off-hours trading flags 99% and averaging down flags 100%.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No size habit (false flag) | 4% [2%, 10%] | 1% [0%, 5%] | 0% [0%, 4%] | 0% [0%, 4%] |
| Sizes up 1.25x after a loss (power) | 38% [29%, 48%] | 48% [38%, 58%] | 46% [37%, 56%] | 51% [41%, 61%] |
| Sizes up 1.5x after a loss (power) | 91% [84%, 95%] | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |
| Sizes up 2x after a loss (power) | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |
| Sizes up 3x after a loss (power) | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |

### Stress tests: where the court failed, and the fix

In the stress suite every simulated trader has no size habit, so every flag and every accepted rule is a wrong one. We apply persistent size drift, a regime shift, autocorrelated returns, fat tails, and all four together. The first version of the court shuffled single labels as if trips were independent. Under autocorrelated returns it wrongly accepted a rule 49.0% of the time, and under all four stresses 92.7% of the time. The family-wise false-flag rate under all four stresses was 9.3%, and 3 cells had an interval wholly above five percent.

The cause was not a coding slip. When losses cluster, a cap after a loss really does save money, so "the cap helps" is true without the size habit the rule names. Single-label shuffling also understated how much a gap varies under clustering, and drifting sizes looked like a habit. The fix has four parts: block permutation when dependence is detected, a trailing usual-size baseline instead of a global one, a rolling baseline in the court, and a minimum-evidence guard stated in the verdict reason. Averaging down is now tested before fees.

After the fix, with the same generator, seeds and number of traders per cell, the court's wrong acceptance is 0.0% under autocorrelated returns and 0.3% under all four stresses. The highest court wrong acceptance under any single stress is 1.0% under size drift, and the highest family-wise flag rate is 1.7% under size drift. Cells whose interval lies wholly above five percent: 0.

The fix has a price, which we measured. If returns are serially dependent, a rule is accepted only when the size habit is also visible in the trader's sizes. A planted real costly leak on top of autocorrelated returns at 600 trips is still accepted 100.0% (95% interval 96.3% to 100.0%).

After:

| Stress (truth: no size-up habit) | size after loss | hold asymmetry | overtrading | revenge re-entry | any, after Holm | court wrongly accepts |
|---|---|---|---|---|---|---|
| none (reference) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.3% [0.1%, 1.9%] |
| persistent size drift (about 4.5x over the history) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 1.0% [0.3%, 2.9%] |
| regime shift at the midpoint (3x size, 3x volatility) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.7% [0.2%, 2.4%] |
| autocorrelated returns (AR(1), rho 0.6) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] |
| fat tails (Student t, 2 degrees of freedom) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 1.0% [0.3%, 2.9%] |
| all four together | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.3% [0.1%, 1.9%] |

Before (first version, frozen):

| Stress (truth: no size-up habit) | size after loss | hold asymmetry | overtrading | revenge re-entry | any, after Holm | court wrongly accepts |
|---|---|---|---|---|---|---|
| none (reference) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.7% [0.2%, 2.4%] |
| persistent size drift (about 4.5x over the history) | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 2.0% [0.9%, 4.3%] | 1.0% [0.3%, 2.9%] |
| regime shift at the midpoint (3x size, 3x volatility) | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 3.3% [1.8%, 6.0%] | 0.3% [0.1%, 1.9%] |
| autocorrelated returns (AR(1), rho 0.6) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 3.3% [1.8%, 6.0%] | 0.0% [0.0%, 1.3%] | 3.3% [1.8%, 6.0%] | 49.0% [43.4%, 54.6%] |
| fat tails (Student t, 2 degrees of freedom) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 1.0% [0.3%, 2.9%] |
| all four together | 5.7% [3.6%, 8.9%] | 0.0% [0.0%, 1.3%] | 3.7% [2.1%, 6.4%] | 0.0% [0.0%, 1.3%] | 9.3% [6.5%, 13.2%] | 92.7% [89.1%, 95.1%] |

### The look-ahead guard

We planted three rules that peek at the future, plus one honest control. The guard refused each peeking rule in 100 of 100 histories. With the guard switched off, the statistics alone would have accepted the first rule in 100 of 100 histories and the second in 1 of 100. The honest control was refused in 0 of 100 and accepted in 48 of 100.

### The cohort study

To test the pooling problem on real data we ran a pre-registered study. The plan and the terms check were committed before any fills were fetched. We drew 60 public Hyperliquid wallets from a leaderboard snapshot of 47,438 rows (11,037 eligible), stratified by all-time profit, with a seeded shuffle: 459,230 fills and 18,412 round trips in all.

After correcting across wallets with the Benjamini-Hochberg procedure, a size-after-loss habit survived on 4 of 55 testable wallets, hold asymmetry on 2 of 54, overtrading days on 0 of 50 and revenge re-entry on 0 of 14. The pooled size-after-loss p-value was 0.0005 and the within-trader p-value was 0.51. The court judged 191 of 240 rule trials and accepted a rule on 1 of 60 wallets. If no wallet had a real leak, up to 2.4 acceptances would be expected by chance, so one acceptance is consistent with chance and we do not present it as a proven leak.

We do not claim that these habits are common, that any owner is emotional, or that the cohort represents Hyperliquid or Bitget users. The wallets are public, gave no consent and may be bots.

### Real wallets and wallet D

5 public Hyperliquid wallets plus 1 Bitget futures export (a trading bot's account, not a human trader), plus one simulated trader that is always labelled as simulated, and wallet H, described below. On the 6 real wallets the court accepted at least one rule on 1 (wallet D had 2 of 4 proposed rules accepted: cap at 1.0x median after a loss (held-out effect +$7,498), cap at 1.5x median after a loss (held-out effect +$6,303)) and accepted none on the other 5; the remaining proposals were rejected or underpowered.

Wallet D is the one case where the court accepted rules, and our other checks do not confirm it. wallet D is the one real wallet where the court accepted rules (1.0x (held-out $7,498), 1.5x (held-out $6,303)); the independent re-implementation reproduces both verdicts. But the same cap rules priced on ALL of D's history give $-1,964 at 1.5x with a 95% interval of [-10,059, 5,636] (it contains zero), the CSCV probability of backtest overfitting over D's four caps is 0.87, and the deflated Sharpe of the best cap is 0.36. The court's held-out effect leaves out the first part of the history by design, because that part sets the baseline, so a positive held-out figure next to a non-positive all-history figure is possible. We read it this way: the acceptance is real under the court's pre-declared test, it clears one multiple-testing safeguard and it fails to clear two other lenses. None of the real wallets reaches a deflated Sharpe of `0.95`. On planted traders the two lenses behave: a costly leak gives a PBO near 0.01 and a deflated Sharpe near 0.99, and a trader with no leak gives a PBO near 0.43 and a deflated Sharpe near 0.66.

| Wallet | Trips used | PBO | P(best rule loses OOS) | In-sample best cap | PSR(0) | DSR (4 trials) | Court accepted |
|---|---|---|---|---|---|---|---|
| A | 76 | 0.77 | 1.00 | 3.0x | n/a | n/a | 0 |
| B | 111 | 0.37 | 0.39 | 1.5x | 0.69 | 0.60 | 0 |
| C | 273 | 0.69 | 0.39 | 3.0x | 0.92 | 0.81 | 0 |
| D | 318 | 0.87 | 0.74 | 1.0x | 0.52 | 0.36 | 2 |
| E | 223 | 0.76 | 0.59 | 2.0x | 0.98 | 0.54 | 0 |
| G | 66 | 0.33 | 0.33 | 1.0x | 0.85 | 0.58 | 0 |

### The chat router

The router was scored on sets written by people other than its author, each scored once at first contact. On the author's own blind set it scored 118 of 120, which is optimistic because that set shares vocabulary with the router. On the first independent set, written by another person without reading the router, it scored 146 of 200 (73.0%). We then improved the router using those misses, which contaminated that set. A second independent author wrote fresh questions, and the improved router scored 165 of 200 (82.5%) the first time. After we added Chinese patterns for that set's misses it re-scored 175 of 200 (87.5%), but that set is no longer blind, so the later figure is not an estimate for new questions. The honest estimate is the first-contact score on the second set.

### Bitget tools

Public market endpoints feed the cost line and context. bitget-signal technical-analysis (the skill's own indicator code run locally on Bitget public candles) answered 28 of 28 logged calls on 8 symbols; its hosted data skills (sentiment, news, macro) answered 0 of 19 logged data calls (evidence/bitget_calls.jsonl, /evidence). Every call is logged and shown at `/evidence`. Nothing in the product depends on a source that failed.

## Where we lost

This section follows the repository's `LOSSES.md`, which is read from the results files and also served at `/wrong`. Nothing here is rounded in our favour.

### The rule court: false admission and power

Source: `court_results.json`, from `scripts/measure_court.py`, 300 simulated traders per cell, the 4-proposal ledger, per-rule threshold 0.0125, with block permutation and the dependence guard. All traders are planted and their returns independent.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No leak: court wrongly accepts | 0.0% (0.0% to 1.3%) | 0.3% (0.1% to 1.9%) | 0.3% (0.1% to 1.9%) | 1.3% (0.5% to 3.4%) |
| Costless habit: court wrongly accepts | 0.0% (0.0% to 1.3%) | 0.7% (0.2% to 2.4%) | 1.0% (0.3% to 2.9%) | 1.0% (0.3% to 2.9%) |
| Costly leak: court correctly accepts (power) | 1.0% (0.3% to 2.9%) | 18.7% (14.7% to 23.5%) | 54.7% (49.0% to 60.2%) | 92.0% (88.4% to 94.6%) |

- On a trader with no leak at all, the court wrongly accepted 1.3% at the longest history. The nominal bar is the per-rule threshold; on independent data the estimates sit at or just above it, and the interval is wide.
- A real costly leak was accepted only 18.7% of the time at the shorter history and 54.7% at the middle one. Power on short histories is low.
- The earlier single-split court had much lower power and a larger false-admission cell. The walk-forward court and a fairer baseline improved it. The separate planted-rule suite measures the halt rule and the decay check and reports weaker cells; its report lists its own failures cell by cell.
- The court's first version failed on serially dependent and drifting data: 49.0% and 92.7% wrong acceptance. After the fix the same two cells read 0.0% and 0.3%, and the highest wrong acceptance under any single stress is 1.0% under size drift. The full tables, the diagnosis and the cost in power are above and in the validation page at `/validation`.

### The chat router

- The author-written blind set scored 118 of 120, and the first independent set scored 146 of 200 (73.0%). The honest estimate of how the chat understands a stranger is the lower number.
- The first independent set was then used to improve the router, so it is contaminated. A second independent author scored 165 of 200 (82.5%) at first contact, and that figure is our honest estimate for the template-only chat. After tuning on that set's misses it re-scored 175 of 200 (87.5%), which is not an estimate of performance on new questions.
- Most misses were paraphrases that fell back to the help answer, "should I buy" and execution lines routed to the order check, a Chinese injection that was obeyed on the first set, and Hinglish. Loop has no order path, so a misroute gives a wrong answer, never a trade. The chat refuses advice and "do it now" requests before routing.

### Our own selftest

The selftest sentences were written later by a different agent in plainer trader language. Its frozen first run passed 13 of 24. It includes an injection sentence and a "place it for me" sentence that the router sent to the order check instead of the refusal, and chat answers took seconds, not the sub-second we want. Those prompts were written by someone who had read the router's code, so even that run is not blind.

### What is still missing, and known issues

- **No real-user testing yet.** Task completion and time to first insight are targeted, not yet observed. We have no numbers from people outside the team, and we record no simulated or mock metrics in their place.
- **The demo's real traders are not human Bitget traders.** The demo holds 5 public Hyperliquid wallets plus 1 Bitget futures export (a trading bot's account, not a human trader). Wallet G is a trading bot's account, and its export format omits opening fees, so its net results overstate. The public Hyperliquid wallets are on another venue, hand-picked and illustrative. Behaviour patterns are venue-independent; execution costs are not, which is why the cost line uses Bitget books only. Wallet H is a real Bitget futures journal of 53 verified trades, far below the number where the tests have decent power. It is used under its MPL-2.0 licence, and the author has not been contacted.
- **Some interface strings are untranslated in the 中文 view.** The starter chips, the lists on the "what we got wrong" page and the rows on the daily runs board remain in English. Chat answers, the gate, the cost line and the labels are in Chinese, in Simplified characters even when the question was in Traditional.
- **Averaging-down false flags.** The averaging-down detector flags a costless planted habit 5.5% of the time before the Holm step, the highest of the three newer detectors, and 1.0% after it.
- **The no-leak false admission is 1.3% at the longest history**, at or just above the nominal bar.
- **A small real habit is often invisible.** A planted size-up of one quarter is flagged only 46% of the time at the middle history.
- **Wallet D's accepted rules are not confirmed** by the all-history view, by a PBO of 0.87 or by a deflated Sharpe of 0.36.
- **One bootstrap interval endpoint is noisier than shown.** wallet A size_after_loss: our shipped CI is [0.776, 1.21] and scipy's is [0.757, 1.16]. Re-running our own procedure with 40 other seeds, 40% landed within tolerance (upper endpoint ranged 1.15 to 1.21), and with 20,000 draws our procedure gives [0.76, 1.2], matching scipy. The p-value is unaffected.
- **Serial dependence is handled at a price in power**, described above, and the stress list is ours.
- **The planted generator and the detectors share one author.** An outside generator is still needed. Court p-values were checked against our own re-implementation, because no library implements this within-chunk label permutation. Revenge re-entry and fee drag were not cross-checked.
- **Real wallets are bots and public wallets.** The cohort wallets are public, gave no consent, and may be bots. They carry survivorship and window limits, and come from one snapshot day.
- **Bitget's hosted data skills mostly did not answer.** The evidence page shows each call. Nothing in the product depends on the ones that failed, but the Bitget-native data count is thin.
- **No forward record graded on outcomes yet.** The public record logs decisions, but no resolver writes outcomes, so decisions stay pending.
- **The public record resets on redeploy** on the free host, whose disk is ephemeral. The runs board survives through a committed seed file; the live record does not, so anchors should be kept in the public repository.
- **Free-host sleep.** The free host sleeps when idle, so the first visit after a quiet period is slow. It runs one worker. The first screen falls back to a pre-rendered snapshot if the live server fails.
- **The first demo story did not survive a stricter unit of analysis.** A wallet that looked like a loss chaser stopped looking like one when we moved to round trips, so the demo uses the wallets that behave and says so.
- **Not built yet:** a live scheduled weekly push (it needs bot tokens), user accounts, signed exports in production (they need a server secret), and the stateless revision of the MCP protocol.

## Limits, and what Loop is not

Loop places no orders. It has no order path and no way to receive one, and its MCP server cannot arm a rule, retire a rule or place an order.

Loop gives no advice. It is not a signal service and not a trading bot. In chat it refuses buy and sell advice, price prediction and "place it for me" requests.

Loop does not promise profit. An accepted rule is a statement about past trades the rule was not built from. It says nothing certain about future ones. Nothing here shows that the habits we test for predict future losses for a real person. A flagged habit is a pattern in the data, not a judgement of the person, and Loop never claims to know why a trader did something.

Loop does not replace the trader's judgement. Nothing is armed without a click, and the evidence is shown with its uncertainty, including the cases where the honest answer is "not enough trades yet".

## How to try it

Open https://loop-trade-review.onrender.com. There is no login and no key. The first screen shows a demo wallet with its provenance label, one finding priced in dollars and the court's verdict. Pick a wallet, ask a question in the chat in English or 中文, open a receipt, and type an order idea into the Rule Gate to see the verdict and the live cost line. Simulated wallet F shows what an accepted rule and an arm click look like, and is always labelled simulated. You can import your own Bitget CSV or JSON export in-session; it is parsed in memory and not stored.

Other pages: `/wrong` (what we got wrong), `/validation` (the full validation page), `/proof`, `/cockpit`, `/selftest`, `/evidence`, `/record`, `/runs` and `/video`. The walkthrough video is at https://loop-trade-review.onrender.com/video.

## Reproducibility

Every number in this paper is produced by a script in the repository and read through `claims.py`. To rebuild them:

```
python scripts/measure_court.py          # court false admission and power -> court_results.json
python scripts/robustness_suite.py       # hostile-generator stresses -> robustness_results.json
python scripts/crosscheck_stats.py       # independent re-computation (dev tools)
python scripts/run_validation.py         # planted power, PBO, deflated Sharpe -> validation_results.json
python scripts/measure_detectors3.py     # the three newer detectors -> detectors3_results.json
python scripts/cohort_study.py           # the pre-registered cohort -> cohort_results.json
python -m pytest -q                      # the automated tests
python scripts/render_docs.py            # render this paper and the other docs
python scripts/render_docs.py --check    # fail if any document drifts from the numbers
```

Files: `claims.py` (every quoted number and its source), `court_results.json`, `robustness_results.json` and `robustness_results_before.json` (the frozen first version), `validation_results.json`, `detectors3_results.json`, `cohort_results.json`, `suite_results.json`, `eval/` (router and selftest sets and results), `LOSSES.md`, `VALIDATION.md` and `COHORT_RESULTS.md`. The engine is in `engine/`, the web app in `app/`, the importers in `adapters/`. The dependencies of the running service are pinned in `requirements.txt`; the cross-check tooling is in `requirements-dev.txt` and is not used by the app.
