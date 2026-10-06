# Validation: do our numbers agree with independent code, and do our detectors find what we plant?

This page is rendered from `VALIDATION.template.md` by `scripts/render_docs.py`. Every number below is computed by `scripts/crosscheck_stats.py` or `scripts/run_validation.py`, stored in `validation_results.json`, and quoted through `claims.py`. The validation tooling is dev-only (`requirements-dev.txt`: {{validation.tools}}); the app, `requirements.txt` and the Dockerfile do not use it, and the tests that need it skip when it is absent.

Honest scope: planted traders come from our own generator, so passing them proves the machinery recovers what we put in, not that real traders behave like the generator. The independent re-computations check our arithmetic and our permutation and bootstrap code against other people's code; they do not check that the habits we test for are the right ones.

## 1. Planted-bias protocol

1. **Generator** (`engine/planted.py`, provenance `SIM_PLANTED`, never shown as a person): each trip has a log-normal size, a normal return per unit of notional, a fee, and a hold time. A planted *size habit* multiplies the next trip's size after a loss by `size_mult`. A planted *costly leak* also lowers the mean return after a loss by `tilt` (`-0.006`). A *costless habit* has the size-up but no tilt. A *null trader* has neither.
2. **Court (rule judging).** For each scenario and trip count we simulate {{court.sims}} traders, propose four caps (1.0x, 1.5x, 2x, 3x of the trader's usual size) so the ledger holds four trials, and judge the 1.5x cap with the walk-forward court (`scripts/measure_court.py`, results in `court_results.json`). "Accepted" on a null or costless trader is a wrong acceptance. Wilson 95% intervals in brackets.

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
