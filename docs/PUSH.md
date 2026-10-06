# Weekly push (Telegram, Feishu, WeChat Work)

`engine/push.py` sends the same number-locked weekly digest the web report shows. It is delivery only: no account access, no orders, no rule changes.

Set only the channels you want (environment variables, never in the repo):

| Channel | Variables |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN` (from @BotFather), `TELEGRAM_CHAT_ID` |
| Feishu | `FEISHU_WEBHOOK` (custom bot URL), optional `FEISHU_SECRET` for signed bots |
| WeChat Work | `WECOM_WEBHOOK` (group robot URL) |

Run: `python scripts/push_weekly.py B --lang en --link https://YOUR-DEMO-URL`
With no channel configured it prints the digest and does nothing else (dry run).

Schedule weekly with cron, or a GitHub Actions workflow:
```yaml
on: { schedule: [{ cron: "0 1 * * 1" }], workflow_dispatch: {} }
jobs: { push: { runs-on: ubuntu-latest, steps: [ {uses: actions/checkout@v4}, {uses: actions/setup-python@v5, with: {python-version: "3.12"}}, {run: pip install -r requirements.txt}, {run: python scripts/push_weekly.py B --link ${{ vars.DEMO_URL }}, env: {TELEGRAM_BOT_TOKEN: "${{ secrets.TELEGRAM_BOT_TOKEN }}", TELEGRAM_CHAT_ID: "${{ secrets.TELEGRAM_CHAT_ID }}"}} ] } }
```
The public demo uses fixed public histories, so this pushes a demo digest. A real user's weekly push would be built from their own import.
