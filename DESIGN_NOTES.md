# First-screen redesign (2026-10-06)

The old first screen was a stack of tables and cards: honest, but a stranger needed a minute to find the
one number that mattered. The new one is built so that in ten seconds a judge can read: what this is, whose
data it is, the one finding priced in dollars with its honest verdict, and the next thing to do.

## Files

- `app/static/home.css`: all page styling (tokens, masthead, trader switch, hero, ask, sections, skeleton, degraded state).
- `app/static/home.js`: the page script (was the inline block in index.html). Same globals as before, so
  `rulebook.js` and `cards.js` are untouched; `cards.js` still wraps `render`.
- `app/static/index.html`: a 40-line shell. Script order is now i18n.js, home.js, rulebook.js, cards.js so home.js can
  register its own 中文 strings. One inline script remains (applies the stored theme before paint); its SHA-256 is in the CSP.
- `scripts/redesign_shots.py`: Playwright screenshots used to iterate (desktop 1366x768, phone 400x800, light/dark, EN/ZH, states).

## What the first screen now says, top to bottom

1. Masthead (sticky): wordmark, one-line claim, a mini-nav with anchors (Finding, Chart, Ask, Court, Rulebook, Costs, Report)
   that marks the section in view, "What we got wrong" (-> /cockpit#losses), Cockpit, theme, 中文.
2. Provenance strip: `REAL_PLATFORM_PUBLIC` or `SIM_PLANTED` as a monospace chip, fills -> orders -> round trips, the
   "hand-picked, illustrative, not a Bitget user" label. Nothing is hidden.
3. Trader switch: a compact segmented control (A control ... F simulated) with a one-line caption for the chosen wallet.
4. The one finding (left): headline in serif ("Size after a loss: 1.74x"), the habit verdict and the rule verdict as
   colour + icon + word badges, the held-out dollar effect as the hero number, the whole-history effect with its range,
   one honest sentence, and one primary action (ask the demo question; for an accepted rule, send it to the court and arm it).
5. The rule chart (right): PnL with and without the rule, shaded never-seen part, legend with end values, learned-on and
   never-seen tiles, verdict badge with the court's reason. The default rule is now the 1.5x cap, so the chart's held-out
   number and the finding's hero number are the same number (checked: identical for all six traders).
6. Ask: input and three chips (one Chinese) on the first screen on desktop; on a phone the ask bar is fixed to the bottom
   of the screen and answers appear in the flow and scroll into view. Pending state, error state with "Ask again".
7. Below: Evidence (habits table, rule court), Act (rulebook and gate), Costs, Review tools (cards.js). All ids kept.

Also: loading skeleton (shimmer only without reduced-motion), a degraded-state card when /api/traders or a trader fails
(what the page would show, retry, auto-retry countdown), keyboard focus rings, light/dark tokens with a theme switch,
WCAG AA text colours, system font stacks only (the CSP allows no foreign fonts).

## Chart colours

Validated with the dataviz skill's checker. Light: actual `#8a949c` vs rule `#0f6b63` (normal-vision dE 19.8, CVD 16.2).
Dark: actual was `#7f8d97` (dE 14.7, below the 15 floor); now `#707e88` (dE 18.8, CVD 16.0, contrast >= 3:1).
The grey series fails the chroma floor on purpose: it is the neutral "what happened" baseline; identity is also carried
by the legend words and end values.

## Screenshots

Before: `C:\Users\neon_\bitget\data\redesign\before_desktop_full.png`, `before_phone_full.png`, `before_chinese.png`
(copies of TEAM_SHARE/first_screen_*.png).

After (round 4): `C:\Users\neon_\bitget\data\redesign\after_{desktop,phone}_{light,dark}_{en,zh}_{fold,full}.png`,
plus `after_state_down.png`, `after_state_trader_down.png`, `after_state_skeleton.png`, `after_state_planted_F.png`,
`after_state_control_A.png`, `after_state_chat.png`, `after_phone_light_en_chat.png`.

Measured on the final run: ask input bottom at 735 px (EN) / 706 px (ZH) on a 768 px desktop viewport, with all three
chips inside the fold; on the phone the input is fixed at the bottom. No horizontal scroll at 400 px. No console
errors, warnings or 4xx responses in any shot.

## Iterations (what the screenshots showed and what changed)

1. Round 1: ask input at 910 px (below the fold); the legend swatch for "with the rule" picked up the `.rule` class from
   the rulebook; x-axis labels collided at the cut; the chart's honest line and "suggestive" badge stayed English in 中文.
   Fixed: strip to one row, chart height 300 -> 250, legend class renamed, cut label hidden when crowded, five 中文 patterns
   for the court's reasons, 中文 for the suggestive badge.
2. Round 2: 775 px on desktop; phone input at 935 px. Fixed: secondary action became a text link, verdicts on one row,
   tighter masthead, phone ask bar fixed to the bottom with the Chinese chip second.
3. Round 3: 773 px; underpowered traders showed a big red number as if it were a verdict. Fixed: chart 250 -> 232,
   finding sub-line shortened to one line, muted colour for underpowered money, tiles no longer pushed to the bottom.
4. Round 4: 735 px, chips inside the fold; phone tables now scroll sideways instead of wrapping one word per line.

## Remaining flaws (honest)

- The demo's named task ("I lost money on stock perps last month. What one habit cost me most, is it real, and what rule
  should I arm?") routes to `falsify` in the chat router and answers "nothing to disprove" for wallet B. The hero's
  primary action therefore asks "What is my biggest costly habit?", which routes correctly. The router is not changed here.
- For the default wallet B the headline is "suggestive, not proven" and the rule is rejected: honest, but the first
  impression is a negative result. Wallet F (simulated, labelled) shows the accept path. The order of the switch is unchanged.
- The three chips are only inside the fold at 1366x768 with about 10 px to spare; a browser with a bookmarks bar will cut
  them off. The input stays visible.
- On a phone the fixed ask bar costs 110 px of every screen and hides the Chinese chip's neighbour behind a scroll.
- Dark mode is selected by the same tokens cockpit/record/selftest use; those pages were not restyled, so the
  masthead differs between the home page and the cockpit.
- Chart hover shows date and both values but there is no keyboard equivalent for the tooltip; the figure has an
  aria-label and a `<title>` with the two end values instead.
- The verdict text in the chart and the finding repeats the same sentence for the cap rule (by design: the chart can
  switch to the halt rule, and then they differ).
- The phone "court" screenshot in the script scrolls before smooth scrolling finishes; the full-page phone shots cover it.
