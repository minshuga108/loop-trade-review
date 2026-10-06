# Stress report: hostile testing and hardening of Loop

Date: 2026-10-06. Branch `worktree-agent-a2d28c0a20580cc9b`, six commits (one per step; steps 2 and 3 share one because they touch the same page). Python 3.12, Windows 11, one machine. Other agent sessions were running on the same machine, so the timing numbers are noisy.

Test suite: 690 tests before, 768 after (+78). The only failure on this branch was already there before: `tests/test_judge.py::test_losses_says_the_uncomfortable_parts` fails because commit d5f65b2 rewrote LOSSES.md and the phrase "above nominal" is no longer in it. I did not touch it. The mutation script deselects it, since it fails on the unmutated tree too.

The data folder `../data` already existed next to the worktrees, so no copy or symlink was needed.

## 1. Fuzzing (tests/test_fuzz.py, seeded hand-written generators)

- **What ran:**
  - 15k random strings through `gate.parse_order`: unicode, RTL and zero-width marks, null bytes, emoji, 400-digit numbers, NaN and inf strings, SQL, HTML and JS.
  - 8k through `numberlock`.
  - 4k plus five 100k-character strings through the router.
  - 135 adversarial or random chat messages over HTTP.
  - 60 random fill histories through the ledger, with duplicates, shuffling, mid-position starts and unfinished trips. Checked: trips end flat, trip net equals the sum of (pnl − fee) over its fills, order totals are conserved.
  - 200 garbage-position histories.
  - 7k mutated Bitget UTA responses, 300 random Bitget English CSVs and 300 random Hyperliquid CSVs.
- **Bugs found and fixed:**
  - **`$1,000,000` was read as 1,000.** An order idea was under-read 1000×, so it could pass a size rule it breaks.
  - **A 400-digit number gave an `inf` notional.** Because inf is not valid JSON, `/api/chat` and `/api/gate` returned **500**.
  - **Number-lock let `7k`, `3e6`, `5万` and `2b` through.** It read them as 7, 3, 5 and 2, which sit on the 0..10 allow-list. Magnitudes attached to a numeral are now checked at their real size.
  - **Adapters crashed or let NaN through:**
    - A wrong-typed field raised TypeError or AttributeError, a short CSV row raised AttributeError, and `"nan"` became a NaN price.
    - Now: SchemaDrift for Bitget, BadRow (a ValueError) for Hyperliquid, and fill side must be buy or sell.
- **Proof:** with the old code, 14 of 23 fuzz tests fail.
- **Not bugs:**
  - The ledger conserved position and P&L on every generated history.
  - Python 3.12's compensated `sum()` broke my own test generator, not the engine.

## 2. HTTP hardening (tests/test_http.py)

Every route from main, judge, record_api and mcp_server was tried with:

- 10 odd path ids
- 15 malformed bodies
- 5 odd header sets
- traversal paths
- HEAD and OPTIONS
- oversized bodies, with and without Content-Length
- concurrent threads

**Bugs fixed:**

| Bug | Before | After |
|---|---|---|
| A validation error echoed its input, and an inf or undecodable body cannot be encoded | 500 | 422 or 400; inputs are no longer echoed |
| `POST /mcp` with `[` nested 3000 deep raised RecursionError | 500 | 400 parse error |
| Rulebook under 8 threads gave duplicate rule ids, a wrong proposal count and a **forked hash chain in 30 of 30 runs** | race | `Rulebook` mutators take an RLock; propose and transition hold it while logging |
| The session sandbox dict raised KeyError on concurrent eviction | race | dict access locked |
| Chat `history` had no length limit | unbounded | at most 50 items |
| HEAD on any GET route (uptime pingers often use HEAD) | 405 | answered like GET, with no body |

The record log's own lock held up: 8 threads × 40 appends kept the chain intact.

**New `app/ratelimit.py`** (in-memory token buckets, pure ASGI):

| Bucket | Burst | Refill |
|---|---|---|
| Per IP | 240 | 12/s |
| Per session | 120 | 6/s |
| Heavy routes, per IP (rulebook and court routes) | 30 | 1 every 2 s |

- Over the limit the answer is 429 with Retry-After. `/api/health` is exempt.
- Bodies over 64 KB get 413. Bodies without a Content-Length are buffered up to the cap first.
- An X-Session that is not 1 to 128 visible ASCII characters gets 400 (10k characters and control characters included).
- `LOOP_RATELIMIT=off` disables the buckets; the test suite sets it.

**New `app/security.py`:**

- CSP: `script-src 'self'` plus the SHA-256 of each of the 4 shipped inline scripts, computed at start-up with newlines normalized to LF. There is no `unsafe-inline` for scripts. Styles allow `unsafe-inline`.
- Also `object-src 'none'`, `base-uri 'none'`, `connect-src 'self'`.
- nosniff, Referrer-Policy, COOP and Permissions-Policy.
- Framing: X-Frame-Options SAMEORIGIN and `frame-ancestors 'self'`. On Hugging Face Spaces (`SPACE_ID` is set) it allows huggingface.co instead and drops X-Frame-Options, because a Space shows the app in an iframe. `LOOP_FRAME_ANCESTORS` overrides this.
- The one inline `onclick` (the language button) moved into i18n.js.

**Playwright check with headers and rate limits on:** the page loads, chat and gate answer, the rule toggle and language switch work, and /cockpit, /record and /selftest load. There are no CSP violations or page errors.

## 3. XSS review (index.html, rulebook.js, cockpit, record, selftest)

- cockpit, record and selftest already escaped everything.
- `index.html` and `rulebook.js` put these into `innerHTML` unescaped: trader label, blurb, provenance, rule text, toggle reason and note, detector-name fallback, fact values, the gate idea's side and symbol, rule id and evidence, and the badge fallback for unknown states. Their `esc()` also skipped quotes, so it was unsafe inside attributes.
- **None of these was exploitable today.** The values are server constants, and the gate symbol is letters only. They would have become stored XSS as soon as real user labels or uploads arrive. All are escaped now, and `esc()` handles quotes and null.
- A 422 `detail` list used to crash `esc()`; it is now shown as text.
- **Proof** (`tests/test_browser.py::test_xss_payloads_never_become_markup`):
  - `<script>`, `<img onerror>`, `"><svg onload>`, `'><img>` and `<iframe srcdoc>` go through the trader label and blurb, every chat answer field (text, interpreted, next chips, facts, steps, number_lock), the user's own echoed message, and the gate idea, reasons, checklist, note, state and check line.
  - It asserts that no injected element, attribute or script exists and that `window.__xss` is never set.
  - It fails on the old page.

## 4. Load (scripts/load_test.py; raw JSON in docs/stress/)

- **Setup:** standard library threads and http.client. The script starts its own uvicorn (`LOOP_NO_REFRESH=1`, throwaway record file).
- **Users:** 50 at once, each with its own X-Session and X-Forwarded-For, rate limits on.
- **Flow, run twice per user:** page, two scripts, traders, review, halt toggle, rulebook, chat, cap toggle, gate, chat with an order idea.

| Run | p50 | p95 | max | throughput | errors |
|---|---|---|---|---|---|
| Warm, before | 698 ms | 2774 ms | 3897 ms | 46 req/s | 0 |
| Warm, after caching | 174 ms | 825 ms | 1285 ms | 186 req/s | 0 |
| Warm, final commit (machine busier) | 217 ms | 945 ms | 1925 ms | 128 req/s | 0 |
| Cold start, before | 805 ms | 1449 ms | **106.7 s** (review) | 10 req/s | 0 |
| Cold start, after single-flight | 125 ms | 1889 ms | 20.8 s (review) | 44 req/s | 0 |

- **Slow endpoints:**
  - The cap toggle ran the walk-forward court (about 150 ms CPU) on every call.
  - The halt toggle permutation took about 40 ms.
  - The rulebook view's checklist permutation test took 15 to 26 ms.
  - Everything is CPU-bound under the GIL, so these queued behind each other.
- **Fix:** cache the toggle, the checklist measurement and the court verdict for a proposal, keyed by (trader, earlier proposals, multiple). The histories are fixed and every permutation is seeded, so results are identical. Tests compare cached against uncached results, and the trial count still rises with every proposal. **No permutation count was lowered.**
- **Cold start:** 50 visitors each computed the same multi-second review in parallel. Reviews are now single-flight per trader, and unknown ids create no lock.

## 5. Mutation testing (scripts/mutate.py; docs/stress/mutation_results*.json)

25 mutants were applied one at a time:

- 8 in court.py
- 5 in walkforward.py
- 6 in rulebook.py
- 3 in gate.py
- 2 in numberlock.py
- 1 removing escaping in index.html

The script restores the original bytes after each mutant, keeps a backup that survives a hard kill, and refuses to start on a red baseline. **`git diff` is clean.**

**First pass: 17 of 25 killed (68%).** Notes on that number:

- In an aborted first attempt, the pre-existing red test made every mutant look killed. A hard stop of that attempt left one mutant (a train/test overlap in court.py) in the tree. I restored it from git and added the backup and baseline guards to the script.
- In the counted pass, M16 and M19 were killed only by a rate-limit test that depended on machine speed. I froze that test's clock. On the rerun, M16 is killed by the new thread test and M19 by an existing rulebook test.

**Survivors (genuine test gaps):**

| Mutant | What it broke |
|---|---|
| M04, M12 | The underpowered guard in both courts changed from `or` to `and` |
| M06 | Off-by-one split: one trip was in both train and test |
| M07, M09 | **Look-ahead:** the baseline was taken from the whole history (split court) or included the judged chunk (walk-forward) |
| M11 | The permutation never counted a null result (p collapses to 1/1501) |
| M15 | **A REJECTED verdict landed as ACCEPTED, so it could be armed** |
| M23 | Number-lock tolerance widened by 1 |

`tests/test_mutation_guards.py` adds a test for each one. The look-ahead tests multiply the judged trips' sizes by 100 and assert the cap does not move. **Rerun: 10 of 10 killed, so 25 of 25 overall.**

## 6. Degraded mode (tests/test_degraded.py; 6 of 9 fail on the previous commit)

| Failure | Before | After |
|---|---|---|
| Refresher thread raising every call | survived (already fine) | pinned by a test |
| Empty book cache | honest "no recent book" (already fine) | pinned |
| Stale cache | chat said "Estimated cost on the live book" from an old snapshot | chat says the snapshot is stale and unused; the gate already ignored it |
| Broken snapshot | gate and `/api/cost` returned 500 | "no cost estimate" with the reason |
| One wallet CSV missing or unreadable | `/api/traders` 500, **whole first screen dead** | that trader is listed as unavailable with the reason; its routes return 503 with that sentence; the page greys it out and picks another trader; MCP returns isError |
| One corrupt line in the record | `/api/record/entries`, `/counter`, `/day` returned 500 | the bad line is marked; `corrupt_lines` is counted; verify names seq 2; the gate still answers with `record_error` |
| Record location cannot be opened | 500 | 503 with an honest sentence |

## Honest limits

- **Rate limiting:**
  - It is per process only; more than one worker or replica means separate buckets.
  - The Dockerfile's `--forwarded-allow-ips='*'` lets a client spoof X-Forwarded-For, so the per-IP bucket is a speed bump, not a wall. Behind a known proxy, set that option to the proxy's address.
  - `/mcp` is in the general buckets only. Its own cap is 100 rule tries per session.
- **Cold start:** about 24 s of CPU to compute the six reviews, during which a visitor can wait up to about 21 s. Deploy health checks should allow for it, or the reviews should be precomputed at build time.
- **CSP:** styles still need `unsafe-inline` because the pages use style attributes. The script hashes change whenever an inline script is edited. They are computed at start-up, so this needs no maintenance.
- **Number-lock** still cannot see numbers written as words, such as 三百 or "seven thousand". The chat path writes only templates today.
- **Known console error:** /cockpit probes `/verify`. That page does not exist in this build, so Chromium logs one 404 there. The browser test tolerates exactly that one request.
- **Machine:** all numbers come from one Windows machine shared with other sessions. The load test is in-process over localhost, with no network latency and no TLS.
- **Mutation testing:** 25 hand-picked mutants is a sample, not a full mutation analysis.
