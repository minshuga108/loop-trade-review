# Placeholders only Palak can fill

Edit the TEMPLATES (README.template.md, SUBMISSION.template.md), then run `python scripts/render_docs.py` and `python scripts/render_docs.py --check`. Do not edit README.md or SUBMISSION.md directly (check fails on drift).

Already filled from `claims.py`: demo URL (`LIVE_URL` https://loop-trade-review.onrender.com), repo URL (`REPO_URL`), video page (`VIDEO_URL` = LIVE_URL + /video). Change them there, not in the templates.

| Placeholder | Where | What to put |
|---|---|---|
| `[FILL AFTER DEPLOY]` first byte and page weight | SUBMISSION.template.md section 3 | numbers printed by `python scripts/cold_visit.py` against the deployed URL |
| `[FILL: 5 non-team testers ...]` | SUBMISSION.template.md section 3, "Observed with users" | real completion rate and time from the app log for 5 outside testers; otherwise replace with "targeted, not yet observed" |
| `[state which key: hackathon base URL or Alibaba Cloud DashScope]` | SUBMISSION.template.md, "Role of the LLM" | which Qwen key you use. The hosted build currently runs with the model off; if you add no key, say so and delete the Qwen model name |
| Voiceover YouTube link (optional) | submission form / X post | upload the narrated version (script: VIDEO_SCRIPT.md) and paste its link; the silent captioned video already plays at /video |
| X post link | submission form | the public post URL after you post it (must include #BitgetHackathon and @Bitget_AI and quote the announcement) |
| Team lead Bitget UID, sub-theme, form boxes | the submission form | your own entries at submit time |
