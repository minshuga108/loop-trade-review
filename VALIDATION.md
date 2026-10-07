# Validation: do our numbers agree with independent code, and do our detectors find what we plant?

This page is rendered from `VALIDATION.template.md` by `scripts/render_docs.py`. Every number below is computed by `scripts/crosscheck_stats.py` or `scripts/run_validation.py`, stored in `validation_results.json`, and quoted through `claims.py`. The validation tooling is dev-only (`requirements-dev.txt`: scipy 1.18.1, statsmodels 0.15.0, arch 8.0.0, hypothesis 6.168.5); the app, `requirements.txt` and the Dockerfile do not use it, and the tests that need it skip when it is absent.

Honest scope: planted traders come from our own generator, so passing them proves the machinery recovers what we put in, not that real traders behave like the generator. The independent re-computations check our arithmetic and our permutation and bootstrap code against other people's code; they do not check that the habits we test for are the right ones.

## 1. Planted-bias protocol

1. **Generator** (`engine/planted.py`, provenance `SIM_PLANTED`, never shown as a person): each trip has a log-normal size, a normal return per unit of notional, a fee, and a hold time. A planted *size habit* multiplies the next trip's size after a loss by `size_mult`. A planted *costly leak* also lowers the mean return after a loss by `tilt` (`-0.006`). A *costless habit* has the size-up but no tilt. A *null trader* has neither.
2. **Court (rule judging).** For each scenario and trip count we simulate 300 traders, propose four caps (1.0x, 1.5x, 2x, 3x of the trader's usual size) so the ledger holds four trials, and judge the 1.5x cap with the walk-forward court (`scripts/measure_court.py`, results in `court_results.json`). "Accepted" on a null or costless trader is a wrong acceptance. This is on independent (non-serially-dependent) data: the planted generator draws every return independently. The stress results in section 4b (autocorrelated returns, drift, regime shifts, fat tails) are reported separately and are where an earlier version of the court failed. Wilson 95% intervals in brackets.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No leak (court wrongly accepts) | 0% [0%, 1%] | 0% [0%, 2%] | 0% [0%, 2%] | 1% [1%, 3%] |
| Costless habit, 3x size up (court wrongly accepts) | 0% [0%, 1%] | 1% [0%, 2%] | 1% [0%, 3%] | 1% [0%, 3%] |
| Costly leak (court correctly accepts = power) | 1% [0%, 3%] | 19% [15%, 23%] | 55% [49%, 60%] | 92% [88%, 95%] |

3. **Habit detector (size after a loss).** We simulate traders who size up by a stated factor after each loss and count how often `size_after_loss` returns FLAGGED (raw, p below 0.05 and ratio at least 1.25, before the Holm step; 100 traders per cell, 300 permutations per test, seeds different from the court run). Weak habits are included on purpose, because 3x is easy.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No size habit (false flag) | 4% [2%, 10%] | 1% [0%, 5%] | 0% [0%, 4%] | 0% [0%, 4%] |
| Sizes up 1.25x after a loss (power) | 38% [29%, 48%] | 48% [38%, 58%] | 46% [37%, 56%] | 51% [41%, 61%] |
| Sizes up 1.5x after a loss (power) | 91% [84%, 95%] | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |
| Sizes up 2x after a loss (power) | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |
| Sizes up 3x after a loss (power) | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |

Reading it: the detector did not false-flag a trader with no habit in these runs, finds a 1.5x or larger habit nearly always from 150 trips, and finds a 1.25x habit only about half the time even at 600 trips (46% at 300 trips). A small real habit is therefore often invisible to us, which is why the product says "underpowered" rather than "clean".

## 2. Cross-checks against independent implementations

Tolerances were fixed in the script before the first run. The shipped traders are the six real histories (A to E and the Bitget export G); the planted trader F is excluded.

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

Result: permutation p-values 13 of 13, bootstrap CIs 12 of 13, shipped Holm adjustments 19 of 19, court verdicts 24 of 24.

**Finding 1 (bootstrap CI noise, not a bug).** wallet A size_after_loss: our shipped CI is [0.776, 1.21] and scipy's is [0.757, 1.16]. Re-running our own procedure with 40 other seeds, 40% landed within tolerance (upper endpoint ranged 1.15 to 1.21), and with 20,000 draws our procedure gives [0.76, 1.2], matching scipy. The p-value is unaffected. The cause is that a median of discrete order statistics has a lumpy bootstrap distribution, so a 97.5% endpoint can sit on a jump and 1,500 draws pin it down badly. The shipped interval is wider than the converged one, so the error is conservative. We did not change the shipped draw count; this row stays in the table as a known imprecision of the displayed upper endpoint for lumpy ratio statistics.

**Detector tests**

| Trader | Test | n (flagged group / other) | Our p | scipy p | Our 95% CI | scipy 95% CI (percentile) | scipy BCa | p ok | CI ok |
|---|---|---|---|---|---|---|---|---|---|
| A | size_after_loss | 28/48 | 0.4331 | 0.4297 | [0.776, 1.21] | [0.757, 1.16] | [0.845, 1.26] | yes | NO |
| A | hold_asymmetry | 29/54 | 0.6281 | 0.6376 | [0.282, 3.37] | [0.309, 3.53] | [0.293, 3.36] | yes | yes |
| A | overtrading_clusters | 9/74 | underpowered | underpowered | | | | yes | |
| B | size_after_loss | 90/21 | 0.0115 | 0.0148 | [0.893, 26.3] | [0.881, 25.4] | [0.871, 24.7] | yes | yes |
| B | hold_asymmetry | 83/29 | 1.0000 | 1.0000 | [0.101, 0.447] | [0.1, 0.441] | [0.0871, 0.388] | yes | yes |
| B | overtrading_clusters | 0/0 | underpowered | underpowered | | | | yes | |
| C | size_after_loss | 183/90 | 0.1570 | 0.1473 | [0.835, 2] | [0.85, 2] | [0.717, 1.62] | yes | yes |
| C | hold_asymmetry | 168/107 | 1.0000 | 1.0000 | [0.152, 0.354] | [0.148, 0.35] | [0.148, 0.349] | yes | yes |
| C | overtrading_clusters | 81/194 | 0.4801 | 0.4807 | [-197, 216] | [-200, 207] | [-194, 214] | yes | yes |
| D | size_after_loss | 128/190 | 0.9205 | 0.9176 | [0.824, 1.04] | [0.814, 1.02] | [0.837, 1.05] | yes | yes |
| D | hold_asymmetry | 122/197 | 0.9813 | 0.9822 | [0.229, 1.3] | [0.23, 1.31] | [0.207, 1.2] | yes | yes |
| D | overtrading_clusters | 73/246 | 0.0552 | 0.0561 | [-683, 77.4] | [-671, 74.8] | [-722, 44.2] | yes | yes |
| E | size_after_loss | 129/94 | 0.8433 | 0.8441 | [0.827, 1] | [0.827, 1] | [0.972, 1] | yes | yes |
| E | hold_asymmetry | 127/97 | 1.0000 | 1.0000 | [0.224, 0.5] | [0.215, 0.516] | [0.246, 0.588] | yes | yes |
| E | overtrading_clusters | 29/195 | 0.7036 | 0.7068 | [-2.56e+03, 4.98e+03] | [-2.59e+03, 5.03e+03] | [-1.91e+03, 7.17e+03] | yes | yes |
| G | size_after_loss | 55/11 | underpowered | underpowered | | | | yes | |
| G | hold_asymmetry | 56/11 | underpowered | underpowered | | | | yes | |
| G | overtrading_clusters | 0/0 | underpowered | underpowered | | | | yes | |

**Court verdicts (our walk-forward court against a re-implementation from its documented rule, 100,000 permutations)**

| Trader | Cap | Our status | Reference status | Our p (1,500 perms) | Reference p (100,000) | Our held-out effect | Reference effect |
|---|---|---|---|---|---|---|---|
| A | 1.0x | REJECTED | REJECTED | 0.8728 | 0.8735 | -14611.78 | -14611.78 |
| A | 1.5x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | -8826.63 | -8826.63 |
| A | 2.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | -3090.76 | -3090.76 |
| A | 3.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 33.35 | 33.35 |
| B | 1.0x | REJECTED | REJECTED | 0.0706 | 0.0714 | 54.48 | 54.48 |
| B | 1.5x | REJECTED | REJECTED | 0.0846 | 0.0858 | -630.50 | -630.50 |
| B | 2.0x | REJECTED | REJECTED | 0.1039 | 0.1037 | -1003.37 | -1003.37 |
| B | 3.0x | REJECTED | REJECTED | 0.1419 | 0.1377 | -1118.31 | -1118.31 |
| C | 1.0x | REJECTED | REJECTED | 0.1945 | 0.1933 | 6764.30 | 6764.30 |
| C | 1.5x | REJECTED | REJECTED | 0.2165 | 0.2069 | 5591.65 | 5591.65 |
| C | 2.0x | REJECTED | REJECTED | 0.2492 | 0.2449 | 5001.26 | 5001.26 |
| C | 3.0x | REJECTED | REJECTED | 0.1739 | 0.1728 | 5425.16 | 5425.16 |
| D | 1.0x | ACCEPTED | ACCEPTED | 0.0020 | 0.0018 | 7498.26 | 7498.26 |
| D | 1.5x | ACCEPTED | ACCEPTED | 0.0027 | 0.0031 | 6303.24 | 6303.24 |
| D | 2.0x | REJECTED | REJECTED | 0.0167 | 0.0178 | 2830.12 | 2830.12 |
| D | 3.0x | REJECTED | REJECTED | 0.0939 | 0.0980 | -239.22 | -239.22 |
| E | 1.0x | REJECTED | REJECTED | 0.8767 | 0.8801 | -60706.66 | -60706.66 |
| E | 1.5x | REJECTED | REJECTED | 0.8701 | 0.8568 | -28476.02 | -28476.02 |
| E | 2.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | -5274.85 | -5274.85 |
| E | 3.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 0.00 | 0.00 |
| G | 1.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 0.00 | 0.00 |
| G | 1.5x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 0.00 | 0.00 |
| G | 2.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 0.00 | 0.00 |
| G | 3.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 0.00 | 0.00 |

**Finding 2 (are trips exchangeable?).** The detectors and the court resample trips as independent draws. With `arch` we repeated the all-history cap-rule interval with the iid bootstrap (it matches ours), a stationary bootstrap and a circular block bootstrap. Dependent-data intervals are 0.89x to 1.03x as wide as the iid one, and no wallet's interval changed on whether it contains zero. On these six histories the exchangeability assumption does not change the conclusion; that is a measured fact about six histories, not a proof.

| Trader | Rule | Effect | Our iid CI (800 draws) | arch iid CI | arch stationary (mean block 5) | width vs iid | arch circular block 5 | width vs iid |
|---|---|---|---|---|---|---|---|---|
| A | cap 1.5x | -2,759 | [-8,307, 45] | [-8,307, 45] | [-8,345, 45] | 1.00x | [-8,345, 67] | 1.01x |
| B | cap 1.5x | 1,287 | [-3,499, 4,805] | [-3,401, 5,038] | [-2,923, 4,589] | 0.89x | [-3,299, 4,899] | 0.97x |
| C | cap 1.5x | 2,351 | [-10,354, 13,410] | [-10,259, 13,990] | [-10,265, 14,716] | 1.03x | [-9,637, 14,364] | 0.99x |
| D | cap 1.5x | -1,964 | [-9,514, 5,944] | [-10,059, 5,636] | [-10,346, 5,407] | 1.00x | [-11,184, 5,720] | 1.08x |
| E | cap 1.5x | -22,101 | [-75,851, 6,806] | [-75,687, 6,725] | [-75,874, 6,928] | 1.00x | [-75,417, 6,752] | 1.00x |
| G | cap 1.5x | -0 | [-1, 0] | [-1, 0] | [-1, 0] | 1.00x | [-1, 0] | 1.00x |

## 3. Property tests (hypothesis)

9 property tests pass (`tests/test_validation_properties.py`): fills turn into round trips that conserve net pnl including an unfinished tail; `dedupe` is idempotent, order-free and replay-proof; the after-loss label of a trip does not change when every later trip is rewritten; the walk-forward court's cap for the last chunk does not change when that chunk's own trades are rewritten; Holm adjusted p-values are bounded by 1 and by Bonferroni, monotone in the raw p-values, equivariant under reordering, never improved by adding a test, and equal to statsmodels.

## 4. Backtest overfitting (PBO) and a deflated Sharpe on the rule-court ledger

Implemented by us from the published formulas (Bailey, Borwein, Lopez de Prado and Zhu 2015 for CSCV and PBO; Bailey and Lopez de Prado 2014 for the probabilistic and deflated Sharpe ratio), in `scripts/validation_lib.py`. The four pre-declared caps are the trial ledger. Each cap's per-trip dollar effect over the whole history is one column; PBO splits the history into 16 time blocks and tries all 12,870 half/half splits: how often does the cap that looks best in-sample rank at or below the median out of sample? DSR deflates the best cap's Sharpe ratio for having been picked from four.

Honest limits: four trials is very few for CSCV; the caps are nested and strongly correlated (see the correlation column), so the effective number of trials is below four; the per-trip effect series is mostly zeros, so Sharpe ratios and their skew and kurtosis are crude. PBO asks whether the choice among caps is stable, a different question from the court's "is this rule's out-of-sample effect real", so the two can differ. We report both rather than pick the flattering one.

| Planted trader (300 trips, 60 sims) | Mean PBO | Mean P(best rule loses out of sample) | Mean DSR | Mean PSR(0) | Share DSR > 0.95 | Mean correlation between rules |
|---|---|---|---|---|---|---|
| No leak | 0.43 | 0.55 | 0.66 | 0.80 | 12% | 0.71 |
| Costless habit | 0.47 | 0.43 | 0.59 | 0.64 | 12% | 0.94 |
| Costly leak | 0.01 | 0.01 | 0.99 | 1.00 | 93% | 0.94 |

On planted traders the numbers behave: a leak that is really costly gives PBO near 0.01 and a deflated Sharpe near 0.99; a trader with no leak gives PBO near 0.43 (a coin flip is 0.5) and a deflated Sharpe near 0.66.

| Wallet | Trips used | PBO | P(best rule loses OOS) | In-sample best cap | PSR(0) | DSR (4 trials) | Court accepted |
|---|---|---|---|---|---|---|---|
| A | 76 | 0.77 | 1.00 | 3.0x | n/a | n/a | 0 |
| B | 111 | 0.37 | 0.39 | 1.5x | 0.69 | 0.60 | 0 |
| C | 273 | 0.69 | 0.39 | 3.0x | 0.92 | 0.81 | 0 |
| D | 318 | 0.87 | 0.74 | 1.0x | 0.52 | 0.36 | 2 |
| E | 223 | 0.76 | 0.59 | 2.0x | 0.98 | 0.54 | 0 |
| G | 66 | 0.33 | 0.33 | 1.0x | 0.85 | 0.58 | 0 |

**Finding 3 (the court's accepted rules on a real wallet are not confirmed by these two views).** wallet D is the one real wallet where the court accepted rules (1.0x (held-out $7,498), 1.5x (held-out $6,303)); the independent re-implementation reproduces both verdicts. But the same cap rules priced on ALL of D's history give $-1,964 at 1.5x with a 95% interval of [-10,059, 5,636] (it contains zero), the CSCV probability of backtest overfitting over D's four caps is 0.87, and the deflated Sharpe of the best cap is 0.36. The court's held-out effect leaves out the first sixth of the history by design (it sets the baseline), so a positive held-out figure next to a non-positive all-history figure is possible, and the gap is itself informative. We read this as: the acceptance is real under the court's pre-declared test, but it is not strong evidence; it clears one multiple-testing safeguard and fails to clear two other lenses. None of the real wallets reaches a deflated Sharpe of 0.95. Wallet A's best cap never binds (its Sharpe is zero), so its DSR is n/a.

## 4b. Hostile-generator robustness (our own stresses, our own failures)

`scripts/robustness_suite.py` builds 300 planted traders per row (300 round trips each, from the same planted generator as above) and then rewrites sizes and returns with a stress: persistent size drift, a regime shift at the midpoint, autocorrelated returns (so losses cluster), fat tails (Student t with 2 degrees of freedom), and all four together. In every row the trader has **no** size-up-after-loss habit, so every flag and every accepted rule is a wrong one. Cells are rates with Wilson 95% intervals. The four detectors are the app's Holm family; the court row is the 1.5x cap rule judged walk-forward with a four-proposal ledger. Only our own code is run here; no other tool's code or numbers are used.

| Stress (truth: no size-up habit) | size after loss | hold asymmetry | overtrading | revenge re-entry | any, after Holm | court wrongly accepts |
|---|---|---|---|---|---|---|
| none (reference) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.3% [0.1%, 1.9%] |
| persistent size drift (about 4.5x over the history) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 1.0% [0.3%, 2.9%] |
| regime shift at the midpoint (3x size, 3x volatility) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.7% [0.2%, 2.4%] |
| autocorrelated returns (AR(1), rho 0.6) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] |
| fat tails (Student t, 2 degrees of freedom) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 1.0% [0.3%, 2.9%] |
| all four together | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.3% [0.1%, 1.9%] |

**Before (first version of this suite, frozen in `robustness_results_before.json`).** The first court and detectors shuffled single labels as if trips were independent, judged against an expanding "usual size", and compared size after a loss with raw sizes. The same stresses gave:

| Stress (truth: no size-up habit) | size after loss | hold asymmetry | overtrading | revenge re-entry | any, after Holm | court wrongly accepts |
|---|---|---|---|---|---|---|
| none (reference) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.7% [0.2%, 2.4%] |
| persistent size drift (about 4.5x over the history) | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 2.0% [0.9%, 4.3%] | 1.0% [0.3%, 2.9%] |
| regime shift at the midpoint (3x size, 3x volatility) | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 3.3% [1.8%, 6.0%] | 0.3% [0.1%, 1.9%] |
| autocorrelated returns (AR(1), rho 0.6) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 3.3% [1.8%, 6.0%] | 0.0% [0.0%, 1.3%] | 3.3% [1.8%, 6.0%] | 49.0% [43.4%, 54.6%] |
| fat tails (Student t, 2 degrees of freedom) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 1.0% [0.3%, 2.9%] |
| all four together | 5.7% [3.6%, 8.9%] | 0.0% [0.0%, 1.3%] | 3.7% [2.1%, 6.4%] | 0.0% [0.0%, 1.3%] | 9.3% [6.5%, 13.2%] | 92.7% [89.1%, 95.1%] |

That version's worst court wrong acceptance was 92.7% under all four (49.0% under autocorrelated returns alone, 92.7% under all four), its worst family-wise flag rate was 9.3% under all four, and 3 cells had an interval wholly above 5%.

**Why it failed (diagnosis).** Three separate causes. (1) Serial dependence: if a loss tends to follow a loss, a cap after a loss really does save money on unseen trades, so the court's question ("does this cap help out of sample?") correctly returns yes while the premise of the rule ("you size up after losses") is false; shuffling single labels also understates how much a group-mean gap varies when outcomes or labels cluster. (2) Size drift and regime shifts: raw sizes after a loss are compared with raw sizes after a win, so a size level that moves over time (and a label that is correlated with time) looks like a habit; the court's expanding baseline also goes stale. (3) Fat tails and drift widen the effect distribution; with the first two fixed they did not matter here.

**After (current code, same generator, same seeds, same 300 traders per row).** What changed, in `engine/dependence.py`, `engine/court.py`, `engine/walkforward.py`, `engine/detectors.py` and `engine/stats.py`: (a) every habit test and the court check per-trip returns (or pnl) for serial dependence with a Ljung-Box test at the 1% level; when it fires the labels are permuted in contiguous blocks with the block length chosen from the data (a Politis-White rule, our own implementation checked against `arch`), otherwise the ordinary permutation is kept, so independent data is untouched; (b) size after a loss is measured against the trader's own trailing usual size (median of the previous 30 trades that did not follow a loss) instead of one global level, and the court's baseline uses a rolling window of the last 100 trips; (c) the court has a minimum-evidence guard: when dependence is detected, an out-of-sample gain is accepted only if the trader's sizes also show the size-up habit, the affected-trip count is discounted by the effective sample size, and the verdict reason says so in words (it never changes silently); (d) averaging down is tested on pnl before fees, because an add trades more size and pays more fee whatever the decision.

| Stress (truth: no size-up habit) | size after loss | hold asymmetry | overtrading | revenge re-entry | any, after Holm | court wrongly accepts |
|---|---|---|---|---|---|---|
| none (reference) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.3% [0.1%, 1.9%] |
| persistent size drift (about 4.5x over the history) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 0.0% [0.0%, 1.3%] | 1.7% [0.7%, 3.8%] | 1.0% [0.3%, 2.9%] |
| regime shift at the midpoint (3x size, 3x volatility) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.7% [0.2%, 2.4%] |
| autocorrelated returns (AR(1), rho 0.6) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.0% [0.0%, 1.3%] |
| fat tails (Student t, 2 degrees of freedom) | 0.0% [0.0%, 1.3%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 0.3% [0.1%, 1.9%] | 1.0% [0.3%, 2.9%] |
| all four together | 0.3% [0.1%, 1.9%] | 0.0% [0.0%, 1.3%] | 1.0% [0.3%, 2.9%] | 0.0% [0.0%, 1.3%] | 1.3% [0.5%, 3.4%] | 0.3% [0.1%, 1.9%] |

With no stress the family-wise false-flag rate is 1.0% and the court's wrong acceptance is 0.3%. The highest family-wise false-flag rate under any stress is now 1.7% under size drift and the highest single detector is overtrading_clusters 1.7% under size drift; the highest court wrong acceptance is 1.0% under size drift (autocorrelated returns 0.0%, all four together 0.3%; before: 49.0% and 92.7%). Cells whose interval lies wholly above 5% (0): none: no cell's 95% interval lies wholly above 5%.

What this does and does not show. It does not mean serial dependence is gone: under autocorrelated returns a cap after a loss still helps, and the court now declines to call that a size habit and says so in the verdict reason. Its price is power in one corner: if returns are serially dependent, a rule is accepted only when the size habit is also visible in sizes. A planted real costly leak (3x size after a loss, worse returns after a loss) on top of AR(1) returns at 600 trips is accepted 100.0% (95% interval 96.3% to 100.0%), with dependence detected for 100.0% of those traders. The stresses are ones we thought of, they are generated by the same author as the detectors, and a stressed history is not a real trader; "no cell fails" is a statement about these six conditions and 300 traders per row, not a guarantee. Intervals of a few percent are Monte-Carlo noise at this sample size.

## 5. What was not checked

- Court p-values were checked against a re-implementation written by us from the docs, not against a third-party library (no library implements this within-chunk label permutation). The detector p-values and CIs were checked against scipy.
- The revenge re-entry test and fee drag were not cross-checked: on the shipped wallets the former is underpowered everywhere and the latter has no permutation null.
- The planted generator and the detector share one author. An outside generator is still needed.
- None of this says the tested habits predict future losses for a real person.

## 6. Reproduce

```
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python scripts/crosscheck_stats.py     # minutes: independent re-computation of the shipped numbers
.venv/Scripts/python scripts/run_validation.py       # planted-bias power, PBO and deflated Sharpe, property tests, tables
.venv/Scripts/python scripts/robustness_suite.py     # hostile-generator stresses, writes robustness_results.json
.venv/Scripts/python scripts/render_docs.py          # renders this page from validation_results.json via claims.py
```
