# Validation: do our numbers agree with independent code, and do our detectors find what we plant?

This page is rendered from `VALIDATION.template.md` by `scripts/render_docs.py`. Every number below is computed by `scripts/crosscheck_stats.py` or `scripts/run_validation.py`, stored in `validation_results.json`, and quoted through `claims.py`. The validation tooling is dev-only (`requirements-dev.txt`: {{validation.tools}}); the app, `requirements.txt` and the Dockerfile do not use it, and the tests that need it skip when it is absent.

Honest scope: planted traders come from our own generator, so passing them proves the machinery recovers what we put in, not that real traders behave like the generator. The independent re-computations check our arithmetic and our permutation and bootstrap code against other people's code; they do not check that the habits we test for are the right ones.

## 1. Planted-bias protocol

1. **Generator** (`engine/planted.py`, provenance `SIM_PLANTED`, never shown as a person): each trip has a log-normal size, a normal return per unit of notional, a fee, and a hold time. A planted *size habit* multiplies the next trip's size after a loss by `size_mult`. A planted *costly leak* also lowers the mean return after a loss by `tilt` (`-0.006`). A *costless habit* has the size-up but no tilt. A *null trader* has neither.
2. **Court (rule judging).** For each scenario and trip count we simulate {{court.sims}} traders, propose four caps (1.0x, 1.5x, 2x, 3x of the trader's usual size) so the ledger holds four trials, and judge the 1.5x cap with the walk-forward court (`scripts/measure_court.py`, results in `court_results.json`). "Accepted" on a null or costless trader is a wrong acceptance. This is on independent (non-serially-dependent) data: the planted generator draws every return independently. The stress results in section 4b (autocorrelated returns, drift, regime shifts, fat tails) are reported separately and are where an earlier version of the court failed. Wilson 95% intervals in brackets.

{{validation.table.power_court}}

3. **Habit detector (size after a loss).** We simulate traders who size up by a stated factor after each loss and count how often `size_after_loss` returns FLAGGED (raw, p below 0.05 and ratio at least 1.25, before the Holm step; 100 traders per cell, 300 permutations per test, seeds different from the court run). Weak habits are included on purpose, because 3x is easy.

{{validation.table.power_detector}}

Reading it: the detector did not false-flag a trader with no habit in these runs, finds a 1.5x or larger habit nearly always from 150 trips, and finds a 1.25x habit only about half the time even at 600 trips ({{validation.detector_power_125_300}} at 300 trips). A small real habit is therefore often invisible to us, which is why the product says "underpowered" rather than "clean".

## 2. Cross-checks against independent implementations

Tolerances were fixed in the script before the first run. The shipped traders are the six real histories (A to E and the Bitget export G); the planted trader F is excluded.

{{validation.table.crosscheck_summary}}

Result: permutation p-values {{validation.p_agree}}, bootstrap CIs {{validation.ci_agree}}, shipped Holm adjustments {{validation.holm_agree}}, court verdicts {{validation.court_agree}}.

**Finding 1 (bootstrap CI noise, not a bug).** {{validation.ci_finding}}. The cause is that a median of discrete order statistics has a lumpy bootstrap distribution, so a 97.5% endpoint can sit on a jump and 1,500 draws pin it down badly. The shipped interval is wider than the converged one, so the error is conservative. We did not change the shipped draw count; this row stays in the table as a known imprecision of the displayed upper endpoint for lumpy ratio statistics.

**Detector tests**

{{validation.table.crosscheck_detectors}}

**Court verdicts (our walk-forward court against a re-implementation from its documented rule, 100,000 permutations)**

{{validation.table.crosscheck_court}}

**Finding 2 (are trips exchangeable?).** The detectors and the court resample trips as independent draws. With `arch` we repeated the all-history cap-rule interval with the iid bootstrap (it matches ours), a stationary bootstrap and a circular block bootstrap. Dependent-data intervals are {{validation.block_width}} as wide as the iid one, and no wallet's interval changed on whether it contains zero. On these six histories the exchangeability assumption does not change the conclusion; that is a measured fact about six histories, not a proof.

{{validation.table.crosscheck_dependence}}

## 3. Property tests (hypothesis)

{{validation.props_passed}} property tests pass (`tests/test_validation_properties.py`): fills turn into round trips that conserve net pnl including an unfinished tail; `dedupe` is idempotent, order-free and replay-proof; the after-loss label of a trip does not change when every later trip is rewritten; the walk-forward court's cap for the last chunk does not change when that chunk's own trades are rewritten; Holm adjusted p-values are bounded by 1 and by Bonferroni, monotone in the raw p-values, equivariant under reordering, never improved by adding a test, and equal to statsmodels.

## 4. Backtest overfitting (PBO) and a deflated Sharpe on the rule-court ledger

Implemented by us from the published formulas (Bailey, Borwein, Lopez de Prado and Zhu 2015 for CSCV and PBO; Bailey and Lopez de Prado 2014 for the probabilistic and deflated Sharpe ratio), in `scripts/validation_lib.py`. The four pre-declared caps are the trial ledger. Each cap's per-trip dollar effect over the whole history is one column; PBO splits the history into 16 time blocks and tries all 12,870 half/half splits: how often does the cap that looks best in-sample rank at or below the median out of sample? DSR deflates the best cap's Sharpe ratio for having been picked from four.

Honest limits: four trials is very few for CSCV; the caps are nested and strongly correlated (see the correlation column), so the effective number of trials is below four; the per-trip effect series is mostly zeros, so Sharpe ratios and their skew and kurtosis are crude. PBO asks whether the choice among caps is stable, a different question from the court's "is this rule's out-of-sample effect real", so the two can differ. We report both rather than pick the flattering one.

{{validation.table.pbo_planted}}

On planted traders the numbers behave: a leak that is really costly gives PBO near {{validation.pbo_costly}} and a deflated Sharpe near {{validation.dsr_costly}}; a trader with no leak gives PBO near {{validation.pbo_null}} (a coin flip is 0.5) and a deflated Sharpe near {{validation.dsr_null}}.

{{validation.table.pbo_real}}

**Finding 3 (the court's accepted rules on a real wallet are not confirmed by these two views).** {{validation.d_finding}}. The court's held-out effect leaves out the first sixth of the history by design (it sets the baseline), so a positive held-out figure next to a non-positive all-history figure is possible, and the gap is itself informative. We read this as: the acceptance is real under the court's pre-declared test, but it is not strong evidence; it clears one multiple-testing safeguard and fails to clear two other lenses. None of the real wallets reaches a deflated Sharpe of 0.95. Wallet A's best cap never binds (its Sharpe is zero), so its DSR is n/a.

## 4b. Hostile-generator robustness (our own stresses, our own failures)

`scripts/robustness_suite.py` builds {{robustness.sims}} planted traders per row ({{robustness.trips}} round trips each, from the same planted generator as above) and then rewrites sizes and returns with a stress: persistent size drift, a regime shift at the midpoint, autocorrelated returns (so losses cluster), fat tails (Student t with 2 degrees of freedom), and all four together. In every row the trader has **no** size-up-after-loss habit, so every flag and every accepted rule is a wrong one. Cells are rates with Wilson 95% intervals. The four detectors are the app's Holm family; the court row is the 1.5x cap rule judged walk-forward with a four-proposal ledger. Only our own code is run here; no other tool's code or numbers are used.

{{robustness.table}}

**Before (first version of this suite, frozen in `robustness_results_before.json`).** The first court and detectors shuffled single labels as if trips were independent, judged against an expanding "usual size", and compared size after a loss with raw sizes. The same stresses gave:

{{robustness.before_table}}

That version's worst court wrong acceptance was {{robustness.before_worst_court}} ({{robustness.before_ac_court}} under autocorrelated returns alone, {{robustness.before_all_court}} under all four), its worst family-wise flag rate was {{robustness.before_worst_any}}, and {{robustness.before_n_failures}} cells had an interval wholly above 5%.

**Why it failed (diagnosis).** Three separate causes. (1) Serial dependence: if a loss tends to follow a loss, a cap after a loss really does save money on unseen trades, so the court's question ("does this cap help out of sample?") correctly returns yes while the premise of the rule ("you size up after losses") is false; shuffling single labels also understates how much a group-mean gap varies when outcomes or labels cluster. (2) Size drift and regime shifts: raw sizes after a loss are compared with raw sizes after a win, so a size level that moves over time (and a label that is correlated with time) looks like a habit; the court's expanding baseline also goes stale. (3) Fat tails and drift widen the effect distribution; with the first two fixed they did not matter here.

**After (current code, same generator, same seeds, same 300 traders per row).** What changed, in `engine/dependence.py`, `engine/court.py`, `engine/walkforward.py`, `engine/detectors.py` and `engine/stats.py`: (a) every habit test and the court check per-trip returns (or pnl) for serial dependence with a Ljung-Box test at the 1% level; when it fires the labels are permuted in contiguous blocks with the block length chosen from the data (a Politis-White rule, our own implementation checked against `arch`), otherwise the ordinary permutation is kept, so independent data is untouched; (b) size after a loss is measured against the trader's own trailing usual size (median of the previous 30 trades that did not follow a loss) instead of one global level, and the court's baseline uses a rolling window of the last 100 trips; (c) the court has a minimum-evidence guard: when dependence is detected, an out-of-sample gain is accepted only if the trader's sizes also show the size-up habit, the affected-trip count is discounted by the effective sample size, and the verdict reason says so in words (it never changes silently); (d) averaging down is tested on pnl before fees, because an add trades more size and pays more fee whatever the decision.

{{robustness.table}}

With no stress the family-wise false-flag rate is {{robustness.baseline_any}} and the court's wrong acceptance is {{robustness.baseline_court}}. The highest family-wise false-flag rate under any stress is now {{robustness.worst_any}} and the highest single detector is {{robustness.worst_detector}}; the highest court wrong acceptance is {{robustness.worst_court}} (autocorrelated returns {{robustness.ac_court}}, all four together {{robustness.all_court}}; before: {{robustness.before_ac_court}} and {{robustness.before_all_court}}). Cells whose interval lies wholly above 5% ({{robustness.n_failures}}): {{robustness.failures}}.

What this does and does not show. It does not mean serial dependence is gone: under autocorrelated returns a cap after a loss still helps, and the court now declines to call that a size habit and says so in the verdict reason. Its price is power in one corner: if returns are serially dependent, a rule is accepted only when the size habit is also visible in sizes. A planted real costly leak (3x size after a loss, worse returns after a loss) on top of AR(1) returns at {{robustness.dep_power_trips}} trips is accepted {{robustness.dep_power}}, with dependence detected for {{robustness.dep_power_detected}} of those traders. The stresses are ones we thought of, they are generated by the same author as the detectors, and a stressed history is not a real trader; "no cell fails" is a statement about these six conditions and 300 traders per row, not a guarantee. Intervals of a few percent are Monte-Carlo noise at this sample size.

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
