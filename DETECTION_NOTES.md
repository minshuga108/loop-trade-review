# Detection notes: planted-rule suite, look-ahead guard, head-to-head register

Files: `engine/suite.py`, `engine/lookahead.py`, `engine/decay.py`, `engine/register.py`,
`scripts/run_suite.py` -> `SUITE_RESULTS.md` (+ `suite_results.json`), `scripts/run_register.py` ->
`REGISTER_RESULTS.md` (+ `register_results.json`), tests in `tests/test_suite_lookahead.py`.
All numbers are in the two results files and were measured by those scripts. This note gives no new numbers.

## What was built
- **Planted-rule suite** (ARGUS-style: stationary 5/25/60/75% loss base rates, decay, base-rate shift). It judges our two
  rules (cap size after a loss, through `Court`; halt after 2 losses, through `halt.judge`) the same way the product does.
  It reports false admission, power, underpowered rate, wrongful-retirement rate and a full court -> rulebook -> decay
  check lifecycle, all with Wilson intervals, and it lists our losses.
- **Structural no-look-ahead guard** (`engine/lookahead.py`). This responds to arXiv 2608.27734, where a leaky Sharpe-35
  strategy passed DSR/PBO. Every feature is registered with the timestamp at which its value becomes known. Any
  feature known after the order's open is refused. A sampled as-of audit catches features whose tag lies. Each result
  carries the registry hash. In the suite, the planted peek rule was refused in 100 of 100 runs; with the guard
  switched off, statistics alone would have accepted it in every run.
- **Decay check** (`engine/decay.py`). The rulebook had retirement states but no automatic check. The check is
  pre-registered: it looks only at trades after arming and proposes retirement if effect <= 0 or p > 0.3. The owner
  still confirms.
- **Register** (`engine/register.py`). These are independent re-implementations of TradeMirror's four published rules
  and tradememory's published descriptive output, plus a trivial baseline and Loop. They run on 7 planted traders x 30
  seeds and on the 16 sampled public wallets.

## Limitations (read these before quoting any number)
1. **Everything in the suite is SIM_PLANTED and depends on the generator.** The sign of each trade is iid Bernoulli, so
   the base rate is exact by construction. The leak changes outcome magnitudes after a loss (k=0.5) and sizes up 3x.
   Real histories have volatility clustering, overlapping positions and symbol mixes that the generator does not
   model. Power depends on the leak strength and history length (500 trips) we chose. It is not a general curve.
2. **The cap rule loses power at high base rates for a structural reason.** The cap is 1.5x the median opening size
   of the training window. When 60-75% of trades follow a loss and are sized up 3x, the median itself is inflated,
   so the cap rarely binds. This is a design flaw in the rule's baseline, not noise. A fix would be a median computed
   on after-win trades only. It is not applied here, because changing the rule after seeing the suite would be tuning
   on the test.
3. **The court's permutation null is not exact when sizes differ by group.** On the costless-habit cells, after-loss
   trades are 3x larger, so shuffling the after-loss label is not exchangeable and the null is too narrow. The
   measured false admission on those cells is above the null cells; see the table.
4. **The halt rule has no trial deflation** (`halt.judge` uses p < 0.05). Its measured false admission on null cells
   sits around the nominal 5%, not near 0. We did not edit `halt.py` (the brief was new files only). The suite reports
   what the shipped code does.
5. **The decay check retires noisily.** With p > 0.3 as the retire bar, a dead rule is proposed for retirement often,
   but a real rule is also wrongly proposed in some cells (worst for halt and at 5%). The rulebook never retires
   without the owner. Even so, a proposal shown to a user is a claim, and the wrongful-retirement column should be
   read as how often we would nag about a good rule.
6. **The look-ahead guard is only as complete as the registry.** It cannot police code that computes a counterfactual
   outside the registry. The court and halt modules compute their own masks, and the suite checks that the guard's
   masks equal them exactly in every history. The audit samples 12 trips per evaluation, so a feature that lies on
   only a few trips can slip through a sample. The tag check covers every trip.
7. **The register is our reading of two README tables, not the rivals' code.** Every interpretation (mean vs median
   size, ratio of mean holds, greedy 2-hour windows, assumed fee rate for planted traders) is written next to the
   function. tradememory issues no verdict. The "flag" we give it is our convention, anchored on its own "5 of 20"
   example. A rival could fairly say our reading is wrong. That is why every row carries a provenance label.
8. **Wallet fees per trip are approximate.** They are summed from that symbol's fills inside [open, close], which
   double-counts only if fills share the boundary millisecond. Wallet CSVs have no order type and no rToken symbols,
   so TradeMirror's weekend rule is "not applicable" on all of them. Wallets have no ground truth: that table shows who
   flags what, not who is right.
9. **Some Loop coverage is missing from the register.** The overtrading detector in `engine/detectors2.py` is not
   wired in. Loop has no weekend/rToken detector. On those questions TradeMirror covers more than we do (and prices
   by assumption).
10. **Runtime and seeds.** The suite ran 100 sims per cell on fixed seeds (cell i: 10000*i + s), 1000 permutations,
    8 processes, in about 6 minutes. The register ran 30 seeds (500000-500029). Re-running the scripts reproduces the
    tables exactly on the same numpy version.
