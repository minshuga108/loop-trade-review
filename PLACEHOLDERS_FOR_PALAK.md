# Placeholders only Palak can fill

Edit the TEMPLATES (README.template.md, SUBMISSION.template.md), then run `python scripts/render_docs.py` and `python scripts/render_docs.py --check`. Do not edit README.md or SUBMISSION.md directly (check fails on drift).

Already filled from `claims.py`: demo URL (`LIVE_URL` https://loop-trade-review.onrender.com), repo URL (`REPO_URL`), video page (`VIDEO_URL` = LIVE_URL + /video). Change them there, not in the templates.

| Status | Item | Where | Details |
|---|---|---|---|
| **FILLED** | Live cold-visit latency & page weight | SUBMISSION.template.md section 3 | 1.18 s first byte, 184 KB across 10 assets (`scripts/cold_visit.py`) |
| **FILLED** | 5 non-team testers | SUBMISSION.template.md section 3 | "targeted, not yet observed" (honest institutional standard) |
| **FILLED** | Qwen Key Mode | SUBMISSION.template.md "Role of LLM" | Qwen on for the hosted build (key set on Render; used only for questions the typed engine cannot parse; 1.5 s deadline; deterministic fallback; confirm the status strip shows "Qwen: on" before filling the form) |
| **Optional** | Voiceover YouTube link | submission form / X post | Narrated walkthrough (script: VIDEO_SCRIPT.md); silent captioned demo already live at `/video` |
| **Pending Palak** | Public X post link | submission form | Public post URL quoting announcement with `#BitgetHackathon` and `@Bitget_AI` |
| **Pending Palak** | Team lead Bitget UID & Form | the submission form | Your Bitget UID and submit-time form checkboxes |
