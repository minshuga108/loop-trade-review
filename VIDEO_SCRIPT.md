# 3-minute walkthrough: shot list and narration (for the owner's screen recording)

Goal: the required "run record" (one complete research task, question to actionable insight) in 3 minutes or less, with no cuts and no prepared state. Record the live site in a clean browser window (1366x768 or larger), light theme, cursor visible, microphone on. Say what numbers mean in plain words. Do not read the screen aloud; explain the idea.

**The one question the video answers:** "I lost money on stock perps last month. What one habit cost me most, is it real, and what rule should I arm?"

| Time | On screen | Say |
|---|---|---|
| 0:00-0:12 | Open the site. Wallet B is already shown. Point at "In one look". | "This is Loop. It reviews a trader's own trades. This is a public wallet, hand-picked and labelled illustrative. In one look: one habit, what it cost in dollars, and what the rule court decided." |
| 0:12-0:35 | Click the first chat chip ("What is my biggest costly habit?"). Click the number-locked details. | "I ask in plain words. The answer is computed from the fills, not written by a model: every number is locked to a computed fact. The pattern is sizing up after a loss, with a range that is honest about how little data there is." |
| 0:35-1:05 | Scroll to the profit-and-loss chart. Toggle the rule on and off. Read the two boxes. | "Here is what a rule would have changed. On the trades it was built from it looks good. On trades it never saw it does not hold up, so the court says no. A tool that always says yes is fooling itself." |
| 1:05-1:35 | Switch to Wallet F (simulated, labelled). Click Test it on "cap at 1.5x median". Show ACCEPTED. Click Arm. | "To show what a pass looks like, this simulated trader has a costly habit built in. The rule is tested on later trades, every proposal is counted, and this one passes. Nothing is armed until I click. Now it is guarding my orders. Paper only." |
| 1:35-2:10 | In Check an order idea type "Buy $200k RNVDA", tick "my last trade was a loss", press Check. Show BLOCKED, the checklist item and the Check line. Then untick and check again. | "I ask the gate about an idea. Last trade lost and this size breaks my own rule, so it is blocked, with a checklist built from my own losses and a live Bitget order-book cost. The gate never places an order." |
| 2:10-2:30 | Ask in the chat: "what would make this wrong?" then "我最大的坏习惯是什么？" | "I can ask what would make this wrong, and in Chinese. It tells me what it did not test." |
| 2:30-2:50 | Chat: "show my weekly review". Scroll the report: priority finding, rule court, tomorrow's plan, what changed, assumed and missing. | "The weekly review follows the fupan template: what happened, the priority finding, what would make it wrong, tomorrow's plan, what changed, and what we assumed or are missing." |
| 2:50-3:00 | Open /cockpit or LOSSES.md. | "Everything we got wrong is public. The court admits more false rules than it should in some cases, and power is low on short histories. That is why the honest answer is often 'not enough trades yet'." |

Checklist before recording: the demo URL loads with no login; Wallet B is the default; Wallet F is labelled SIMULATED; the browser zoom is 100%; no real account, key or private data is on screen; close other tabs. After recording: upload as public YouTube or an X post; put the link on README line 1 and in the form.

Automated silent cut: `.venv\Scripts\python.exe scripts\record_demo.py` starts a sandboxed local copy (temp record, no real data touched), drives this flow in Chromium at 1280x720 with on-screen captions, and writes `C:\Users\neon_\bitget\demo_video\loop_demo.webm` (about 3:25), `captions.txt` (narration lines to read aloud) and scene-end frames. It adds an .mp4 only if ffmpeg is already installed. It covers the Wallet B and F flow plus a Bitget CSV import and the evidence page.
