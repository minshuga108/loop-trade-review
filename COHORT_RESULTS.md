# Cohort results: 60 public Hyperliquid wallets, 18,412 round trips

Provenance: REAL_PLATFORM_PUBLIC. Public on-chain fills read through Hyperliquid's keyless info API on
2026-10-06. Wallet ids W001-W060 are ordinals; no address, prefix or order id is in this repo.
Every number below is read from `cohort_results.json` (produced by `scripts/cohort_study.py`).
Terms check, sampling rule and analysis plan: `COHORT_NOTES.md`, committed before any fills were fetched.

## For a judge (plain version)

We drew 60 real public traders across the whole profit-and-loss range (12 from each fifth, from the
biggest losers to the biggest winners) by a rule written down and committed before we fetched any data,
and ran Loop's own tests on each trader against that trader's own history. Two things stand out.
First, the "bigger bets after a loss" habit looks strong when all traders are thrown into one pile
(pooled p = 0.0005), but disappears when each trader is only compared with themselves (p = 0.51): the
pile mixes big and small traders. This is the same trap Blotter (JUICEWRLD998) describes, and Loop's
within-trader test avoids it by design. Second, the habit is real for a few people, not for "traders":
4 of 55 testable wallets show it after correcting for testing 55 wallets at once, and the rule court
accepted a cap rule for 1 wallet out of 191 judged rule trials, about what chance alone would give
(up to 2.4). So Loop says "this is your habit" for a handful of people and "no proven leak" for most,
which is the honest answer.

## Sample

- Sampling rule (pre-registered, COHORT_NOTES.md section 2): leaderboard snapshot of 47,438 wallets;
  eligible 11,037 (account value at least 1,000 USD, all-time volume 1M-500M USD, month volume at least
  100k USD); five quintiles of all-time PnL; seeded shuffle (20261006) within each quintile; round-robin
  draw; keep a wallet if the existing ledger finds at least 60 flat-to-flat round trips; 12 per quintile.
- Candidates tried: 102 (per quintile Q1-Q5: 26, 14, 17, 19, 26). Kept: 60 (12 per quintile).
  The extremes needed more draws: many of the biggest losers and winners had fewer than 60 round trips
  in their last 10,000 fills.
- 459,230 fills, 18,412 round trips. Per wallet: round trips median 204 (min 62, max 1,133); window span
  median 319 days (7.6 to 1,137); fills per day median 24 (2.2 to 869). Mean wallet win rate 49%.
- Collection: 367 info requests plus one leaderboard download, no HTTP 429, no keys.

## Per-wallet habits (within-trader permutation tests, engine unchanged)

Benjamini-Hochberg at q = 0.10 across wallets, per detector, on the engine's one-sided p (habit direction).
"Engine flagged" is the engine's own uncorrected rule (p < 0.05 plus its effect floor).

| habit | wallets testable | BH significant (q 0.10) | engine flagged | raw p < 0.05 (chance would give) | per-wallet effect: median [IQR] (min to max) | direction across wallets |
|---|---|---|---|---|---|---|
| size after loss (opening size ratio, after loss / after win) | 55 | **4** | 6 | 8 (2.8) | 1.00 [0.78, 1.25] (0.40 to 2.43) | 28 up, 27 down, sign p 1.00 |
| hold asymmetry (loser / winner hold ratio) | 54 | **2** | 4 | 5 (2.7) | 0.43 [0.26, 1.10] (0.01 to 18.8) | 14 above 1, 40 below 1, sign p 0.0005 |
| overtrading days (heavy-day minus other, $/trip) | 50 | **0** | 3 | 3 (2.5) | -3 [-88, +86] (-1,584 to +1,104) | 23 / 27, sign p 0.67 |
| revenge re-entry (revenge minus other re-entries, $/trip) | 14 | **0** | 0 | 0 (0.7) | -5 [-95, +55] (-264 to +325) | 6 / 8, sign p 0.79 |

Notes:
- Size after loss, BH-significant: W012 (ratio 2.01), W015 (1.83), W016 (1.41), W002 (1.19; significant
  but under the engine's 1.25 effect floor, so the engine does not flag it). Engine-flagged but not
  surviving BH: W004, W030, W052.
- Hold asymmetry runs the OTHER way for most wallets: 40 of 54 hold losing trips SHORTER than winning
  ones (median ratio 0.43). Only W035 (18.8) and W053 (2.36) hold losers longer after correction.
  Stops and liquidations close losers fast in perps; this is not evidence of a disposition effect here.
- Revenge re-entry is underpowered for 46 of 60 wallets (fewer than 20 revenge re-entries).

## Pooled versus within-trader

Same statistic on all 60 wallets stacked. "Pooled p" shuffles labels across all trips (the naive test);
"within p" shuffles only inside each wallet. 2,000 permutations; the smallest possible p is 0.0005.

| test | pooled statistic | pooled p | within-trader p | scale-free version (each wallet divided by its own median or sd): pooled p / within p |
|---|---|---|---|---|
| size after loss (median log ratio) | +0.18 (ratio 1.20) | **0.0005** | **0.51** | 0.17 / 0.16 (ratio 1.001) |
| hold asymmetry (losers longer) | -0.94 (losers shorter) | 1.00 | 1.00 | 1.00 / 1.00 |
| overtrading days ($/trip) | +32 | 0.50 | 0.23 | 0.052 / 0.082 |
| revenge re-entry ($/trip) | +21 | 0.40 | 0.14 | 0.11 / 0.19 |

The size-after-loss row is the pooling trap in one line: a 20% "size-up after losses" across the pile,
p = 0.0005, that is entirely a mix of traders (within-trader p 0.51; once each wallet is put on its own
scale the gap is 0.1%).

## Blotter's two gaps on our cohort (win rate, net pnl > 0)

| gap | pooled gap | pooled p | within-trader p | per-wallet gap median (n testable) | BH significant wallets | direction |
|---|---|---|---|---|---|---|
| weekend entries win less | +0.5 points | 0.31 | 0.24 | -2.3 points (46) | 1 | 20 / 26, sign p 0.46 |
| entries within 60 min after a loss win less | **+18.8 points** | 0.0005 | **0.0005** | +3.4 points (39) | 1 | 27 / 12, sign p 0.024 |

- Weekend: no gap in our cohort at all, pooled or within (Blotter's pooled 10-point gap does not appear).
- 60 minutes after a loss: unlike Blotter's cohort, the gap SURVIVES the within-trader shuffle. But a
  check we added after seeing this (exploratory, not pre-registered) shows entries within 60 minutes
  after a WIN win 12.1 points MORE than other entries (pooled p 0.0005, within-trader p 0.030; per wallet
  25 of 36 positive, sign p 0.029). Outcomes cluster in time (market regimes, streaks), and a label
  shuffle within a trader does not respect time order. So this gap is NOT shown to be a reaction to
  losing; it needs a time-blocked null to say more. We do not claim it.

## Rule court (walk-forward, engine unchanged)

Per wallet: the 4 cap rules (opening size capped at 1.0x, 1.5x, 2.0x, 3.0x of the calm-trip median after a
loss) proposed first, so the trial-count ledger is 4 per wallet and each rule must clear p < 0.0125;
`walkforward.judge_wf`, 5 folds, 2,000 permutations.

| cap | ACCEPTED | REJECTED | UNDERPOWERED |
|---|---|---|---|
| 1.0x | 0 | 55 | 5 |
| 1.5x | 0 | 49 | 11 |
| 2.0x | 1 | 45 | 14 |
| 3.0x | 0 | 41 | 19 |

- Trial ledger: 240 rule trials across the cohort (4 x 60), 191 judged (not underpowered). Wallets with
  at least one ACCEPTED rule: **1 of 60** (W051, 2.0x cap, out-of-sample +$47 over 110 trips, 18 touched,
  p 0.0015). Five wallets were underpowered on all four rules.
- If no wallet had a real leak, up to 0.0125 x 191 = 2.4 acceptances would be expected from chance. One
  acceptance is consistent with chance; we do not present W051 as a proven leak. The court's job is to
  refuse rules that do not pay out of sample, and on real public traders it refused almost all of them.
- Note that none of the 4 BH-significant size-after-loss wallets got an accepted cap: sizing up after a
  loss is a habit, and it only becomes a leak when those bigger trades also lose more, which the court
  did not find for them out of sample.

## What is NOT claimed

- Not that these habits are common among traders, or among Bitget users. Not that any wallet's owner is
  emotional, on tilt or "revenge" trading: these are names for timing-and-size patterns.
- Not that the 60-minutes-after-a-loss gap is behavioural (see the after-win check).
- Not that W051's accepted rule is real (one acceptance is within chance).
- Not that the cohort is representative of Hyperliquid: it is a stratified sample of the leaderboard's
  active, non-market-maker-scale wallets with at least 60 round trips in the reachable window.
- The court and detector false-positive rates are measured on planted traders (court_results.json),
  not here; these public wallets have no ground truth.

## Limits

- Public Hyperliquid wallets are not Bitget users and gave no consent; they are pseudonymous, may be bots
  or semi-automated (fills per day reach 869), and one person can run many wallets.
- Crypto perps, HIP-3 stock perps (xyz:, para:, io: dexes) and a few spot fills are mixed in the same
  round-trip ledger, as in the existing samples.
- Survivorship: the leaderboard lists wallets that still exist with some account value; fully drained
  and abandoned wallets are under-represented. The quintiles are of all-time PnL, which the window may
  not reflect.
- Window: only the last 10,000 fills per wallet are reachable, so high-frequency wallets cover days and
  slow ones years (span 7.6 to 1,137 days). A trip open at the start of the window is skipped.
- Per-wallet permutation tests treat trips as exchangeable; serial correlation in outcomes (shown above)
  makes p-values for time-adjacent labels optimistic.
- The overtrading and revenge pooled rows stack all wallets, including those the per-wallet detector
  calls underpowered.
- One snapshot day, one seed, one cohort. Exact counts can move with a re-draw.

## Per-wallet table

p is the engine's one-sided within-trader permutation p; **BH** marks significance at q 0.10 across
wallets. Court: A = ACCEPTED, R = REJECTED, U = UNDERPOWERED. n/a = underpowered.

| id | PnL quintile | trips | span d | fills/d | size after loss (ratio) | loser/winner hold (ratio) | heavy-day gap ($/trip) | revenge gap ($/trip) | court 1.0/1.5/2.0/3.0 |
|---|---|---|---|---|---|---|---|---|---|
| W001 | Q2 | 251 | 194 | 23 | 0.80 (p 0.913) | 0.47 (p 0.992) | -301 (p 0.097) | -230 (p 0.229) | R/R/R/R |
| W002 | Q3 | 776 | 416 | 24 | 1.19 (p 0.007) **BH** | 0.20 (p 1.000) | -11 (p 0.098) | -8 (p 0.234) | R/R/R/R |
| W003 | Q5 | 204 | 62 | 161 | 1.44 (p 0.127) | 0.40 (p 0.880) | -293 (p 0.187) | n/a | R/R/R/R |
| W004 | Q2 | 821 | 48 | 146 | 1.26 (p 0.011) | 0.44 (p 1.000) | -2 (p 0.346) | -19 (p 0.090) | R/R/R/R |
| W005 | Q5 | 103 | 1137 | 8 | 0.92 (p 0.605) | 0.41 (p 0.955) | n/a | n/a | R/R/R/U |
| W006 | Q1 | 685 | 52 | 194 | 0.96 (p 0.556) | 0.13 (p 1.000) | -79 (p 0.065) | -22 (p 0.470) | R/R/R/R |
| W007 | Q3 | 525 | 929 | 7 | 0.96 (p 0.611) | 0.21 (p 1.000) | +3 (p 0.741) | -3 (p 0.197) | R/R/R/R |
| W008 | Q5 | 235 | 656 | 5 | 1.37 (p 0.104) | 0.29 (p 0.993) | +127 (p 0.712) | -264 (p 0.054) | R/R/R/U |
| W009 | Q1 | 134 | 96 | 104 | 1.35 (p 0.093) | 1.67 (p 0.131) | +418 (p 0.667) | n/a | R/U/U/U |
| W010 | Q2 | 940 | 464 | 22 | 1.04 (p 0.387) | 0.17 (p 1.000) | -21 (p 0.213) | +81 (p 0.957) | R/R/R/R |
| W011 | Q3 | 346 | 93 | 107 | n/a | n/a | -69 (p 0.023) | n/a | U/U/U/U |
| W012 | Q4 | 865 | 220 | 45 | 2.01 (p 0.000) **BH** | 1.00 (p 0.837) | +1 (p 0.530) | n/a | R/R/R/R |
| W013 | Q5 | 88 | 40 | 250 | n/a | n/a | -2 (p 0.485) | n/a | R/R/R/R |
| W014 | Q2 | 490 | 193 | 46 | 0.75 (p 0.950) | 0.17 (p 1.000) | -91 (p 0.181) | n/a | R/R/R/R |
| W015 | Q3 | 314 | 84 | 118 | 1.83 (p 0.007) **BH** | 0.83 (p 0.687) | +222 (p 0.508) | n/a | R/R/R/R |
| W016 | Q1 | 176 | 165 | 60 | 1.41 (p 0.003) **BH** | 1.19 (p 0.268) | +705 (p 0.714) | n/a | R/R/U/U |
| W017 | Q3 | 203 | 60 | 164 | 0.77 (p 0.766) | 0.94 (p 0.570) | +89 (p 0.827) | n/a | R/U/U/U |
| W018 | Q4 | 235 | 649 | 15 | 1.23 (p 0.289) | 1.31 (p 0.262) | -359 (p 0.281) | n/a | R/R/R/R |
| W019 | Q5 | 121 | 305 | 33 | n/a | n/a | n/a | n/a | U/U/U/U |
| W020 | Q1 | 280 | 391 | 21 | 0.76 (p 0.892) | 0.18 (p 1.000) | +382 (p 0.847) | n/a | R/R/R/R |
| W021 | Q2 | 220 | 332 | 30 | 1.23 (p 0.183) | 0.51 (p 0.974) | +441 (p 0.946) | n/a | R/R/R/R |
| W022 | Q3 | 163 | 131 | 76 | 0.62 (p 0.677) | 0.40 (p 0.978) | -8 (p 0.398) | n/a | R/R/R/R |
| W023 | Q4 | 64 | 302 | 8 | 0.69 (p 0.898) | n/a | -908 (p 0.265) | n/a | R/U/U/U |
| W024 | Q2 | 719 | 757 | 9 | 0.93 (p 0.664) | 0.84 (p 0.865) | +25 (p 0.616) | +111 (p 0.830) | R/R/R/R |
| W025 | Q4 | 271 | 130 | 74 | 1.29 (p 0.171) | 0.27 (p 1.000) | -60 (p 0.215) | n/a | R/R/R/R |
| W026 | Q5 | 390 | 299 | 33 | 1.12 (p 0.172) | 0.19 (p 1.000) | +167 (p 0.423) | n/a | R/R/R/R |
| W027 | Q1 | 328 | 611 | 7 | 0.73 (p 0.938) | 0.38 (p 0.999) | +53 (p 0.727) | -119 (p 0.154) | R/R/R/R |
| W028 | Q2 | 102 | 219 | 16 | 1.13 (p 0.329) | 0.13 (p 1.000) | -418 (p 0.185) | n/a | R/R/R/R |
| W029 | Q3 | 375 | 110 | 90 | 0.65 (p 0.979) | 0.33 (p 1.000) | -11 (p 0.282) | n/a | R/R/R/R |
| W030 | Q4 | 93 | 466 | 8 | 1.63 (p 0.031) | 1.53 (p 0.270) | -402 (p 0.265) | n/a | R/R/R/R |
| W031 | Q2 | 255 | 423 | 8 | 1.14 (p 0.036) | 0.45 (p 0.971) | +154 (p 0.902) | +56 (p 0.627) | R/R/U/U |
| W032 | Q3 | 516 | 900 | 7 | 1.00 (p 0.435) | 0.25 (p 1.000) | -3 (p 0.431) | +53 (p 0.933) | R/R/R/R |
| W033 | Q4 | 83 | 470 | 8 | 1.24 (p 0.292) | 0.30 (p 0.975) | n/a | n/a | R/R/R/R |
| W034 | Q5 | 72 | 564 | 17 | 0.85 (p 0.565) | 0.01 (p 1.000) | n/a | n/a | U/U/U/U |
| W035 | Q2 | 1107 | 403 | 15 | 0.84 (p 0.818) | 18.80 (p 0.000) **BH** | +22 (p 0.885) | n/a | R/R/R/U |
| W036 | Q4 | 290 | 1124 | 4 | 0.78 (p 0.735) | 0.45 (p 0.998) | +7 (p 0.520) | n/a | R/R/R/R |
| W037 | Q2 | 78 | 143 | 27 | 0.64 (p 0.872) | 1.14 (p 0.449) | n/a | n/a | R/R/R/U |
| W038 | Q1 | 465 | 821 | 12 | 0.63 (p 0.989) | 1.48 (p 0.056) | +78 (p 0.605) | n/a | R/R/R/R |
| W039 | Q2 | 94 | 1011 | 3 | 0.54 (p 0.929) | 0.12 (p 0.994) | +214 (p 0.511) | n/a | R/R/R/R |
| W040 | Q4 | 498 | 412 | 24 | 0.40 (p 1.000) | 0.25 (p 1.000) | -79 (p 0.303) | +325 (p 0.810) | R/R/R/R |
| W041 | Q1 | 160 | 352 | 28 | 1.20 (p 0.148) | 1.43 (p 0.127) | +97 (p 0.565) | n/a | R/U/U/U |
| W042 | Q2 | 114 | 270 | 24 | 1.62 (p 0.218) | 0.23 (p 0.989) | n/a | n/a | R/R/R/R |
| W043 | Q3 | 74 | 165 | 11 | 0.89 (p 0.646) | 0.91 (p 0.628) | n/a | n/a | U/U/U/U |
| W044 | Q4 | 188 | 266 | 27 | 0.80 (p 0.858) | 0.27 (p 0.989) | -393 (p 0.016) | n/a | R/R/R/R |
| W045 | Q1 | 62 | 8 | 869 | n/a | n/a | n/a | n/a | R/R/R/R |
| W046 | Q3 | 221 | 476 | 21 | 1.01 (p 0.484) | 1.17 (p 0.358) | -51 (p 0.373) | n/a | R/R/U/U |
| W047 | Q4 | 1133 | 230 | 44 | 0.99 (p 0.550) | 1.22 (p 0.040) | +8 (p 0.632) | +5 (p 0.285) | R/R/R/R |
| W048 | Q5 | 170 | 400 | 25 | 1.64 (p 0.186) | 1.27 (p 0.167) | +42 (p 0.564) | n/a | R/U/U/U |
| W049 | Q3 | 146 | 501 | 6 | 1.14 (p 0.311) | 0.36 (p 0.999) | -568 (p 0.030) | n/a | R/R/R/R |
| W050 | Q5 | 461 | 1055 | 9 | 0.94 (p 0.740) | 0.38 (p 1.000) | -58 (p 0.359) | -172 (p 0.088) | R/R/R/R |
| W051 | Q3 | 132 | 908 | 11 | 1.14 (p 0.189) | 0.95 (p 0.944) | +43 (p 0.778) | n/a | R/R/A/R |
| W052 | Q1 | 160 | 216 | 46 | 1.51 (p 0.019) | 0.47 (p 0.967) | -1444 (p 0.112) | n/a | R/R/R/R |
| W053 | Q4 | 418 | 981 | 2 | 0.96 (p 0.617) | 2.36 (p 0.002) **BH** | -35 (p 0.065) | n/a | R/R/R/R |
| W054 | Q4 | 91 | 630 | 12 | 2.43 (p 0.099) | 9.15 (p 0.034) | n/a | n/a | R/R/R/R |
| W055 | Q5 | 172 | 59 | 168 | n/a | n/a | -520 (p 0.074) | n/a | U/U/U/U |
| W056 | Q1 | 111 | 225 | 26 | 0.73 (p 0.807) | 0.75 (p 0.657) | -1584 (p 0.152) | n/a | R/R/R/R |
| W057 | Q1 | 185 | 344 | 29 | 0.70 (p 0.877) | 0.19 (p 1.000) | -429 (p 0.380) | n/a | R/R/R/U |
| W058 | Q5 | 204 | 674 | 8 | 1.00 (p 0.303) | 0.41 (p 1.000) | +620 (p 0.759) | n/a | R/R/R/R |
| W059 | Q1 | 65 | 123 | 49 | 0.70 (p 0.817) | 0.38 (p 0.860) | n/a | n/a | R/U/U/U |
| W060 | Q5 | 170 | 72 | 138 | 1.48 (p 0.163) | 1.57 (p 0.041) | +1104 (p 0.929) | n/a | R/R/R/R |
