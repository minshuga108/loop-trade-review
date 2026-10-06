# Self-assessment against the four Track 3 criteria

Honest, not promotional. Numbers come from the files named in LOSSES.md. Nobody outside the team has used this yet.

| Criterion | What is built | What is weak or missing | Our own judgement |
|---|---|---|---|
| **Feature depth** (data sources and skills, count and effectiveness) | Bitget UTA v3 and website-CSV importers (tested on real rows from other accounts); Bitget public order books and market-state windows for a live cost line; six detectors; walk-forward rule court; versioned rulebook; measured checklist; Rule Gate; weekly report; public append-only record anchored with OpenTimestamps; read-only MCP server ({{mcp.tools}} tools); Bitget tool evidence logged and shown on /evidence: {{evidence.signal}} | Bitget's own MCP data calls returned 503 on 2026-10-05 so nothing depends on them; the demo has one real Bitget export (wallet G) but it is a trading bot's account, not a human trader; no human Bitget trader history | strong on engine depth, honest but thin on Bitget-native data count |
| **Research quality** | every habit tested within the trader; rules judged on unseen trades; trial-count ledger; look-ahead guard that rejects a cheating rule in 100 of 100 planted runs; head-to-head register against re-implementations of two rival review rule sets | false-admission above nominal in some cells; power low at small n; planted traders are simulated | the strongest part, and it publishes its own failures |
| **LUI fluency** | English and Chinese chat, follow-ups, "what would make this wrong", refusals, number-lock, live selftest | blind-set score written by the router's author; one intent per turn; no Qwen-phrased answers (templates only) | good for a deterministic chat, not yet tested by outsiders |
| **Personalized thesis** | rules, checklist and gate come from the trader's own record; different traders get different verdicts for the same order idea | demo traders are {{wallets.text}}, so mostly other people's wallets on another venue; no intent capture on imported history | real in design, borrowed data in the demo |

## Built versus planned
Built: everything in the table's "what is built" column. Planned: real Bitget account import in the public demo; a forward paper record graded on outcomes (the record logs decisions now; outcomes are not yet resolved automatically); scheduled push to Telegram, Feishu and WeChat Work; signed report exports; Agent Hub demo-order proof from the gate; observed test-user data.

## Zero-effect and missing items
Checklist items with no measurable effect are shown as such. Intent-gap and calibration metrics are not shown for imported histories because intent was not stamped before the order.
