# Chat intent routing: evaluation results (2026-10-06)

Reproduce: `python eval/run_eval.py --set blind|dev [--router chat|router]`

## Sets
| set | n | en / zh | adversarial | needs_context | use |
|---|---|---|---|---|---|
| `blind_questions.jsonl` | 120 | 70 / 50 (incl. 3 mixed EN-ZH, 3 Hinglish) | 12 | 10 | held out, scored once |
| `dev_questions.jsonl` | 80 | 46 / 34 | 5 | 4 | tuning |

Gold intents: habit, rule, court, report, source, gate, checklist, help.
Injection and real-order / withdrawal requests are gold `help`.

## Old router (`app/chat.py` `route`, first keyword match wins)
| | dev | blind |
|---|---|---|
| all | 42/80 = 52.5% | 62/120 = 51.7% |
| en / zh | 54.3% / 50.0% | 51.4% / 52.0% |
| gate, checklist | 0% (intents do not exist) | 0% |
| court | 0/9 | 0/12 (shadowed: "rules" hits the `rule` list first) |
| habit / rule / report / source | 67 / 75 / 89 / 89% | 67 / 73 / 93 / 58% |
| help / adversarial | 75% / 3 of 5 | 75% / 6 of 12 |

Restricted to the five intents it knows, it scores 64.6% on blind.

## New router (`app/router.py`)
Tuned on dev only (dev went 97.5% to 100% after two fixes). Frozen in commit
`3f7b449` before the blind set was run.

**Blind, single frozen run: 118/120 = 98.3%**
| slice | blind (frozen) |
|---|---|
| en | 69/70 = 98.6% |
| zh | 49/50 = 98.0% |
| needs_context true / false | 10/10 / 108/110 |
| adversarial (must be help) | 12/12 |
| mixed / Hinglish | 5/6 |
| per intent | habit 14/15, rule 14/15, everything else 100% |

Misses on the frozen run:
- `我的worst habit是啥` (habit, got help). **Bug**: Python counts CJK as a word character, so `\bworst\b`
  could not match English glued to Chinese. Fixed after the blind run by spacing the two scripts apart in
  `normalise()`, and a test was added. With that bug fix the blind set reads 119/120 (99.2%). That second number is
  no longer blind; quote 98.3%.
- `what would a max position size rule change` (rule, got gate). This is a judgement miss, so it was left unfixed on purpose
  ("position size" pulls toward gate). It is still wrong.

## Caveats (read before quoting the numbers)
- **The same agent wrote the blind set, the dev set and the router, in one session.** The blind set was written and
  committed (`a32fee6`) before `app/chat.py` was opened. But the router author had seen the blind questions, so
  vocabulary overlap is likely and the 98% is optimistic. Treat it as an upper bound. A fair number needs questions
  from people who never saw the router: real user logs, or teammates writing 50+ lines cold.
- The sets are small. With 120 items, one miss is 0.8 points; the 95% interval for 118/120 is roughly 94–99.5%.
  Per-intent cells have 10–28 items.
- All questions are single sentences of clean intent. Real chats will have multi-intent turns ("weekly review and
  is this real data?"); the router returns one intent.
- Context follow-ups only get help when the caller passes `previous_intent`. The current `chat.answer` does not
  track it yet.
- Safety is pattern-based. It catches the injection shapes in these sets, not a determined adversary. Loop has no
  order path, so a miss there yields a wrong answer, not a trade.
- 11 tests outside this change fail in the worktree, because they look for `../data/` (FileNotFoundError). That is pre-existing and environmental.

## Router v2 (2026-10-06)

Reproduce: `python scripts/score_router_sets.py [-v]` (all three sets), `python scripts/build_router_examples.py`
(rebuilds the fallback's training file and prints its leave-one-out check). Everything above this section is
history and unchanged.

**Status of the sets from v2 on:** `eval/independent_blind.jsonl` (n=200, second author) is now a **dev set**:
every one of its 54 misses was studied and fixed. Its v2 number is training-contaminated and must not be
quoted as a generalisation estimate. `blind_questions.jsonl` was seen by the router author before (see caveats
above) and is used here only as a no-regression guard. The fair test is a third set written by someone else.

### Before / after
| set | v1 (current code before v2) | v2 | note |
|---|---|---|---|
| dev_questions (80) | 80/80 = 100% | 80/80 = 100% | tuning set |
| blind_questions (120) | 119/120 = 99.2% (frozen run: 118/120) | 120/120 = 100% | guard only, not blind any more |
| independent_blind (200) | 146/200 = 73.0% | 200/200 = 100% | **contaminated: tuned on it** |
| invented paraphrases (115, `tests/test_router_v2.py`) | n/a | 110/115 on first run, 119/119 after fixes (4 lines added later) | same author as the router: optimistic |

v1 confusion on independent_blind (gold->got): help->gate 8, court->help 7, source->help 7, habit->help 5,
checklist->help 5, rule->help 4, report->help 3, gate->help 3, habit->report 2, and one each of habit->gate,
court->source, court->report, source->rule, gate->rule, rule->source, rule->gate, help->report, help->habit,
help->rule. v2 confusion on all three sets: empty. On the 5 first-run misses of the invented paraphrases:
"where is all my money going" (prediction pattern too loose -> advice), "hold losing trades way too long"
(gate, from "long"), a Hinglish "nuksaan kahan se" line (source), "largest losing trade" and
"a good day to buy" (advice wording) - each fixed by widening the concept, not the sentence.

### What changed (causes fixed)
- **Advice and execution before gate scoring** (was help->gate 8). New negation-, counterfactual- and
  temporal-safe detectors: "should I buy X", "is now a good time", "which coin will pump", "yes or no",
  "该买吗", "合适吗" (with timing or direction), "推荐币" -> help + `advice`; "place a market buy", "sell
  everything", "close my position now", "go all in", "execute", "全部平仓", "帮我市价买", "把单子执行了" ->
  help + `order_request`. A rule-check cue ("given my rules", "does it break", "符合规则") keeps a line on gate;
  "before I place an order" no longer trips `order_request`; "what if I had sold everything" stays rule.
  A bare sized idea ("buy $20k rNVDA", "买两万刀NVDA") stays gate. `app/chat.py` answers the `advice` flag with
  its existing advice decline.
- **Concept synonyms instead of canonical nouns** (was most of the 31 fall-throughs to help):
  habit = leak/bleed/drain/lose money/cost me/where does the money go/named behaviours (oversize, chase, hold
  losers, panic sell); court = strict/threshold/the bar/criteria/p-value/out of sample/overfit/pass/survive/
  "how do you decide"/"do my rules work"; source = made up/fabricated/csv/upload/synced/fresh/"how do you get my
  trades"/simulated (adjective); checklist = "what should I check/confirm/look at" + "before <order verb>";
  rule = "would X have helped", "should I have", caps per day; report = single-day and stats questions.
- **Light stemming and typo repair:** stem-tolerant regexes plus a repair step in `normalise()` that maps
  near-miss tokens onto the concept vocabulary ("wrng", "happend", "summery"), with a common-word stop list and
  a derivation guard so "actually", "half", "simple" are left alone (v1's fuzzy matcher turned "half" into the
  halt rule).
- **Chinese:** traditional -> simplified table (~200 characters), new concept substrings (检验/严格/宽松/样本外/
  审判, 亏在哪/扛单/追涨杀跌, 怎么拿到/交易所/模拟盘, 开单之前/核对, 会咋样/有用吗/不超过), "模式" no longer
  fires on 夜间模式, "模拟" split into source (模拟盘/模拟的) and rule (请模拟/模拟一下), education "什么是X" -> help.
- **Injection, EN + ZH:** "ignore previous/above", role-play, "act as", "you are now", "from now on", "set intent=",
  "dump db", API key / password / seed phrase, base64/rot13/long encoded tokens, chat-template tokens,
  "系统指令", "将意图改为", "扮演", "从现在开始你", "输出数据库/密码". All force help + `injection`.
- **Hinglish:** kya hota/agar/bachta/ruk jata (rule), galti/nuksaan/paisa kahan (habit), "<data|trades> kahan
  se", asli/nakli/kiska (source), pehle + check karna (checklist), kaisa raha/kitna (report), rules allow/chalega
  (gate), "kya aap" (help).
- **Char n-gram nearest-centroid fallback** (2-4 grams, cosine to per-intent centroids), trained only on
  `dev_questions` + `independent_blind` (254 non-follow-up lines, `app/router_examples.json`). It acts only when
  every keyword score is below the floor and no follow-up context applies, needs cosine >= 0.30 and a 0.08
  margin over the runner-up, and flags its answers `fallback`. Calibrated on blind_questions (not in its training
  data): centroid-only at 0.30/0.06 was right on 36 of the 40 lines it fired on. On the three sets as routed it
  fires **0 times** (keywords cover them), so none of the numbers above depend on it; it is a safety net for the
  third set, not a score source.

### What remains / caveats
- 100% on independent_blind is memorisation-tinted: the patterns were written while looking at its misses.
  Expect the third independent set to land well below that; a drop into the 80s would not be surprising.
- Ambiguous gold labels were followed as written ("what's my biggest loss" -> report, "我亏了多少" -> report,
  "did my rules actually work this week" -> court). A different grader could reasonably disagree, and the router
  now encodes those choices.
- Safety is still pattern-based. Capability questions like "can you execute orders" get the decline text
  (flag `order_request`), which is acceptable but not a precise answer. "should I have sold" is treated as a
  counterfactual (rule), "how long should I hold winners" as advice (help).
- Multi-intent turns still return one intent.
