# What we got wrong

Every number below is copied from a results file in this repo; the file is named next to it. Nothing here is rounded in our favour.

## The rule court: measured false admission and power

Source: court_results.json, written by `python scripts/measure_court.py` (300 simulated traders per cell, 300 permutations, 4 proposals in the trial ledger, per-rule threshold 0.0125, walk-forward court with block permutation and the serial-dependence guard of VALIDATION 4b). All traders are planted (simulated), and their returns are independent draws: these cells say nothing about serially dependent data (see the next section).

- **No leak at all:** the court accepted the cap rule for 0.0% (95% interval 0.0% to 1.3%) at 60 trips, 0.3% (95% interval 0.1% to 1.9%) at 150 trips, 0.3% (95% interval 0.1% to 1.9%) at 300 trips and 1.3% (95% interval 0.5% to 3.4%) at 600 trips. The nominal bar is 1.25%; on independent data the estimates sit at or just above it at 600 trips and the interval is wide enough that we do not claim better.
- **A habit that costs nothing extra** (sizes up 3x after a loss, no worse results): accepted 0.7% (95% interval 0.2% to 2.4%) at 150 trips, 1.0% (95% interval 0.3% to 2.9%) at 300 trips and 1.0% (95% interval 0.3% to 2.9%) at 600 trips.
- **A real costly leak:** accepted 1.0% (95% interval 0.3% to 2.9%) at 60 trips, 18.7% (95% interval 14.7% to 23.5%) at 150 trips, 54.7% (95% interval 49.0% to 60.2%) at 300 trips and 92.0% (95% interval 88.4% to 94.6%) at 600 trips. Power is low on short histories, which is why "not enough trades yet" is the normal answer at 40 to 80 trades.
- The earlier single-split court (SELFTEST_RESULTS.md) had much lower power (about 10% at 300 and 28% at 600) and a 3% false-admission cell; the walk-forward court and a fairer baseline (the trader's usual size, not inflated by the habit) improved it. SUITE_RESULTS.md (written by a separate agent) measures the halt rule and decay checks and reports weaker cells; read it too.
- **Serially dependent and drifting data (the court's first version failed here).** Before the fix the court wrongly accepted a rule for a trader with no size habit 49.0% of the time when returns were autocorrelated (AR(1), rho 0.6) and 92.7% of the time when drift, a regime shift, autocorrelation and fat tails were combined, and the family-wise habit-flag rate under all four was 9.3%. The cause: a cap after a loss really does help when losses cluster, so "the cap helps" is true without the size habit the rule names, and single-label shuffling ignored the dependence. Block permutation, a rolling usual-size baseline and a minimum-evidence guard (stated in the verdict reason) now bring those cells down; after the fix the same two cells read {{robustness.ac_court}} (autocorrelated returns) and {{robustness.all_court}} (all four stresses together), and the highest court wrong acceptance under any single stress is {{robustness.worst_court}}; the tables, the diagnosis and what the guard costs in power are in VALIDATION 4b, read from robustness_results.json and robustness_results_before.json. The full text is served at /validation. Independent-data guarantees above are unchanged in kind but remeasured on the new code.

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
- The demo histories are {{wallets.text}}, plus one simulated trader (F). The hosted build also enables wallet H, a real Bitget journal of 53 verified trades (below the 150 where tests have decent power).
- No forward (live or paper) record yet: the evidence is replay on past fills.
