# Cohort study: terms check and pre-registered plan

Written and committed on 2026-10-06 BEFORE any wallet fills were fetched. The only data looked at so far
is the size of the leaderboard (47,438 rows) and the size of the eligible universe below (11,037 rows).
Nothing in this file is changed after results are seen; any later deviation is listed at the bottom
under "Deviations" with a reason.

## 1. What Hyperliquid's pages say about using public API data

Pages read on 2026-10-06:

- Terms of Use, https://app.hyperliquid.xyz/terms (JS-rendered; text read from the page's own bundle
  `assets/TermsOfUse-*.js`, "Last updated on June 15, 2026").
- API docs, rate limits: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- API docs, info endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Not reachable: the privacy policy (https://app.hyperliquid.xyz/privacypolicy referenced by the ToU;
  hyperliquid.xyz returned 403 to a plain fetch). No separate API terms or data licence page exists in the
  docs sitemap (no page title contains terms, legal, licence or privacy).

Quoted lines (verbatim):

- Scope of the ToU: "These Terms of Use (“Terms”) explain the terms and conditions by which you may access
  and use this website-hosted user interface (“Interface”), available at app.hyperliquid.xyz."
- "The Interface is not the exclusive means of accessing Hyperliquid." and Hyperliquid is described as
  "a decentralized, permissionless, and community-driven blockchain".
- 3.1.8 "Automated or High-Frequency Abuses. Activity that employs bots, scripts, or other automated methods
  to interact with the Interface in ways that exceed reasonable usage, bypass rate limits, cause
  denial-of-service conditions, or disrupt the normal functioning of Hyperliquid or related systems."
- 3.1.1 "Intellectual Property Infringement. Activity that infringes or violates any copyright, trademark,
  service mark, patent, right of publicity, right of privacy, or other proprietary or intellectual property
  rights under applicable law."
- 3.1.10 "... including, but not limited to, those relating to financial crimes, market integrity, data
  protection, intellectual property, or consumer protection."
- 4.2 "Any content, information, or data made available through the Interface may be incomplete, outdated,
  or subject to other inaccuracies."
- Rate limits: "REST requests share an aggregated weight limit of 1200 per minute". "All other documented
  `info` requests have weight 20." and `userFillsByTime` is among the endpoints with "an additional rate
  limit weight per 20 items returned in the response".
- Info endpoint, userFillsByTime: "Returns at most 2000 fills per response and only the 10000 most recent
  fills are available".

Reading: nothing found prohibits reading public on-chain fills through the documented, keyless info API.
The ToU governs the web Interface; the only automation clause (3.1.8) targets automated use that exceeds
reasonable usage, bypasses rate limits or disrupts the system. This study stays far under the documented
limit (see 3), never touches the Interface, and sends read-only info requests only. Clauses 3.1.1 and
3.1.10 (right of privacy, data protection) are the real constraint: pseudonymous addresses can be personal
data, so no address, address prefix, display name or order id leaves `C:\Users\neon_\bitget\data\cohort_raw`
(outside git). Committed outputs use ordinal ids W001, W002, ... only. This is not legal advice.

## 2. Pre-registered sampling rule

- Source: leaderboard snapshot `GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`, downloaded
  2026-10-06, saved at `data/cohort_raw/leaderboard.json` (private).
- Eligible: accountValue >= 1,000 USD; all-time volume between 1M and 500M USD (drops dust accounts and
  market-maker-scale volume); month volume >= 100k USD (active in the last month, so recent fills exist).
  Eligible universe on this snapshot: 11,037 wallets.
- Strata: five quintiles of ALL-TIME PnL among eligible wallets (Q1 = biggest losers ... Q5 = biggest
  winners), so the cohort spans the performance range, not only winners.
- Order: within each stratum, wallets are shuffled with `numpy.random.default_rng(20261006)`.
- Draw: round-robin Q1, Q2, Q3, Q4, Q5, Q1, ... taking the next wallet of each stratum; fetch its fills;
  KEEP it if the existing ledger (`ledger.dedupe` then `ledger.to_round_trips` over the
  `adapters/hyperliquid_csv` loader) yields at least 60 flat-to-flat round trips. A stratum stops once it
  has 12 kept wallets. The run stops at 60 kept wallets (cap), or after 400 candidates tried, or when
  every stratum is full or empty. Minimum target: 30 kept wallets.
- No other exclusion (bots and semi-automated wallets are NOT removed; fills/day is reported instead).
- Fills: `userFillsByTime` from startTime 0, paged forward by last time + 1, at most 5 pages of 2000
  (the 10,000-fill window). All fills are kept, spot included, in the same column format as
  `data/trader_samples` (time_ms, coin, side, dir, px, sz, fee, closedPnl, startPosition, oid).

## 3. Collection etiquette

At most 2 requests per second, and a rolling weight budget of 600 per 60 s (half the documented 1200)
counting 20 + 1 per 20 fills returned. Network errors and 5xx retry up to 3 times with exponential
backoff. HTTP 429 stops the whole run immediately (progress is saved; the run resumes from the cache).
No keys, no write endpoints.

## 4. Pre-registered analysis

Per wallet, with the engine unchanged (n_perm 4000, seed 0): `detectors.size_after_loss`,
`detectors.hold_asymmetry`, `detectors2.overtrading_clusters`, `detectors2.revenge_reentry`.

- Multiple testing across wallets: Benjamini-Hochberg at q = 0.10 within each detector, over the wallets
  where the detector is not UNDERPOWERED. Report the count of BH-significant wallets in the habit's
  direction, alongside the engine's own FLAGGED count (p < 0.05 plus effect floor, uncorrected).
- Effect sizes: distribution (min, quartiles, max) of the per-wallet effect; sign count with a binomial
  sign test.
- Pooled versus within-trader: stack every wallet's trips with labels computed per wallet. Same statistic
  as the detector on the stacked data. Pooled p: labels shuffled across ALL trips (the naive pooled test).
  Within-trader p: labels shuffled only inside each wallet (stratified permutation), so between-wallet
  differences in size, pnl scale or hold time cannot create the gap. 2000 permutations, seed 0.
- Replication of Blotter's (JUICEWRLD998) two gaps on our cohort, same pooled versus within-trader
  contrast, statistic = win rate (net pnl > 0) difference: (a) weekend entries (opened Saturday or Sunday
  UTC) versus weekday; (b) entries opened within 60 minutes after the trader's most recent close, when
  that close was a loss, versus all other entries.
- Court: per wallet, a fresh `Court(n_perm=2000, seed=0)` with the 4 cap rules (1.0x, 1.5x, 2.0x, 3.0x of
  the calm-trip median) proposed first, then `walkforward.judge_wf` on each of the 4 rules. Trial ledger
  per wallet = 4 (Bonferroni 0.0125 per rule). Report ACCEPTED, REJECTED and UNDERPOWERED counts, wallets
  with at least one ACCEPTED rule, the cohort-wide trial count (4 x wallets) and the number of acceptances
  expected by chance if no wallet had a real leak (at most 0.0125 per trial).

## Deviations

- Collection ran exactly as written: 102 candidates tried, 60 kept (12 per quintile), 367 info requests,
  no 429. A page boundary re-read with tid de-duplication leaves some full wallets at 9,9xx fills instead
  of 10,000.
- Added AFTER seeing results, labelled exploratory in cohort_results.json (`exploratory_after_win_60m`)
  and COHORT_RESULTS.md: the mirror of Blotter's after-loss gap (entries within 60 minutes after a WIN),
  to check whether the after-loss gap is outcome clustering in time. It changes no pre-registered number.
- The overtrading and revenge pooled rows stack all 60 wallets, including wallets whose per-wallet test
  is underpowered (the plan did not say; stated in the results).
