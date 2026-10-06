# What we got wrong

Every number below is copied from a results file in this repo; the file is named next to it. Nothing here is rounded in our favour.

## The rule court: measured false admission and power

Source: court_results.json, written by `python scripts/measure_court.py` (100 simulated traders per cell, 300 permutations, 4 proposals in the trial ledger, per-rule threshold 0.0125, walk-forward court). All traders are planted (simulated).

- **No leak at all:** the court accepted the cap rule for 0% (95% interval 0.0% to 3.7%) at 60 trips, 1% (95% interval 0.2% to 5.4%) at 150, 1% (95% interval 0.2% to 5.4%) at 300 and 1% (95% interval 0.2% to 5.4%) at 600. The nominal bar is 1.25%; the estimates are near it but each cell has only 100 traders, so they are noisy.
- **A habit that costs nothing extra** (sizes up 3x after a loss, no worse results): accepted 0% (95% interval 0.0% to 3.7%) at 300 trips and 3% (95% interval 1.0% to 8.5%) at 600. The 600-trip figure is above the 1.25% bar, and we do not claim otherwise.
- **A real costly leak:** accepted 1% (95% interval 0.2% to 5.4%) at 60 trips, 19% (95% interval 12.5% to 27.8%) at 150, 53% (95% interval 43.3% to 62.5%) at 300 and 88% (95% interval 80.2% to 93.0%) at 600. Power is low on short histories, which is why "not enough trades yet" is the normal answer at 40 to 80 trades.
- The earlier single-split court (SELFTEST_RESULTS.md) had much lower power (about 10% at 300 and 28% at 600) and a 3% false-admission cell; the walk-forward court and a fairer baseline (the trader's usual size, not inflated by the habit) improved it. SUITE_RESULTS.md (written by a separate agent) measures the halt rule and decay checks and reports weaker cells; read it too.

## The chat router: 98% on its author's set, 73% on an independent set

Sources: eval/RESULTS.md (author-written blind set, 118/120 = 98.3%) and eval/INDEPENDENT_RESULTS.md (a different author, 200 lines written before reading the router, scored once: **146/200 = 73.0%, 95% interval 66.5 to 78.7**).

- The honest estimate of how well the chat understands a stranger is the **lower** number. The author-written set shares vocabulary with the router.
- On the independent set: English 70.9%, Chinese 75.6%, follow-ups 95.5%, adversarial lines 68.8%. Most misses were paraphrases that fell to "help" (31), "should I buy" and execution lines routed to the order check (8), a Chinese injection that was obeyed, and Hinglish.
- Loop has no order path, so a misroute gives a wrong answer, never a trade. The chat also refuses advice and "do it now" requests before routing.
- We then improved the router using those misses (so that set is now training-contaminated: its 200/200 after the fixes means nothing). A **second independent author** then wrote 200 fresh questions without reading the repo, and the improved router scored **165/200 = 82.5% (95% interval 76.6 to 87.1)** the first time it was scored (eval/INDEPENDENT_2_RESULTS.md; English 83.8%, Chinese 81.1%, adversarial lines 71.9%, follow-ups 78.3%). **82.5% is our honest estimate** for the template-only chat. The remaining misses are paraphrases of 'which wallet', 'is this real', 'the rules list', Cantonese-style Chinese, and eight 'should I...' lines still routed to the order check (nothing can execute). After that we added targeted Chinese patterns for this set's misses and it re-scored 175/200 = 87.5%; that set is now tuned on, no longer blind, and 87.5% is not an estimate of performance on new questions.

## Our own selftest scored far below the blind set

Source: eval/selftest_first_run.json (frozen first run of eval/selftest_prompts.jsonl; the /selftest page reads it and shows every miss).

The 24 selftest sentences were written later, by a different agent, in plainer trader language. The frozen first run is shown on /selftest with its pass count, misses and timings, read from that file. It is much lower than the blind score above, it includes an injection sentence and a "place it for me" sentence that the router sent to the order check instead of the refusal, and chat answers took seconds, not the sub-second we want. Those prompts were also written by someone who had read the router's code, so even that run is not blind.

## What is still missing

- No test users yet: no observed task-completion or time-to-first-insight numbers from people outside the team.
- The demo histories are 5 public Hyperliquid wallets, one simulated trader and one real Bitget export (wallet G, a trading bot's account, not a human trader).
- No forward (live or paper) record yet: the evidence is replay on past fills.
