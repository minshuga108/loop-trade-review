# Deploying Loop (always-on, no login, no key)

Loop is one FastAPI process with a background thread (the Bitget book refresher) and in-memory per-session sandboxes. It needs a host that keeps one container running. Serverless/function hosts (Vercel, Netlify functions) are a poor fit: the refresher thread and the sandboxes would vanish between requests.

## 0. Before any host

1. Owner, once: add the judge routes to `app/main.py`:
   ```python
   from . import judge
   app.include_router(judge.router)
   ```
2. Ship the sample histories (only the wallets the app uses, anonymised):
   ```
   python scripts/prepare_samples.py --src ../data/trader_samples
   ```
   This writes `deploy_data/trader_samples/` (five CSVs plus `SOURCES.md`). Order ids are replaced by order-preserving ranks, `summary.json` (full addresses) is never copied, and the script re-runs the ledger on each copy and refuses to write if any trip differs. Commit `deploy_data/` so git-based hosts can build it. The image places it at `/srv/data/trader_samples`, which is where `app/service.py` looks (`parents[2]/data/trader_samples`). The UI shows aliases (Wallet A..F) only.
3. Build and run locally:
   ```
   docker build -t loop .
   docker run --rm -p 8000:8000 loop
   python scripts/cold_visit.py http://127.0.0.1:8000 --browser
   ```

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `PORT` | set by most hosts | Port uvicorn listens on (default 8000; Hugging Face needs 7860). |
| `QWEN_API_KEY` | no | Turns on Qwen for unclear chat sentences only. Without it the template path answers everything. Put it in the host's secret store, never in the image or repo. |
| `QWEN_BASE_URL`, `QWEN_MODEL` | no | Override the OpenAI-compatible endpoint and model. |
| `LOOP_NO_REFRESH` | no | Any value stops the background refresher (no calls to api.bitget.com). Then the cost line says "no recent book" and `/api/sources` shows 0 endpoints reached. Leave it unset in production. |
| `LOOP_VIDEO_URL` | no | Walkthrough video link shown on `/cockpit`. |

Health check path: **`/api/health`** (returns `{"ok": true, "mode": "read-only", "writes": false}`). The Dockerfile also has a `HEALTHCHECK` on it.

Run one worker only (the Dockerfile does): the sandboxes and the selftest state live in memory, so several workers would give a judge a different sandbox on each request.

## Render (Web Service, Docker)

1. New → Web Service → connect the public repo → Runtime: **Docker** (Render finds the `Dockerfile`).
2. Instance type: Free works but **sleeps after about 15 minutes idle**, and the first visit after that waits for a cold start, which fails the 1.5 s first-byte gate. For judging use the smallest paid instance, or keep it warm (step 5).
3. Health Check Path: `/api/health`.
4. Environment: add `QWEN_API_KEY` as a secret only if wanted. Render sets `PORT`.
5. If staying on Free: an external uptime pinger hitting `/api/health` every 5-10 minutes keeps it awake (check Render's current terms first).

## Fly.io

```
fly launch --no-deploy            # pick a name and region near the judges; say no to databases
```
Edit the generated `fly.toml`:
```toml
[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "off"      # always on: no cold start for a judge
  auto_start_machines = true
  min_machines_running = 1

[[http_service.checks]]
  grace_period = "40s"
  interval = "30s"
  method = "GET"
  path = "/api/health"
  timeout = "5s"
```
Then `fly secrets set QWEN_API_KEY=...` (optional) and `fly deploy`. Use one machine (`fly scale count 1`). A shared-cpu-1x with 512 MB is the floor; the first review of a wallet is CPU-heavy, so 1 GB is safer.

## Railway

1. New Project → Deploy from GitHub repo. Railway detects the `Dockerfile`.
2. Settings → Networking → Generate Domain. Railway sets `PORT`.
3. Settings → Deploy → Healthcheck Path `/api/health`; keep replicas at 1; leave serverless/app sleeping **off**.
4. Variables: `QWEN_API_KEY` (optional).
Railway's free allowance is a small monthly credit, not a free always-on tier; check the balance covers the judging window.

## Hugging Face Spaces (Docker)

1. Create a Space → SDK **Docker** → public.
2. Push this repo to the Space (or link it). In the Space `README.md` front matter add:
   ```yaml
   sdk: docker
   app_port: 7860
   ```
   and under Settings → Variables add `PORT=7860` (the Dockerfile reads `$PORT`).
3. Secrets: `QWEN_API_KEY` (optional).
4. Free CPU Spaces **sleep after a period without traffic** (48 h at the time of writing) and the cold start is slow. Upgraded hardware can be set to never sleep. The container already runs as uid 1000, which Spaces requires.

## Plain VPS (any provider, 1 vCPU / 1 GB)

```
sudo apt-get install -y docker.io
git clone <repo> loop && cd loop
python3 scripts/prepare_samples.py --src /path/to/data/trader_samples   # or use the committed deploy_data/
sudo docker build -t loop .
sudo docker run -d --name loop --restart unless-stopped -p 127.0.0.1:8000:8000 \
     -e QWEN_API_KEY="${QWEN_API_KEY:-}" loop
```
Put Caddy in front for HTTPS (`/etc/caddy/Caddyfile`):
```
loop.example.com {
    reverse_proxy 127.0.0.1:8000
}
```
Check with `curl -fsS https://loop.example.com/api/health`.

## After any deploy

```
python scripts/cold_visit.py https://YOUR-URL --browser
```
It prints pass/fail for first byte (1.5 s), first-screen weight (under 1 MB), no login, `/api/health`, time to first trader card and curve on desktop and a 400 px phone, and horizontal scroll on `/`, `/cockpit` and `/selftest`. Then open `/cockpit` and confirm the source strip shows Bitget endpoints reached (needs a minute after start for the first refresh).

## Cold starts: snapshot and keep-warm

- The first screen falls back to `app/static/snapshot.json` (traders, reviews and both rule toggles, pre-rendered from the engine) when `/api/traders`, `/api/review/*` or `/api/toggle/*` fail or return 5xx, and shows "Live server unreachable, showing snapshot from DATE". Regenerate and commit it after any engine or data change: `python scripts/make_snapshot.py`.
- Optional keep-warm (nothing external is set up for you): run `python scripts/keep_warm.py` from your own machine; it calls `GET /api/health` every 10 minutes (`--every SECONDS`, `--once` for a single timed check). Render free instances sleep after about 15 idle minutes.
- Demo video: `deploy_data/media/loop_demo.webm` (about 16 MB; no ffmpeg here to re-encode) is served at `/media/loop_demo.webm` with Range support, and the `/video` page plays it with a transcript.

Do not redeploy during the judging window except for logged hotfixes.
