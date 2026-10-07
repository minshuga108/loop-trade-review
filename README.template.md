# Loop: trade review that tests its own rules before you trust them

**Your Bitget fills in. Your costly habits priced in dollars, court-tested on your own trades, armed as rules before your next order.**

Bitget AI Base Camp Hackathon S2 · Track 3 (AI Trading Desk) · sub-theme **Review & Self-Evolution** (post-trade review and self-improvement)

Live demo: `{{url.live}}` (no login, no key) · 3-minute walkthrough: `{{url.video}}` · Judge cockpit: `{{url.live}}/cockpit`

> **In short.** Loop reviews a trader's finished trades in paper mode only: it places no orders and gives no financial advice. {{court.real_acceptance}}; two stricter checks do not confirm those accepted rules yet (VALIDATION.md finding 3). On simulated traders with 300 trips, the court caught a real leak {{court.power_300}} of the time.
>
> **Read this before judging.** Loop reviews a trader's past fills. It places no orders and has no write access. Its demo histories are {{wallets.text}}, hand-picked and illustrative (plus one clearly labelled simulated trader, F). Wallet G is a real Bitget export but a trading bot's account, so we still have no human Bitget trader to show. The importers for Bitget's own formats (UTA v3 API and the website CSV export) are tested on real Bitget rows, but we do not yet have a real Bitget trader's history to show. {{court.real_acceptance}}. Everything else tested on real wallets was not accepted, and that is the honest result. On {{court.sims}} simulated traders per cell the court wrongly accepted a rule for a trader with no leak {{court.fa_null_600}} of the time at 600 trips on independent simulated data (a trip is a completed round-trip trade). Stress results, including serially dependent returns, are in VALIDATION.md section 4b. The court also caught a real costly leak {{court.power_300}} of the time at 300 trips. Everything we got wrong is listed in [LOSSES.md](LOSSES.md).

## What a judge can check in two minutes

| You look for | Where it is answered | How to check it |
|---|---|---|
| **Feature depth** (data sources and skills, and whether they work) | Bitget fills (UTA v3 API and website CSV importers), Bitget public order books (live cost line), Bitget market-state windows; a read-only MCP server ({{mcp.tools}} tools); each source's state is shown live | open `/cockpit` (source strip); `GET /api/sources` |
| **Research quality** | Every habit tested within the trader; rules learned on early trades and judged on later ones (walk-forward); every proposal counted; a planted-rule suite that must reject a look-ahead cheat | `/cockpit` → losses and calibration; `python scripts/measure_court.py` |
| **LUI fluency** | Chat in English and 中文, follow-ups, "what would make this wrong", refusal of advice and order requests; every number is locked to a computed fact | `/` → Ask; `/selftest` |
| **Personalized thesis** | Rules, checklist and the gate are built from the trader's own record; the same order idea gets a different verdict for a different trader | `/` → pick Wallet A, then Wallet F → Check "Buy $20k rNVDA" |

## What it does, in one loop

1. **Import** fills (Bitget UTA v3, Bitget website CSV, public Hyperliquid wallets) → orders → round trips, fees included; unknown layouts are refused loudly.
2. **Detect** habits (size after a loss, holding losers, busiest days, re-entry after a loss) with a within-trader permutation test; thin data says "not enough trades yet".
3. **Price** the habit in dollars from measured fills, with a range, and show the required win rate at your real costs.
4. **Court-test** a proposed rule on trades it never saw (walk-forward, every proposal counted, a look-ahead guard).
5. **Arm** it with one click (paper only), keep a versioned rulebook with a hash-chained log, and get a checklist whose effect is measured.
6. **Gate** your next order idea against your armed rules, with a live Bitget order-book cost line. It never places an order.
7. **Review weekly** (复盘 template, "what changed since last time", assumed and missing).

## Verify in 60 seconds

```
curl -s {{url.live}}/api/health                         # {"ok":true,"mode":"read-only","writes":false}
curl -s {{url.live}}/api/review/B | python -m json.tool  # every number on the first screen, computed from fills
curl -s {{url.live}}/api/record/verify                   # hash chain of the public record: "intact"
curl -s -X POST {{url.live}}/mcp -H "Content-Type: application/json"      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'   # the {{mcp.tools}} read-only tools
python scripts/render_docs.py --check                  # this README matches its template and the numbers computed now
```

## Honest boundaries

- The public demo ships one real Bitget futures export (wallet G, a trading bot's DOGE trades; its format omits opening fees) and an Import panel where a visitor can load their own Bitget CSV; that import is parsed in the session only and not stored. No human Bitget trader's account is in the demo, and no keys are accepted on the site.
- Demo histories are other people's public wallets on another venue. Behaviour patterns are venue-independent; execution costs are not, which is why the cost line uses Bitget books only.
- "Underpowered" is the normal answer at 40 to 80 trades.
- Paper fills are conservative and calibrated against recorded books, not equal to live trading.
- The chat router: {{router.independent2}} on a second independent set at first scoring; it was tuned on afterwards ({{router.independent2_after}}, no longer blind).
- The chat's blind-set score was written by the router's author; read the caveat in LOSSES.md.
- Independent validation ([VALIDATION.md](VALIDATION.md), dev-only tooling): our permutation p-values agree with scipy on {{validation.p_agree}} tests, Holm with statsmodels on {{validation.holm_agree}}, and our court verdicts with a re-implementation on {{validation.court_agree}}; one bootstrap CI upper endpoint is noisier than we show (listed as a finding). The habit detector flags a planted 1.5x size-up after a loss {{validation.detector_power_15_300}} of the time at 300 trips but a 1.25x one only {{validation.detector_power_125_300}} of the time. On the one real wallet where the court accepted rules ({{validation.real_accepted_wallets}}), the PBO and deflated-Sharpe views do not confirm it; the page says so.

## Run it

```
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --port 8000
.venv/Scripts/python -m pytest -q          # {{tests.collected}} tests collected
python scripts/render_docs.py --check   # fails if a doc differs from its template or from numbers computed now
```

Deploying: see [DEPLOY.md](DEPLOY.md). MCP server: see docs/MCP.md once merged. The submission text is in [SUBMISSION.md](SUBMISSION.md).

Licence: MIT for our code. Third-party data and fixtures keep their own licences (see data/bitget_samples/SOURCES.md).
