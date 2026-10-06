# Validation: do our numbers agree with independent code, and do our detectors find what we plant?

This page is rendered from `VALIDATION.template.md` by `scripts/render_docs.py`. Every number below is computed by `scripts/crosscheck_stats.py` or `scripts/run_validation.py`, stored in `validation_results.json`, and quoted through `claims.py`. The validation tooling is dev-only (`requirements-dev.txt`: scipy 1.18.1, statsmodels 0.15.0, arch 8.0.0, hypothesis 6.168.5); the app, `requirements.txt` and the Dockerfile do not use it, and the tests that need it skip when it is absent.

Honest scope: planted traders come from our own generator, so passing them proves the machinery recovers what we put in, not that real traders behave like the generator. The independent re-computations check our arithmetic and our permutation and bootstrap code against other people's code; they do not check that the habits we test for are the right ones.

## 1. Planted-bias protocol

1. **Generator** (`engine/planted.py`, provenance `SIM_PLANTED`, never shown as a person): each trip has a log-normal size, a normal return per unit of notional, a fee, and a hold time. A planted *size habit* multiplies the next trip's size after a loss by `size_mult`. A planted *costly leak* also lowers the mean return after a loss by `tilt` (`-0.006`). A *costless habit* has the size-up but no tilt. A *null trader* has neither.
2. **Court (rule judging).** For each scenario and trip count we simulate 100 traders, propose four caps (1.0x, 1.5x, 2x, 3x of the trader's usual size) so the ledger holds four trials, and judge the 1.5x cap with the walk-forward court (`scripts/measure_court.py`, results in `court_results.json`). "Accepted" on a null or costless trader is a wrong acceptance. Wilson 95% intervals in brackets.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No leak (court wrongly accepts) | 0% [0%, 4%] | 1% [0%, 5%] | 1% [0%, 5%] | 1% [0%, 5%] |
| Costless habit, 3x size up (court wrongly accepts) | 0% [0%, 4%] | 1% [0%, 5%] | 0% [0%, 4%] | 3% [1%, 8%] |
| Costly leak (court correctly accepts = power) | 1% [0%, 5%] | 19% [13%, 28%] | 53% [43%, 62%] | 88% [80%, 93%] |

3. **Habit detector (size after a loss).** We simulate traders who size up by a stated factor after each loss and count how often `size_after_loss` returns FLAGGED (raw, p below 0.05 and ratio at least 1.25, before the Holm step; 100 traders per cell, 300 permutations per test, seeds different from the court run). Weak habits are included on purpose, because 3x is easy.

| Planted trader | 60 trips | 150 trips | 300 trips | 600 trips |
|---|---|---|---|---|
| No size habit (false flag) | 1% [0%, 5%] | 1% [0%, 5%] | 0% [0%, 4%] | 0% [0%, 4%] |
| Sizes up 1.25x after a loss (power) | 40% [31%, 50%] | 54% [44%, 63%] | 49% [39%, 59%] | 55% [45%, 64%] |
| Sizes up 1.5x after a loss (power) | 88% [80%, 93%] | 98% [93%, 99%] | 100% [96%, 100%] | 100% [96%, 100%] |
| Sizes up 2x after a loss (power) | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |
| Sizes up 3x after a loss (power) | 99% [95%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] | 100% [96%, 100%] |

Reading it: the detector did not false-flag a trader with no habit in these runs, finds a 1.5x or larger habit nearly always from 150 trips, and finds a 1.25x habit only about half the time even at 600 trips (49% at 300 trips). A small real habit is therefore often invisible to us, which is why the product says "underpowered" rather than "clean".

## 2. Cross-checks against independent implementations

Tolerances were fixed in the script before the first run. The shipped traders are the six real histories (A to E and the Bitget export G); the planted trader F is excluded.

| Quantity | Reference implementation | Compared | Agree | Tolerance (declared before running) |
|---|---|---|---|---|
| Detector p-values (permutation) | scipy.stats.permutation_test, 40,000 resamples | 13 | 13 | 3 combined Monte-Carlo SE + 1e-4 |
| Detector 95% CIs (bootstrap) | scipy.stats.bootstrap, 9,999 resamples | 13 | 12 | endpoints within 10% of the reference CI width |
| UNDERPOWERED gating | independent group counts | 5 | 5 | same decision |
| Holm adjusted p (shipped, per trader) | statsmodels multipletests(holm) | 13 | 13 | 5e-4 (max observed 0.0e+00) |
| Holm on random p-vectors | statsmodels multipletests(holm) | 3,000 | 3,000 | 1e-12 (max observed 0.0e+00) |
| Court walk-forward verdicts (effect, p, status) | our re-implementation from the docs, 100,000 permutations | 24 | 24 | effect within $0.01; p within 3 combined SE |
| After-loss labels | independent searchsorted implementation | 6 traders | 6 | identical arrays |
| All-history CI of the 1.5x rule | arch IIDBootstrap, 5,000 resamples | 6 | 6 | endpoints within 10% of width |

Result: permutation p-values 13 of 13, bootstrap CIs 12 of 13, shipped Holm adjustments 13 of 13, court verdicts 24 of 24.

**Finding 1 (bootstrap CI noise, not a bug).** wallet E size_after_loss: our shipped CI is [0.75, 1.6] and scipy's is [0.75, 1.33]. Re-running our own procedure with 40 other seeds, 80% landed within tolerance (upper endpoint ranged 1.33 to 1.6), and with 20,000 draws our procedure gives [0.75, 1.33], matching scipy. The p-value is unaffected. The cause is that a median of discrete order statistics has a lumpy bootstrap distribution, so a 97.5% endpoint can sit on a jump and 1,500 draws pin it down badly. The shipped interval is wider than the converged one, so the error is conservative. We did not change the shipped draw count; this row stays in the table as a known imprecision of the displayed upper endpoint for lumpy ratio statistics.

**Detector tests**

| Trader | Test | n (flagged group / other) | Our p | scipy p | Our 95% CI | scipy 95% CI (percentile) | scipy BCa | p ok | CI ok |
|---|---|---|---|---|---|---|---|---|---|
| A | size_after_loss | 28/48 | 0.4331 | 0.4297 | [0.754, 1.25] | [0.754, 1.25] | [0.806, 1.32] | yes | yes |
| A | hold_asymmetry | 29/54 | 0.6281 | 0.6376 | [0.282, 3.37] | [0.309, 3.53] | [0.293, 3.36] | yes | yes |
| A | overtrading_clusters | 9/74 | underpowered | underpowered | | | | yes | |
| B | size_after_loss | 90/21 | 0.0242 | 0.0315 | [0.993, 22.1] | [0.992, 20.2] | [0.909, 17] | yes | yes |
| B | hold_asymmetry | 83/29 | 1.0000 | 1.0000 | [0.101, 0.447] | [0.1, 0.441] | [0.0871, 0.388] | yes | yes |
| B | overtrading_clusters | 0/0 | underpowered | underpowered | | | | yes | |
| C | size_after_loss | 183/90 | 0.0730 | 0.0631 | [0.801, 2] | [0.801, 2] | [0.966, 2.25] | yes | yes |
| C | hold_asymmetry | 168/107 | 1.0000 | 1.0000 | [0.152, 0.354] | [0.148, 0.35] | [0.148, 0.349] | yes | yes |
| C | overtrading_clusters | 81/194 | 0.4801 | 0.4807 | [-197, 216] | [-200, 207] | [-194, 214] | yes | yes |
| D | size_after_loss | 128/190 | 0.8878 | 0.8897 | [0.662, 1.12] | [0.65, 1.12] | [0.668, 1.16] | yes | yes |
| D | hold_asymmetry | 122/197 | 0.9813 | 0.9822 | [0.229, 1.3] | [0.23, 1.31] | [0.207, 1.2] | yes | yes |
| D | overtrading_clusters | 73/246 | 0.0552 | 0.0561 | [-683, 77.4] | [-671, 74.8] | [-722, 44.2] | yes | yes |
| E | size_after_loss | 129/94 | 0.6926 | 0.6936 | [0.75, 1.6] | [0.75, 1.33] | [0.5, 1.06] | yes | NO |
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
| C | 1.0x | REJECTED | REJECTED | 0.2378 | 0.2487 | 6763.03 | 6763.03 |
| C | 1.5x | REJECTED | REJECTED | 0.2478 | 0.2521 | 5539.23 | 5539.23 |
| C | 2.0x | REJECTED | REJECTED | 0.2751 | 0.2731 | 5358.05 | 5358.05 |
| C | 3.0x | REJECTED | REJECTED | 0.2532 | 0.2584 | 5432.51 | 5432.51 |
| D | 1.0x | ACCEPTED | ACCEPTED | 0.0047 | 0.0050 | 5479.21 | 5479.21 |
| D | 1.5x | ACCEPTED | ACCEPTED | 0.0073 | 0.0060 | 4804.14 | 4804.14 |
| D | 2.0x | REJECTED | REJECTED | 0.0153 | 0.0177 | 2208.10 | 2208.10 |
| D | 3.0x | REJECTED | REJECTED | 0.0566 | 0.0601 | -612.45 | -612.45 |
| E | 1.0x | REJECTED | REJECTED | 0.8741 | 0.8757 | -57748.75 | -57748.75 |
| E | 1.5x | REJECTED | REJECTED | 0.8408 | 0.8324 | -23705.68 | -23705.68 |
| E | 2.0x | UNDERPOWERED | UNDERPOWERED | n/a | n/a | 474.26 | 474.26 |
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

**Finding 3 (the court's accepted rules on a real wallet are not confirmed by these two views).** wallet D is the one real wallet where the court accepted rules (1.0x (held-out $5,479), 1.5x (held-out $4,804)); the independent re-implementation reproduces both verdicts. But the same cap rules priced on ALL of D's history give $-1,964 at 1.5x with a 95% interval of [-10,059, 5,636] (it contains zero), the CSCV probability of backtest overfitting over D's four caps is 0.87, and the deflated Sharpe of the best cap is 0.36. The court's held-out effect leaves out the first sixth of the history by design (it sets the baseline), so a positive held-out figure next to a non-positive all-history figure is possible, and the gap is itself informative. We read this as: the acceptance is real under the court's pre-declared test, but it is not strong evidence; it clears one multiple-testing safeguard and fails to clear two other lenses. None of the real wallets reaches a deflated Sharpe of 0.95. Wallet A's best cap never binds (its Sharpe is zero), so its DSR is n/a.

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
.venv/Scripts/python scripts/render_docs.py          # renders this page from validation_results.json via claims.py
```
