# Build progress (honest, weighted; updated each time work lands)

| Part | Weight | Done | Notes |
|---|---|---|---|
| Research and plan (feature list, rival scans and teardowns, data sources, cohort study) | 15 | 15 | finished; rival watch every 12 hours for 3 days |
| Core engine: ledger, habit tests with Holm correction, pricing, walk-forward court, look-ahead guard, planted suite, drift, structural gap, win-rate, register, trend | 15 | 14.5 | wrong-acceptance 0-1 percent, power 19/53/88 percent at 150/300/600 trips (court_results.json) |
| Rulebook, checklist, Rule Gate | 10 | 9.5 | human approval, hash-chained log, measured checklist, live Bitget cost line, context line |
| First screen and pages | 8 | 7.5 | redesigned; cockpit, selftest, record, evidence, import panel |
| Chat: typed QA engine (26 metrics, follow-ups), router v2, number-lock, refusals, Qwen planner with spend caps | 8 | 7 | router 82.5 percent blind on an independent set (87.5 percent after tuning on it, not blind); Chinese gate, cost and label strings added; odd data questions get an honest could-not-parse; QA 96 percent on its held-out set (same author) |
| Weekly report, push, share card, signed export | 6 | 5.5 | push needs a bot token |
| Real Bitget data path | 10 | 6.5 | UTA and CSV adapters on real rows; a real public Bitget export is demo trader G; bring-your-own-export works; no teammate or demo-account history yet |
| Hosting, speed, stress, security, claims check, clean release export | 10 | 8 | all built and tested (1024 tests passed at that time; see README for the current count from the clean release folder); not deployed to a public URL |
| Packaging: video, README, five-part text, X post | 10 | 4 | README, SUBMISSION, VIDEO_SCRIPT, LAUNCH_CHECKLIST written; video, X post, form not done |
| Observed testing with 5 people, final polish | 8 | 0.5 | judge audit round 1 done (22/50 before the fixes); round 2 pending |
| **Total** | **100** | **81** | built about 90 percent, submission-ready about 68 percent |
