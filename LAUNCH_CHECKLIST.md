# Launch checklist (the parts only the owner can do), in order

Everything below takes the finished product and puts it where judges can reach it. Nothing needs a code change.

## 1. Make a clean public repo (about 10 minutes)
The working folder contains local-only data and old agent history that must NOT be published. Publish a fresh copy:
1. Ask Claude: "make the clean release folder" (it exports only tracked files into `C:\Users\neon_\bitget\release\loop` with one new commit, no old history, no wallet files).
2. On GitHub create an empty **public** repo named for the product (no README/licence from GitHub).
3. In the release folder: `git remote add origin <repo url>` then `git push -u origin main`. (Or say "create the repo" and Claude will do it with your GitHub login.)
4. Check on github.com that the repo has: README.md with the tables, LOSSES.md, DEPLOY.md, no `data/` folder, no `.claude/` folder, no `.venv/`.

## 2. Host the app (about 20 minutes)
Follow DEPLOY.md. Quickest: **Render** (Docker web service) or **Fly.io**. Needs: always-on (one process), health check `/api/health`, port from `$PORT`. Free tiers sleep when idle: use a small paid instance or a pinger for the judging days.
Optional environment variables: `QWEN_API_KEY` (see below), `LOOP_VIDEO_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (weekly push), `LOOP_SIGNING_KEY` (signed report export).
After it is up, run: `python scripts/cold_visit.py https://YOUR-URL --browser` and keep the output.

## 3. Reset the public record before launch
The record counts decisions made on the site. Test traffic from development is in it. Before you share the link, ask Claude: "reset the public record and anchor day zero". Then the counter starts honest from launch day.

## 4. Record the 3-minute walkthrough
Use VIDEO_SCRIPT.md on the live URL. Upload as a public YouTube video (or an X post). Put the link in README line 1 (`<VIDEO URL>`), set `LOOP_VIDEO_URL`, and use it in the form.

## 5. Fill the placeholders and re-render
Replace `<DEMO URL>`, `<VIDEO URL>`, `<REPO URL>` in README.template.md and SUBMISSION.template.md, then `python scripts/render_docs.py` and `python scripts/render_docs.py --check`.

## 6. Qwen (optional, product runs without it)
Best: a normal Alibaba Cloud DashScope key as `QWEN_API_KEY` on the host (never in the repo). The hackathon credit is for coding tools. If you use no key, say so in "Role of the LLM" ("Qwen off: template path").

## 7. X post
Use the draft in SUBMISSION.md. It must include `#BitgetHackathon` and `@Bitget_AI` and quote https://x.com/Bitget_AI/status/2100519318824055159. Post it publicly and keep the URL for the form.

## 8. Five test users (for the form's "test users" metric)
Ask 5 people outside the team to open the link and do the 5 tasks listed in SUBMISSION.md part 3. Write down completion and time honestly; report n=5 as observed. If not done, say "targeted, not yet observed".

## 9. The form
Open the live Google Form. Sub-theme field: type exactly `Review & Self-Evolution`. Project description in the five parts from SUBMISSION.md. Materials links one per line. Team lead Bitget UID. Submit, then open every link logged out to confirm.

## 10. After submitting
Do not redeploy during judging except for logged hotfixes. Keep the cold-visit check green. Claude can keep watching rivals and fixing small things; ask before any change that touches the live site.
