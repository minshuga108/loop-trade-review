// Review cards: trade replay, trend and drift, rule decay, ledger drift, structural gap sandbox,
// intent sandbox, report export and share card. Loaded after index.html's inline script, rulebook.js
// and i18n.js; uses their globals ($, esc, usd, badge, detName, current, HDR, render, bookAction, loadBook,
// ZH_EXACT, ZH_PATTERNS). Every number shown comes from an API response; nothing is computed for display
// beyond formatting.
(function () {
  const ea = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const tx = (s) => ea(s);
  const ut = (ms) => (ms == null ? "–" : new Date(ms).toISOString().slice(0, 16).replace("T", " "));
  const day = (ms) => (ms == null ? "–" : new Date(ms).toISOString().slice(0, 10));
  const nf = (x, d = 2) => (x == null || x !== x ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: 0 }));
  const sgn = (x, d = 2) => (x == null ? "–" : (x >= 0 ? "+" : "-") + nf(Math.abs(x), d));
  const rx = (x) => (x == null ? "–" : Number(x).toFixed(2) + "x");
  const pc = (x, d = 1) => (x == null ? "–" : (100 * x).toFixed(d) + "%");
  const hold = (ms) => (ms < 3600e3 ? Math.max(1, Math.round(ms / 60e3)) + " min" : ms < 48 * 3600e3 ? (ms / 3600e3).toFixed(1) + " h" : (ms / 86400e3).toFixed(1) + " d");
  const cls = (x) => (x > 0 ? "cpos" : x < 0 ? "cneg" : "");
  const CB = {
    KEEP: ["b-ok", "✔ still earning its keep"], RETIRE: ["b-warn", "▲ check says retire"], UNDERPOWERED: ["b-grey", "◌ not enough trades yet"],
    RECONCILED: ["b-ok", "✔ reconciled"], UNEXPLAINED: ["b-warn", "▲ unexplained residual"], NO_RECORDS: ["b-grey", "◌ no records for this wallet"],
    ALARM: ["b-warn", "▲ drift alarm"], NO_ALARM: ["b-grey", "● no drift alarm"], CHANGE_DETECTED: ["b-warn", "▲ change detected"],
    NO_CHANGE_DETECTED: ["b-grey", "● no change detected"], MEASURED: ["b-ok", "✔ measured"], NOT_ENOUGH: ["b-grey", "◌ not enough entries yet"],
    NOT_TRIGGERED: ["b-grey", "○ stop not reached"], HONOURED: ["b-ok", "✔ stop honoured"], BEHAVIOURAL_BREACH: ["b-bad", "✖ behavioural breach"],
    STRUCTURAL_GAP: ["b-warn", "▲ structural gap"], VERIFIED: ["b-ok", "✔ verified: unchanged since export"], ALTERED: ["b-bad", "✖ altered after export"],
    UNSIGNED: ["b-grey", "◌ unverified: no signature"], KEY_UNAVAILABLE: ["b-grey", "◌ cannot check: server has no key"], OTHER_KEY: ["b-warn", "▲ signed with another key"],
    REFUSED: ["b-grey", "■ refused"], OK: ["b-ok", "✔ balances add up"], GAPS: ["b-warn", "▲ balance gap found"],
  };
  const cb = (s) => { const [c, t] = CB[s] || ["b-grey", s]; return `<span class="badge ${c}">${tx(t)}</span>`; };
  const TAG = { after_loss: "after a loss", losing: "losing trip", busiest_day: "busiest day", reentry: "re-entry", revenge: "revenge re-entry" };
  const C = { tid: null, review: null, habit: "size_after_loss" };
  const get = async (u, opt) => { const r = await fetch(u, Object.assign({ headers: HDR }, opt || {})); const j = await r.json().catch(() => ({})); return { ok: r.ok, j }; };

  // ---------------------------------------------------------------- small SVG charts (one y axis each)
  function frame(W, H, pad, y0, y1, ticks, fmt, logY) {
    const T = (v) => (logY ? Math.log(v) : v);
    const Y = (v) => pad.t + (1 - (T(v) - T(y0)) / (T(y1) - T(y0) || 1)) * (H - pad.t - pad.b);
    const g = ticks.map((v) => `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--line)" stroke-dasharray="2 4"/>` +
      `<text x="${pad.l - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${fmt(v)}</text>`).join("");
    return { Y, g };
  }
  function lineChart(series, opts) {
    const W = 900, H = opts.h || 200, pad = { l: 58, r: 12, t: 16, b: 24 };
    const all = series.flatMap((s) => s.pts);
    if (!all.length) return "";
    const xs = all.map((p) => p[0]), x0 = Math.min(...xs), x1 = Math.max(...xs);
    const ys = all.map((p) => p[1]).concat(opts.hline ? [opts.hline.y] : []).concat(opts.zero ? [0] : []);
    let y0 = Math.min(...ys), y1 = Math.max(...ys); if (y1 === y0) y1 = y0 + 1;
    const X = (x) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
    const { Y, g } = frame(W, H, pad, y0, y1, [y0, (y0 + y1) / 2, y1], opts.fmt || ((v) => nf(v, 1)));
    const path = (pts) => pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
    const hl = opts.hline ? `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(opts.hline.y)}" y2="${Y(opts.hline.y)}" stroke="var(--bad)" stroke-width="1.5" stroke-dasharray="6 4"/>` +
      `<text x="${W - pad.r}" y="${Y(opts.hline.y) - 5}" text-anchor="end" font-size="11" fill="var(--muted)">${tx(opts.hline.label)}</text>` : "";
    const zl = opts.zero ? `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--muted)" stroke-width="1"/>` : "";
    const lines = series.map((s) => `<path d="${path(s.pts)}" fill="none" stroke="${s.color}" stroke-width="2" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""}><title>${tx(s.label)}</title></path>`).join("");
    const hits = series.flatMap((s) => s.pts.filter((_, i) => i % Math.max(1, Math.ceil(s.pts.length / 60)) === 0 || i === s.pts.length - 1)
      .map((p) => `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="6" fill="transparent"><title>${tx(s.label)} · ${day(p[0])} · ${(opts.fmt || ((v) => nf(v, 2)))(p[1])}</title></circle>`)).join("");
    const legend = series.length > 1 ? `<div class="crow" aria-hidden="true">${series.map((s) => `<span class="cnote"><svg width="22" height="8" style="display:inline;width:22px"><line x1="0" x2="22" y1="4" y2="4" stroke="${s.color}" stroke-width="2" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""}/></svg> ${tx(s.label)}</span>`).join("")}</div>` : "";
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${ea(opts.aria)}">${g}${zl}${hl}${lines}${hits}
      <text x="${pad.l}" y="${H - 6}" font-size="11" fill="var(--muted)">${day(x0)}</text><text x="${W - pad.r}" y="${H - 6}" text-anchor="end" font-size="11" fill="var(--muted)">${day(x1)}</text></svg>${legend}`;
  }

  // ---------------------------------------------------------------- mount
  const _render = render;
  render = function (r, t) { _render(r, t); try { mount(r); } catch (e) { console.error("cards", e); } };   // eslint-disable-line no-global-assign
  if (typeof bookAction === "function") {
    const _ba = bookAction;
    bookAction = async function (a, rid) { await _ba(a, rid); loadDecay(); };   // eslint-disable-line no-global-assign
  }

  function mount(r) {
    C.tid = r.trader.id; C.review = r;
    addOpenButtons(r);
    const host = document.createElement("div");
    host.id = "cards";
    host.innerHTML = `
    <h2 class="cards-h">Review tools</h2>
    <div class="card scroll" id="c-replay"><h2>Open the trades</h2><p class="cnote">Pick "Open the trades" next to a habit above to see the round trips it was measured on.</p><div id="c-replay-body"></div><div id="c-trip"></div></div>
    <div class="card" id="c-trend"><h2>Trend and drift</h2>
      <div class="crow"><label class="cnote" for="c-habit">Habit:</label><select id="c-habit" class="cbtn"><option value="size_after_loss">Size after a loss</option><option value="hold_asymmetry">Holding losers longer than winners</option></select></div>
      <div id="c-trend-body"><p class="cnote">Computing…</p></div></div>
    <div class="card" id="c-decay"><h2>Is an armed rule still earning its keep?</h2><div id="c-decay-body"></div></div>
    <div class="cards-grid">
      <div class="card scroll" id="c-ledger"><h2>Ledger drift: does the balance add up?</h2><div id="c-ledger-body"><p class="cnote">Loading…</p></div></div>
      <div class="card" id="c-gap"><h2>Stop missed, or jumped by the market?</h2><div id="c-gap-body"></div></div>
    </div>
    <div class="card" id="c-intent"><h2>Plan before the order: intent sandbox</h2><div id="c-intent-body"></div></div>
    <div class="cards-grid">
      <div class="card" id="c-export"><h2>Export this review</h2><div id="c-export-body"></div></div>
      <div class="card" id="c-share"><h2>Share card</h2><div id="c-share-body"></div></div>
    </div>`;
    $("#main").appendChild(host);
    $("#c-habit").value = C.habit;
    $("#c-habit").addEventListener("change", (e) => { C.habit = e.target.value; loadTrend(); });
    loadTrend(); loadDecay(); loadLedger(); gapForm(); loadIntent(); exportCard(); shareCard();
  }

  // ---------------------------------------------------------------- 1. replay
  function addOpenButtons(r) {
    const tbl = [...document.querySelectorAll("#main table")].find((t) => t.querySelector("thead th") && t.querySelector("thead th").textContent.trim() === "Habit" || t.querySelector("thead th") && t.querySelector("thead th").textContent.trim() === "习惯");
    if (!tbl) return;
    tbl.querySelector("thead tr").insertAdjacentHTML("beforeend", "<th>Trades</th>");
    tbl.querySelectorAll("tbody tr").forEach((tr, i) => {
      const f = r.findings[i]; if (!f) return;
      tr.insertAdjacentHTML("beforeend", `<td><button type="button" class="copen" data-det="${ea(f.detector)}">Open the trades</button></td>`);
    });
    tbl.addEventListener("click", (e) => { const b = e.target.closest("button[data-det]"); if (b) openTrades(b.dataset.det); });
  }

  async function openTrades(det) {
    const body = $("#c-replay-body"); if (!body) return;
    $("#c-trip").innerHTML = "";
    body.innerHTML = '<p class="cnote">Loading…</p>';
    $("#c-replay").scrollIntoView({ behavior: "smooth", block: "start" });
    const { ok, j } = await get(`/api/trips/${C.tid}?finding=${encodeURIComponent(det)}&limit=25`);
    if (!ok) { body.innerHTML = `<p class="err">${tx(j.detail || "error")}</p>`; return; }
    const rows = j.rows.map((x) => `<tr data-i="${x.index}" tabindex="0"><td>${tx(x.symbol)}</td><td class="n">${ut(x.t_open_ms)}</td><td class="n">${hold(x.hold_ms)}</td><td>${x.side === "buy" ? "long" : "short"}</td>
      <td class="n">${nf(x.first_order_notional, 0)}</td><td class="n ${cls(x.net_pnl)}">${sgn(x.net_pnl)}</td>
      <td><span class="ctags">${x.tags.filter((g) => g !== j.tag).map((g) => `<span class="ctag">${tx(TAG[g] || g)}</span>`).join("")}</span></td></tr>`).join("");
    body.innerHTML = `<p><b>${tx(detName[det] || det)}</b></p>
      <p class="cnote"><span>Trips in this group:</span> <b>${j.total}</b> · <span>showing the worst net results first:</span> <b>${j.rows.length}</b></p>
      <table class="ctable"><thead><tr><th>Symbol</th><th>Opened (UTC)</th><th>Held</th><th>Side</th><th>First order (USD)</th><th>Net result (USD)</th><th>Also tagged</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="cnote">${tx(j.note)}</p><p class="cnote">Pick a row to see its fills.</p>`;
    const tb = body.querySelector("tbody");
    const pick = (tr) => { if (!tr) return; tb.querySelectorAll("tr").forEach((x) => x.classList.toggle("sel", x === tr)); loadTrip(+tr.dataset.i); };
    tb.addEventListener("click", (e) => pick(e.target.closest("tr[data-i]")));
    tb.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(e.target.closest("tr[data-i]")); } });
  }

  async function loadTrip(i) {
    const el = $("#c-trip"); if (!el) return; el.innerHTML = '<p class="cnote">Loading…</p>';
    const { ok, j } = await get(`/api/trip/${C.tid}/${i}`);
    if (!el.isConnected) return;                       // the page was re-rendered (trader switch) while this was loading
    if (!ok) { el.innerHTML = `<p class="err">${tx(j.detail || "error")}</p>`; return; }
    const t = j.trip;
    const fr = (f) => `<tr><td class="n">${ut(f.t_ms)}</td><td>${f.side}</td><td>${f.is_open ? "opens" : "closes"}</td><td class="n">${nf(f.price, 6)}</td><td class="n">${nf(f.size, 4)}</td><td class="n">${nf(f.notional, 2)}</td><td class="n">${nf(f.fee, 4)}</td><td class="n ${cls(f.realized_pnl)}">${sgn(f.realized_pnl)}</td></tr>`;
    const head = `<thead><tr><th>Time (UTC)</th><th>Side</th><th>Opens or closes</th><th>Price</th><th>Size</th><th>Notional (USD)</th><th>Fee</th><th>Realised</th></tr></thead>`;
    const MAXF = 12;
    const fills = !j.fills.length ? `<p class="cnote">${tx(j.fills_note)}</p>` :
      `<p class="cnote"><span>Fills in this trip:</span> <b>${j.fills.length}</b></p><table class="ctable">${head}<tbody>${j.fills.slice(0, MAXF).map(fr).join("")}</tbody></table>` +
      (j.fills.length > MAXF ? `<details><summary class="cnote"><span>Show the other fills:</span> <b>${j.fills.length - MAXF}</b></summary><table class="ctable">${head}<tbody>${j.fills.slice(MAXF).map(fr).join("")}</tbody></table></details>` : "");
    let chart = `<p class="honest">${tx(j.candles_note)}</p>`;
    if (j.candles) {
      const pts = j.candles.rows.map((c) => [c[0], c[4]]);
      chart = lineChart([{ pts, color: "var(--accent)", label: "candle close" }], { aria: "Price path during the trip from stored candles", fmt: (v) => nf(v, 4), h: 160 }) +
        `<p class="cnote"><span>MAE:</span> <b>${pc(j.mae_frac, 2)}</b> · <span>MFE:</span> <b>${pc(j.mfe_frac, 2)}</b></p><p class="cnote">${tx(j.candles_note)}</p>`;
    }
    el.innerHTML = `<h2 style="margin-top:14px">Trip</h2><p class="cnote"><b>${tx(t.symbol)}</b> · ${ut(t.t_open_ms)} → ${ut(t.t_close_ms)} · <span>net result</span> <b class="${cls(t.net_pnl)}">${sgn(t.net_pnl)}</b> · <span class="clabel">${tx(t.provenance)}</span></p>${fills}${chart}`;
  }

  // ---------------------------------------------------------------- 2. trend and drift
  function windowChart(ws) {
    const m = ws.filter((w) => w.status === "MEASURED");
    const W = 900, H = 220, pad = { l: 58, r: 12, t: 16, b: 36 };
    if (!m.length) return "";
    const vals = m.flatMap((w) => [w.ci[0], w.ci[1], w.ratio]).concat([1]);
    let y0 = Math.max(Math.min(...vals) * 0.9, 1e-3), y1 = Math.max(...vals) * 1.1;
    const { Y, g } = frame(W, H, pad, y0, y1, [y0, 1, y1].filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b), (v) => v.toFixed(2) + "x", true);
    const bw = (W - pad.l - pad.r) / ws.length;
    const marks = ws.map((w, i) => {
      const cx = pad.l + bw * (i + 0.5);
      const lab = `<text x="${cx}" y="${H - 20}" text-anchor="middle" font-size="11" fill="var(--muted)">W${w.index}</text><text x="${cx}" y="${H - 6}" text-anchor="middle" font-size="10" fill="var(--muted)">${day(w.first_ms)}</text>`;
      if (w.status !== "MEASURED") return lab + `<text x="${cx}" y="${pad.t + 40}" text-anchor="middle" font-size="11" fill="var(--muted)">◌ ${w.n_scores}</text>`;
      return lab + `<g><title>W${w.index}: ${w.ratio.toFixed(2)}x (95% ${w.ci[0].toFixed(2)} to ${w.ci[1].toFixed(2)}), ${w.n_scores} trips</title>
        <line x1="${cx}" x2="${cx}" y1="${Y(w.ci[1])}" y2="${Y(w.ci[0])}" stroke="var(--accent)" stroke-width="2"/>
        <circle cx="${cx}" cy="${Y(w.ratio)}" r="5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>
        <rect x="${cx - bw / 2}" y="${pad.t}" width="${bw}" height="${H - pad.t - pad.b}" fill="transparent"/></g>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Habit ratio per walk-forward window with 95% ranges">${g}
      <line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(1)}" y2="${Y(1)}" stroke="var(--muted)" stroke-width="1"/>
      <text x="${pad.l + 4}" y="${Y(1) + 14}" font-size="11" fill="var(--muted)">1.00x = no habit</text>${marks}</svg>`;
  }

  async function loadTrend() {
    const el = $("#c-trend-body"); if (!el) return;
    el.innerHTML = '<p class="cnote">Computing…</p>';
    const { ok, j } = await get(`/api/trend/${C.tid}?habit=${C.habit}`);
    if (!el.isConnected) return;
    if (!ok) { el.innerHTML = `<p class="err">${tx(j.detail || "error")}</p>`; return; }
    const t = j.test, c = j.cusum;
    let answer;
    if (t.status === "UNDERPOWERED") answer = `<p class="honest"><span>Not enough trades yet:</span> <span>${tx(t.detail)}</span></p>`;
    else if (t.status === "CHANGE_DETECTED") answer = `<p class="honest">${cb(t.status)} <span>Habit ratio after the reference period versus during it:</span> <b>${rx(t.change_ratio)}</b> <span>(95% interval</span> <b>${rx(t.change_ci[0])}</b> <span>to</span> <b>${rx(t.change_ci[1])}</b><span>).</span></p>`;
    else {
      const next = t.more_habit_trips_needed != null
        ? `<span>To see a change of</span> <b>${rx(t.target_ratio)}</b><span>, the next test needs about</span> <b>${t.more_habit_trips_needed}</b> <span>more habit trips</span>${t.more_trades_needed != null ? ` <span>(about</span> <b>${t.more_trades_needed}</b> <span>trades at your rate).</span>` : "."}`
        : `<span>The reference period is too noisy for this test ever to see a change of</span> <b>${rx(t.target_ratio)}</b><span>. A fresh test with this many habit trips in each period would:</span> <b>${t.habit_trips_each_needed}</b>`;
      answer = `<p class="honest">${cb(t.status)} <span>The smallest change this test could have detected:</span> <b>${rx(t.mde_ratio)}</b> <span>(80% power, 5% two-sided).</span> ${next}</p>`;
    }
    const ref = c.reference;
    const refLine = `<p class="cnote"><span>Reference period: the first third of the history,</span> <b>${day(ref.first_ms)}</b> <span>to</span> <b>${day(ref.last_ms)}</b> <span>·</span> <span>habit trips in it:</span> <b>${ref.n_scores}</b></p>`;
    const cus = c.status === "UNDERPOWERED" ? `<p class="cnote">${cb("UNDERPOWERED")} ${tx(c.detail)}</p>` :
      `<p>${cb(c.status)} <span>${tx(c.detail)}</span></p>` +
      lineChart([{ pts: c.upper, color: "var(--accent)", label: "upward drift (habit growing)" }, { pts: c.lower, color: "var(--curve)", dash: "5 3", label: "downward drift (habit shrinking)" }],
        { aria: "CUSUM drift statistics after the reference period, with the alarm limit", hline: { y: c.h_sd, label: "alarm limit" }, fmt: (v) => v.toFixed(1), h: 180 }) +
      `<p class="cnote"><span>Alarm limit in reference SDs:</span> <b>${c.h_sd.toFixed(2)}</b> <span>· set so that this share of time-shuffled copies of your own trips cross it:</span> <b>${pc(c.false_alarm_shuffled, 0)}</b></p>` +
      `<p class="cnote">An alarm says "look here". A change is claimed only when the before/after interval excludes no change.</p>`;
    el.innerHTML = answer + refLine + `<h2 style="margin-top:10px">Habit ratio per window of your own history</h2>` + windowChart(j.windows) +
      `<p class="cnote">Dots: median habit ratio per window; bars: 95% bootstrap range. ◌ = too few trips in the window.</p>` +
      `<h2 style="margin-top:10px">Drift alarm (CUSUM)</h2>` + cus + `<p class="cnote"><span class="clabel">${tx(j.provenance)}</span> <span>Pre-registered settings; nothing tuned on this trader.</span></p>`;
  }

  // ---------------------------------------------------------------- 4. decay
  async function loadDecay() {
    const el = $("#c-decay-body"); if (!el || !C.tid) return;
    const { ok, j } = await get(`/api/decay/${C.tid}`);
    if (!el.isConnected) return;
    if (!ok) { el.innerHTML = `<p class="err">${tx(j.detail || "error")}</p>`; return; }
    if (!j.rules.length) { el.innerHTML = '<p class="cnote">No armed rule in your rulebook yet. Arm one above and its effect over time appears here.</p>'; return; }
    el.innerHTML = j.rules.map((r) => {
      const rp = r.replay, ck = rp.check;
      const parts = rp.parts.map((p) => `<tr><td>${p.part}</td><td class="n">${day(p.first_ms)}</td><td class="n">${p.n_trips}</td><td class="n">${p.n_affected}</td><td class="n">${p.effect == null ? "–" : usd(p.effect)}</td><td class="n">${p.p == null ? "–" : p.p.toFixed(3)}</td><td>${cb(p.status)}</td></tr>`).join("");
      return `<div class="rule"><b>${tx(r.rule_id)}</b> · <span>cap opening size at ${r.rule.value}x your median after a loss</span> ${sb(r.state)}
        <p class="cnote">${tx(r.since_arming.detail)}</p>
        <p><span class="clabel">REPLAY</span> <span class="cnote">${tx(rp.label)}</span></p>
        ${lineChart([{ pts: rp.curve, color: "var(--accent)", label: "cumulative effect of the rule" }], { aria: "Cumulative effect of the rule on replayed trades", zero: true, fmt: (v) => usd(v), h: 170 })}
        <p>${cb(ck.status)} <span>Effect on replayed trades:</span> <b>${ck.effect == null ? "–" : usd(ck.effect)}</b> · <span>p:</span> <b>${ck.p == null ? "–" : ck.p.toFixed(3)}</b> · <span>trades touched:</span> <b>${ck.n_affected}</b></p>
        <div class="scroll"><table class="ctable"><thead><tr><th>Part</th><th>From</th><th>Trips</th><th>Touched</th><th>Effect</th><th>p</th><th>Check</th></tr></thead><tbody>${parts}</tbody></table></div>
        <p class="cnote">${tx(rp.rule)}</p>
        <div class="crow"><button type="button" class="cbtn primary" data-decay="${ea(r.rule_id)}">Run the decay check</button><span class="cnote" data-decay-msg="${ea(r.rule_id)}"></span></div></div>`;
    }).join("") + `<p class="cnote">${tx(j.note)}</p>`;
    el.querySelectorAll("button[data-decay]").forEach((b) => b.addEventListener("click", async () => {
      const rid = b.dataset.decay;
      const { ok: ok2, j: d } = await get(`/api/decay/${C.tid}/${rid}/check`, { method: "POST" });
      const msg = el.querySelector(`[data-decay-msg="${rid}"]`);
      if (!ok2) { msg.textContent = d.detail || "error"; return; }
      if (typeof renderBook === "function") renderBook(d.book);
      msg.textContent = d.proposed_retirement ? "Loop proposed retirement. Confirm it or keep the rule in the rulebook above." : "No retirement proposed: the check does not say retire.";
    }));
  }

  // ---------------------------------------------------------------- 3a. ledger drift
  async function loadLedger() {
    const el = $("#c-ledger-body"); if (!el) return;
    const { ok, j } = await get(`/api/ledger-drift/${C.tid}`);
    if (!el.isConnected) return;
    if (!ok) { el.innerHTML = `<p class="err">${tx(j.detail || "error")}</p>`; return; }
    const demo = j.demo.map((d) => {
      const rc = d.reconciliation;
      const rows = d.walk.rows.map((r) => `<tr><td class="n">${ut(r.ts)}</td><td>${tx(r.type || "(blank)")}</td><td>${tx(r.category)}</td><td class="n">${sgn(r.amount, 8)}</td><td class="n">${nf(r.balance, 8)}</td><td class="n">${nf(r.expected, 8)}</td><td class="n ${r.gap ? "cneg" : ""}">${r.gap ? sgn(r.gap, 8) : "0"}</td></tr>`).join("");
      return `<h2 style="margin-top:12px">${tx(d.name)}</h2><p class="cnote"><span class="clabel">REAL</span> <span class="cmono">${tx(d.endpoint)}</span> · <span>rows:</span> <b>${d.n_rows}</b></p>
        <table class="ctable"><thead><tr><th>Time (UTC)</th><th>Type</th><th>Category</th><th>Amount</th><th>Balance</th><th>Expected</th><th>Gap</th></tr></thead><tbody>${rows}</tbody></table>
        <p>${cb(rc.status)} <span>Balance change:</span> <b>${sgn(rc.balance_change, 8)}</b> · <span>explained:</span> <b>${sgn(rc.explained, 8)}</b> · <span>residual:</span> <b>${sgn(rc.residual, 8)}</b> · <span>threshold:</span> <b>${nf(rc.threshold, 8)}</b></p>
        <p class="cnote">${tx(d.inputs)}</p>`;
    }).join("");
    el.innerHTML = `<p>${cb(j.wallet.status)}</p><p class="cnote">${tx(j.wallet.detail)}</p>
      <p class="cnote">${tx(j.method)}</p>
      <p class="honest">${tx(j.demo_label)}</p>${demo || '<p class="cnote">The sample file is not available on this server.</p>'}`;
  }

  // ---------------------------------------------------------------- 3b. structural gap sandbox
  function gapForm() {
    const el = $("#c-gap-body");
    el.innerHTML = `<p class="cnote"><span class="clabel">SANDBOX</span> You type a stop, the prices the market printed and a hypothetical exit. No trader data is used. The check tells a stop the trader did not honour from a stop the market jumped over.</p>
      <form class="cform" id="c-gap-f">
        <label>Position<select name="side"><option value="long">long</option><option value="short">short</option></select></label>
        <label>Stop price<input name="stop" type="number" step="any" min="0" required></label>
        <label>Exit minute<input name="exit_minute" type="number" step="any" min="0" required></label>
        <label>Exit price<input name="exit_price" type="number" step="any" min="0" required></label>
        <label class="wide">Market prints, one per line: minute price<textarea name="prints" required placeholder="0 100.0"></textarea></label>
        <div class="crow wide"><button class="cbtn primary" type="submit">Check the stop</button><button class="cbtn" type="button" id="c-gap-ex">Fill a typed example (a gap)</button></div>
      </form><div id="c-gap-res" aria-live="polite"></div>`;
    const f = $("#c-gap-f");
    $("#c-gap-ex").addEventListener("click", () => { f.side.value = "long"; f.stop.value = 100; f.exit_minute.value = 2.5; f.exit_price.value = 96.5; f.prints.value = "0 104.0\n1 101.2\n2 97.0\n3 96.4"; });
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const prints = f.prints.value.split(/\n+/).map((l) => l.trim().split(/[\s,;]+/).map(Number)).filter((p) => p.length >= 2 && p.every((v) => v === v));
      const body = { side: f.side.value, stop: +f.stop.value, exit_minute: +f.exit_minute.value, exit_price: +f.exit_price.value, prints: prints.map((p) => [p[0], p[1]]) };
      const { ok, j } = await get("/api/structural-gap/sandbox", { method: "POST", body: JSON.stringify(body) });
      const res = $("#c-gap-res"); if (!res) return;
      if (!ok) { res.innerHTML = `<p class="err">${tx(typeof j.detail === "string" ? j.detail : "Check the numbers: every field needs a positive number, and at least one print.")}</p>`; return; }
      const t = j.tag;
      res.innerHTML = `<p>${cb(t.tag)}</p><p>${tx(j.why)}</p>` + (t.breach_price != null ?
        `<p class="cnote"><span>First print at or past the stop:</span> <b>${nf(t.breach_price, 6)}</b> · <span>beyond the stop by:</span> <b>${pc(t.gap_frac, 2)}</b> · <span>exit after it (s):</span> <b>${Math.round(t.exit_lag_ms / 1000)}</b></p>` : "") +
        `<p class="cnote"><span>Exit beyond the stop (a cost either way):</span> <b>${pc(t.exit_beyond_frac, 2)}</b> · <span>gap tolerance:</span> <b>${pc(j.gap_tolerance, 1)}</b> · <span>grace (s):</span> <b>${j.exit_grace_s}</b></p><p class="cnote">${tx(j.label)}</p>`;
    });
  }

  // ---------------------------------------------------------------- 5. intent sandbox
  async function loadIntent() {
    const el = $("#c-intent-body");
    const [m, v] = await Promise.all([get(`/api/intent/metrics/${C.tid}`), get("/api/intent")]);
    if (!el || !el.isConnected) return;               // stale render: a newer one owns the card
    el.innerHTML = `<p class="cnote"><span class="clabel">SANDBOX · SIM_PAPER</span> Stamp your plan before a hypothetical order. The stamp is hash-locked with the server's time, so it cannot be edited once the outcome is known. Nothing here places an order.</p>
      <div class="chk"><b>Wallet ${tx(C.tid)}:</b> ${cb(m.j.status || "REFUSED")} <small>${tx(m.j.reason || "")}</small></div>
      <form class="cform" id="c-int-f">
        <label class="wide">Thesis: why this trade, and what would prove it wrong<input name="thesis" maxlength="300" minlength="3" required></label>
        <label>Side<select name="side"><option value="long">long</option><option value="short">short</option></select></label>
        <label>Symbol<input name="symbol" maxlength="30" required placeholder="BTCUSDT"></label>
        <label>Entry<input name="entry" type="number" step="any" min="0" required></label>
        <label>Stop<input name="stop" type="number" step="any" min="0" required></label>
        <label>Size (USDT)<input name="size" type="number" step="any" min="0" required></label>
        <label>Confidence it wins (%)<input name="confidence" type="number" min="1" max="99" step="1" required></label>
        <div class="crow wide"><button class="cbtn primary" type="submit">Stamp the plan</button><span class="cnote" id="c-int-msg" aria-live="polite"></span></div>
      </form><div id="c-int-view"></div>`;
    const f = el.querySelector("#c-int-f"); if (!f) return;
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { thesis: f.thesis.value, side: f.side.value, symbol: f.symbol.value, entry: +f.entry.value, stop: +f.stop.value, size: +f.size.value, confidence: +f.confidence.value / 100 };
      const { ok, j } = await get("/api/intent/stamp", { method: "POST", body: JSON.stringify(body) });
      { const m2 = $("#c-int-msg"); if (m2) m2.textContent = ok ? "Stamped." : (typeof j.detail === "string" ? j.detail : "Check the fields: every number must be positive and the stop on the losing side of the entry."); }
      if (ok) { f.reset(); intentView(j.view); }
    });
    intentView(v.j);
  }

  function intentView(v) {
    const el = $("#c-int-view"); if (!el || !v.entries) return;
    const g = v.grid.cells, cal = v.calibration;
    const list = v.entries.slice().reverse().map((e) => {
      const o = e.outcome;
      const res = o ? `<span>Outcome:</span> <b>${o.followed_plan ? "followed the plan" : "broke the plan"}</b>, <b>${o.won ? "won" : "lost"}</b> <span class="cnote">${ut(o.ts_ms)} UTC</span>` :
        `<span class="crow"><label class="cnote">Plan<select class="cbtn" data-f="${e.seq}"><option value="1">followed</option><option value="0">broke</option></select></label>
         <label class="cnote">Result<select class="cbtn" data-w="${e.seq}"><option value="1">won</option><option value="0">lost</option></select></label>
         <button type="button" class="cbtn" data-res="${e.seq}">Record the outcome</button></span>`;
      return `<div class="rule"><b>#${e.seq}</b> · <span>${tx(e.side)}</span> <b>${tx(e.symbol)}</b> · <span>entry</span> ${nf(e.entry, 6)} · <span>stop</span> ${nf(e.stop, 6)} · <span>size</span> ${nf(e.size, 2)} · <span>confidence</span> ${Math.round(e.confidence * 100)}% · <span>risk</span> ${nf(e.risk_usdt, 2)}
        <div class="cnote">${tx(e.thesis)}</div><div class="cnote"><span>Stamped</span> ${ut(e.ts_ms)} UTC · <span class="cmono">${tx(e.hash.slice(0, 16))}…</span></div><div>${res}</div></div>`;
    }).join("");
    const calib = cal.status === "MEASURED"
      ? `<p>${cb("MEASURED")} <span>Brier score:</span> <b>${cal.brier.toFixed(3)}</b> · <span>always stating your own win rate would score:</span> <b>${cal.brier_always_base_rate.toFixed(3)}</b></p>
        <table class="ctable"><thead><tr><th>Stated confidence</th><th>Entries</th><th>Average stated</th><th>Actually won</th></tr></thead><tbody>${cal.bins.map((b) => `<tr><td class="n">${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%</td><td class="n">${b.n}</td><td class="n">${pc(b.stated, 0)}</td><td class="n">${pc(b.actual, 0)}</td></tr>`).join("")}</tbody></table><p class="cnote">${tx(cal.detail)}</p>`
      : `<p>${cb("NOT_ENOUGH")} <span>Calibration appears at this many resolved entries:</span> <b>${cal.min}</b> · <span>resolved so far:</span> <b>${cal.n}</b> · <span>still needed:</span> <b>${cal.needed}</b></p>`;
    el.innerHTML = `<h2 style="margin-top:12px">Process versus outcome</h2>
      <div class="cgrid2"><div class="h"></div><div class="h">Won</div><div class="h">Lost</div>
        <div class="h">Followed the plan</div><div><b>${g.earned_win}</b>earned win</div><div><b>${g.good_loss}</b>good loss</div>
        <div class="h">Broke the plan</div><div><b>${g.lucky_win}</b>lucky win</div><div><b>${g.deserved_loss}</b>deserved loss</div></div>
      <p class="cnote">A good loss is still a good decision; a lucky win is not a plan to repeat.</p>
      <h2 style="margin-top:12px">Calibration</h2>${calib}
      <p class="cnote"><span>Hash chain:</span> <span>${v.chain.intact ? "intact" : "BROKEN"}</span> · <span>${tx(v.label)}</span></p>${list}`;
    el.querySelectorAll("button[data-res]").forEach((b) => b.addEventListener("click", async () => {
      const s = +b.dataset.res;
      const body = { seq: s, followed_plan: el.querySelector(`[data-f="${s}"]`).value === "1", won: el.querySelector(`[data-w="${s}"]`).value === "1" };
      const { ok, j } = await get("/api/intent/resolve", { method: "POST", body: JSON.stringify(body) });
      if (ok) intentView(j.view); else b.insertAdjacentHTML("afterend", ` <span class="err">${tx(j.detail || "error")}</span>`);
    }));
  }

  // ---------------------------------------------------------------- 6. export
  function exportCard() {
    const el = $("#c-export-body");
    const q = (typeof LANG !== "undefined" && LANG === "zh") ? "?lang=zh" : "";
    const base = `/api/report/${encodeURIComponent(C.tid)}`;
    el.innerHTML = `<p class="cnote">The weekly review with the same sections as the chat report: what happened, the priority finding, what would make it wrong, the rule court, tomorrow's plan, what changed, assumed and missing.</p>
      <div class="crow"><a class="cbtn primary" href="${base}.md${q}" download="loop-review-${ea(C.tid)}.md">Download Markdown</a>
        <a class="cbtn" href="${base}.html${q}" target="_blank" rel="noopener">Open printable page</a>
        <a class="cbtn" href="${base}.html${q ? q + "&" : "?"}download=1" download="loop-review-${ea(C.tid)}.html">Download HTML</a></div>
      <p class="cnote">If this server holds a signing key, each file ends with an HMAC-SHA256 signature line. It proves the file is unchanged since this server exported it. It is a signature, not zero-knowledge, and it does not make the numbers right; the number lock does that.</p>
      <label class="cnote" for="c-ver">Check an exported file:</label> <input type="file" id="c-ver" accept=".md,.html,.txt,text/*" class="cbtn"><div id="c-ver-res" aria-live="polite"></div>`;
    $("#c-ver").addEventListener("change", async (e) => {
      const file = e.target.files[0]; if (!file) return;
      const text = await file.text();
      const { ok, j } = await get("/api/report/verify", { method: "POST", body: JSON.stringify({ text }) });
      $("#c-ver-res").innerHTML = ok ? `<p>${cb(j.status)}</p><p class="cnote">${tx(j.detail)}</p>` : `<p class="err">${tx(j.detail && j.detail[0] ? j.detail[0].msg : "error")}</p>`;
    });
  }

  // ---------------------------------------------------------------- 7. share card
  function shareCard() {
    const el = $("#c-share-body");
    const path = `/api/share/${encodeURIComponent(C.tid)}.svg`;
    el.innerHTML = `<img class="cshare" src="${path}" alt="Share card: the one-line finding, the priced rule and the court verdict for wallet ${ea(C.tid)}, with its provenance" width="1200" height="630" loading="lazy">
      <div class="crow"><button type="button" class="cbtn primary" id="c-copy">Copy link</button><a class="cbtn" href="${path}" download="loop-share-${ea(C.tid)}.svg">Download SVG</a><span class="cnote" id="c-copy-msg" aria-live="polite"></span></div>
      <p class="cnote">Built from the same computed numbers as this page; the provenance label is printed on the card.</p>`;
    $("#c-copy").addEventListener("click", async () => {
      const url = location.origin + path;
      try { await navigator.clipboard.writeText(url); $("#c-copy-msg").textContent = "Link copied."; }
      catch (e) { $("#c-copy-msg").textContent = url; }
    });
  }

  // ---------------------------------------------------------------- 中文 (English is the source; patterns never touch numbers)
  if (typeof ZH_EXACT !== "undefined") {
    Object.assign(ZH_EXACT, {
      "Review tools": "复盘工具", "Open the trades": "查看这些交易", "Trades": "交易", "Trend and drift": "趋势与漂移",
      "Is an armed rule still earning its keep?": "已启用的规则还值得保留吗？", "Ledger drift: does the balance add up?": "账本漂移：余额对得上吗？",
      "Stop missed, or jumped by the market?": "是没执行止损，还是市场跳空越过了止损？", "Plan before the order: intent sandbox": "下单前先写计划：意图沙盒",
      "Export this review": "导出这份复盘", "Share card": "分享卡片", "Habit:": "习惯：", "Computing…": "计算中…",
      "Pick \"Open the trades\" next to a habit above to see the round trips it was measured on.": "点击上方习惯旁的“查看这些交易”，看它是基于哪些完整交易计算的。",
      "Trips in this group:": "这一组的交易数：", "showing the worst net results first:": "按净结果从差到好显示：",
      "Symbol": "品种", "Opened (UTC)": "开仓时间（UTC）", "Held": "持仓时长", "Side": "方向", "First order (USD)": "首笔订单（美元）",
      "Net result (USD)": "净结果（美元）", "Also tagged": "其他标签", "Pick a row to see its fills.": "点一行查看它的成交记录。",
      "after a loss": "亏损之后", "losing trip": "亏损交易", "busiest day": "最忙的一天", "re-entry": "再次进场", "revenge re-entry": "报复性再进场",
      "long": "多", "short": "空", "buy": "买", "sell": "卖", "opens": "开仓", "closes": "平仓", "Trip": "交易",
      "Time (UTC)": "时间（UTC）", "Opens or closes": "开仓或平仓", "Price": "价格", "Size": "数量", "Notional (USD)": "名义金额（美元）", "Fee": "手续费", "Realised": "已实现",
      "net result": "净结果", "MAE:": "最大不利波动：", "MFE:": "最大有利波动：",
      "Trips are flat-to-flat round trips rebuilt from fills; a trip cut by the start of the history is skipped, never guessed.": "交易是根据成交记录重建的从空仓到空仓的完整交易；被历史起点截断的交易会被跳过，不做猜测。",
      "This trader has no fill records (simulated round trips only), so there is nothing to replay fill by fill.": "这位交易者没有成交记录（只有模拟的完整交易），所以无法逐笔回放。",
      "Not enough trades yet:": "交易还不够：", "Habit ratio after the reference period versus during it:": "参照期之后与参照期内的习惯比值：",
      "(95% interval": "（95% 区间", "to": "到", ").": "）。", "The smallest change this test could have detected:": "这个检验能发现的最小变化：",
      "(80% power, 5% two-sided).": "（80% 检验力，5% 双侧）。", "To see a change of": "要发现", ", the next test needs about": " 的变化，下一次检验大约还需要",
      "more habit trips": "笔带有该习惯的交易", "(about": "（约", "trades at your rate).": "笔交易，按你的频率）。",
      "The reference period is too noisy for this test ever to see a change of": "参照期噪声太大，这个检验永远无法发现这样的变化：",
      ". A fresh test with this many habit trips in each period would:": "。重新做一次前后各有这么多笔习惯交易的检验才可以：",
      "Reference period: the first third of the history,": "参照期：历史的前三分之一，", "·": "·", "habit trips in it:": "其中的习惯交易：",
      "Habit ratio per window of your own history": "你自己历史中每个窗口的习惯比值", "Drift alarm (CUSUM)": "漂移警报（CUSUM）",
      "Dots: median habit ratio per window; bars: 95% bootstrap range. ◌ = too few trips in the window.": "圆点：每个窗口的习惯比值中位数；竖线：95% 自助法范围。◌ = 窗口内交易太少。",
      "1.00x = no habit": "1.00x = 没有习惯", "Alarm limit in reference SDs:": "警报界限（参照期标准差）：",
      "· set so that this share of time-shuffled copies of your own trips cross it:": "· 设定标准：把你自己的交易打乱时间顺序后，越过界限的比例为",
      "An alarm says \"look here\". A change is claimed only when the before/after interval excludes no change.": "警报只表示“值得看一看”。只有前后对比的区间排除了“没有变化”，才算发现变化。",
      "upward drift (habit growing)": "向上漂移（习惯在加重）", "downward drift (habit shrinking)": "向下漂移（习惯在减轻）", "alarm limit": "警报界限",
      "Pre-registered settings; nothing tuned on this trader.": "设置事先固定，没有针对这位交易者调参。",
      "No armed rule in your rulebook yet. Arm one above and its effect over time appears here.": "规则手册里还没有启用的规则。在上方启用一条，它随时间的效果会显示在这里。",
      "No trades have happened since you armed this rule (the demo history is fixed), so the real decay check has nothing to judge yet.": "启用这条规则之后还没有新的交易（演示历史是固定的），所以真正的衰减检查暂时没有可判断的内容。",
      "Effect on replayed trades:": "在回放交易上的效果：", "p:": "p：", "trades touched:": "涉及的交易：",
      "Part": "部分", "From": "起始", "Trips": "交易数", "Touched": "涉及", "Effect": "效果", "Check": "检查", "Run the decay check": "运行衰减检查",
      "Loop proposed retirement. Confirm it or keep the rule in the rulebook above.": "Loop 提议退役这条规则。请在上方规则手册中确认或保留。",
      "No retirement proposed: the check does not say retire.": "没有提议退役：检查结果不建议退役。",
      "Only armed rules are checked. Loop may PROPOSE retirement; only you can confirm it.": "只检查已启用的规则。Loop 只能“提议”退役，只有你能确认。",
      "✔ still earning its keep": "✔ 仍然值得保留", "▲ check says retire": "▲ 检查建议退役", "✔ reconciled": "✔ 已对平", "▲ unexplained residual": "▲ 有无法解释的差额",
      "◌ no records for this wallet": "◌ 这个钱包没有记录", "▲ drift alarm": "▲ 漂移警报", "● no drift alarm": "● 没有漂移警报", "▲ change detected": "▲ 发现变化",
      "● no change detected": "● 没有发现变化", "✔ measured": "✔ 已测量", "◌ not enough entries yet": "◌ 记录还不够", "○ stop not reached": "○ 没触及止损",
      "✔ stop honoured": "✔ 止损已执行", "✖ behavioural breach": "✖ 行为性违规", "▲ structural gap": "▲ 结构性跳空", "✔ verified: unchanged since export": "✔ 已验证：导出后未改动",
      "✖ altered after export": "✖ 导出后被改动", "◌ unverified: no signature": "◌ 未验证：没有签名", "◌ cannot check: server has no key": "◌ 无法检查：服务器没有密钥",
      "▲ signed with another key": "▲ 用其他密钥签名", "■ refused": "■ 拒绝", "✔ balances add up": "✔ 余额对得上", "▲ balance gap found": "▲ 发现余额缺口",
      "This wallet has fills but no balance snapshots or financial-records rows (funding, transfers, fees outside trades), so its balance cannot be reconciled. Nothing is estimated in their place.":
        "这个钱包有成交记录，但没有余额快照或资金流水（资金费、划转、交易外的费用），所以无法对账。不会用估计值代替。",
      "REAL rows: captured Bitget API responses from the ccxt test suite (MIT). Not this wallet; tiny on purpose.": "真实数据：来自 ccxt 测试集（MIT）的 Bitget 接口真实返回。不是这个钱包；样本很小。",
      "Futures account: one funding settlement": "合约账户：一笔资金费结算", "Funding wallet: deposit, transfer, withdrawal": "资金账户：充值、划转、提现",
      "rows:": "行数：", "Type": "类型", "Category": "类别", "Amount": "金额", "Balance": "余额", "Expected": "应有余额", "Gap": "缺口", "(blank)": "（空白）",
      "Balance change:": "余额变化：", "explained:": "已解释：", "residual:": "差额：", "threshold:": "阈值：",
      "The sample file is not available on this server.": "这台服务器上没有样本文件。",
      "Position": "持仓方向", "Stop price": "止损价", "Exit minute": "离场分钟", "Exit price": "离场价", "Market prints, one per line: minute price": "市场成交价，每行一个：分钟 价格",
      "Check the stop": "检查止损", "Fill a typed example (a gap)": "填入一个手写示例（跳空）",
      "First print at or past the stop:": "第一笔触及或越过止损的成交价：", "beyond the stop by:": "越过止损：", "exit after it (s):": "之后多久离场（秒）：",
      "Exit beyond the stop (a cost either way):": "离场价越过止损（都算成本）：", "gap tolerance:": "跳空容差：", "grace (s):": "宽限（秒）：",
      "SANDBOX: every number here is one you typed. No trader data is used.": "沙盒：这里每个数字都是你输入的。没有使用任何交易者的数据。",
      "No price you typed reached the stop before the exit, so this is not a stop-out and does not enter the score.": "你输入的价格在离场前都没触及止损，所以这不算止损离场，不计入评分。",
      "Price reached the stop with a print near the level and the exit came within the grace period: honoured.": "价格在止损附近有成交并触及止损，且在宽限期内离场：止损已执行。",
      "Price reached the stop and the position was still open after the grace period: a behavioural breach.": "价格触及止损，宽限期过后仍然持仓：行为性违规。",
      "The first print past the stop was already beyond it by more than the gap tolerance, and the exit was prompt: the market jumped the stop. It still costs money and stays in cost numbers, but it is left out of the behaviour score.":
        "第一笔越过止损的成交价已经超出跳空容差，而且离场及时：是市场跳过了止损。它仍然有成本、计入成本数字，但不计入行为评分。",
      "Thesis: why this trade, and what would prove it wrong": "交易理由：为什么做这笔，什么情况说明它错了", "Entry": "进场价", "Stop": "止损",
      "Size (USDT)": "仓位（USDT）", "Confidence it wins (%)": "认为会赢的把握（%）", "Stamp the plan": "盖章锁定计划", "Stamped.": "已盖章。",
      "Plan": "计划", "followed": "遵守", "broke": "违反", "Result": "结果", "won": "赢", "lost": "输", "Record the outcome": "记录结果",
      "Outcome:": "结果：", "followed the plan": "遵守了计划", "broke the plan": "违反了计划", "entry": "进场", "stop": "止损", "size": "仓位", "confidence": "把握", "risk": "风险", "Stamped": "盖章时间",
      "Process versus outcome": "过程与结果", "Won": "赢", "Lost": "输", "Followed the plan": "遵守计划", "Broke the plan": "违反计划",
      "earned win": "应得的盈利", "good loss": "好的亏损", "lucky win": "侥幸的盈利", "deserved loss": "应得的亏损",
      "A good loss is still a good decision; a lucky win is not a plan to repeat.": "好的亏损仍然是好的决策；侥幸的盈利不是值得重复的计划。",
      "Calibration": "校准", "Brier score:": "Brier 分数：", "always stating your own win rate would score:": "如果总是报出你自己的胜率，分数会是：",
      "Stated confidence": "声明的把握", "Entries": "记录数", "Average stated": "平均声明", "Actually won": "实际赢的比例",
      "Calibration appears at this many resolved entries:": "校准表在已结算记录达到这个数量时出现：", "resolved so far:": "目前已结算：", "still needed:": "还需要：",
      "Hash chain:": "哈希链：", "intact": "完整", "BROKEN": "已损坏",
      "SANDBOX: hypothetical orders you typed in this session. SIM_PAPER, not real fills; resets with the session.": "沙盒：你在本次会话中输入的假设订单。SIM_PAPER，不是真实成交；会话结束即重置。",
      "Stamp your plan before a hypothetical order. The stamp is hash-locked with the server's time, so it cannot be edited once the outcome is known. Nothing here places an order.":
        "在假设的下单之前先盖章锁定计划。盖章用服务器时间做哈希锁定，知道结果后无法再改。这里不会下任何单。",
      "You type a stop, the prices the market printed and a hypothetical exit. No trader data is used. The check tells a stop the trader did not honour from a stop the market jumped over.":
        "你输入止损、市场成交价和一个假设的离场。没有使用任何交易者数据。这个检查区分“交易者没有执行止损”和“市场跳过了止损”。",
      "Download Markdown": "下载 Markdown", "Open printable page": "打开可打印页面", "Download HTML": "下载 HTML", "Check an exported file:": "检查一个导出的文件：",
      "The weekly review with the same sections as the chat report: what happened, the priority finding, what would make it wrong, the rule court, tomorrow's plan, what changed, assumed and missing.":
        "每周复盘，章节与对话中的报告相同：发生了什么、最重要的发现、什么情况下它是错的、规则法庭、明天的计划、变化、假设与缺失。",
      "If this server holds a signing key, each file ends with an HMAC-SHA256 signature line. It proves the file is unchanged since this server exported it. It is a signature, not zero-knowledge, and it does not make the numbers right; the number lock does that.":
        "如果服务器有签名密钥，每个文件末尾都有一行 HMAC-SHA256 签名。它证明文件自服务器导出后没有被改动。这是签名，不是零知识证明，也不保证数字正确；数字锁定负责这一点。",
      "Copy link": "复制链接", "Download SVG": "下载 SVG", "Link copied.": "链接已复制。",
      "Built from the same computed numbers as this page; the provenance label is printed on the card.": "用与本页相同的计算数字生成；卡片上印有数据来源标签。",
    });
    ZH_PATTERNS.push(
      [/^No candles for (.*) are stored offline, so no price path is drawn and MAE\/MFE are not computed\. Nothing is fetched or guessed\.$/, "离线没有存储 $1 的K线，所以不画价格路径，也不计算最大不利/有利波动。不联网获取，也不猜测。"],
      [/^MAE and MFE are approximate: from (\d+)-minute candle highs and lows.*$/, "最大不利/有利波动是近似值：取自 $1 分钟K线的最高价和最低价，可能包含交易时间窗口之外的价格。"],
      [/^W(\d+): ([\d.]+)x \(95% ([\d.]+) to ([\d.]+)\), (\d+) trips$/, "窗口 $1：$2x（95% $3 到 $4），$5 笔交易"],
      [/^Fills in this trip:$/, "这笔交易的成交数："], [/^Show the other fills:$/, "显示其余成交："],
      [/^([\d.]+) min$/, "$1 分钟"], [/^([\d.]+) h$/, "$1 小时"], [/^([\d.]+) d$/, "$1 天"],
      [/^cap opening size at ([\d.]+)x your median after a loss$/, "亏损后开仓大小上限为你中位数的 $1 倍"],
      [/^the reference period \(first third, (\d+) trips\) has (\d+) habit trips; needs (\d+)$/, "参照期（前三分之一，$1 笔交易）只有 $2 笔习惯交易；需要 $3 笔"],
      [/^drift alarm at habit trip (\d+) after the reference period: habit grew$/, "参照期之后第 $1 笔习惯交易触发漂移警报：习惯在加重"],
      [/^drift alarm at habit trip (\d+) after the reference period: habit shrank$/, "参照期之后第 $1 笔习惯交易触发漂移警报：习惯在减轻"],
      [/^no drift alarm over (\d+) habit trips after the reference period$/, "参照期之后的 $1 笔习惯交易中没有漂移警报"],
      [/^no habit trips after the reference period yet$/, "参照期之后还没有习惯交易"],
      [/^REPLAY: treats the last 40% of the history.*$/, "回放：把历史的最后 40% 当作启用之后的交易。这些交易也是法庭证据的一部分，所以这里展示的是检查如何运作，不是独立检验。"],
      [/^retire if effect <= 0 or p > ([\d.]+); underpowered below (\d+) trips or (\d+) affected$/, "效果 ≤ 0 或 p > $1 时建议退役；少于 $2 笔交易或涉及少于 $3 笔时样本不足"],
      [/^explained = trade pnl - trade fees.*$/, "已解释 = 交易盈亏 - 交易手续费 + 资金费 + 强平费 + 划转 + 返佣；差额 = 余额变化 - 已解释，只报告，不归入任何类别"],
      [/^balance change from the rows' own running balance.*$/, "余额变化取自流水自带的滚动余额（起点由第一行推算）；交易盈亏和手续费为 0，因为样本在这段时间没有成交"],
      [/^Wallet ([A-Z]):$/, "钱包 $1："],
      [/^Intent metrics need a plan stamped BEFORE the order\..*$/, "意图指标需要在下单之前盖章的计划。导入的历史（交易所成交或公开钱包）没有这样的盖章，事后补写的计划会被结果影响，所以 Loop 不对它评估意图、计划执行或校准。"],
      [/^Brier score: mean squared gap.*$/, "Brier 分数：声明的把握与 0/1 结果之间的平均平方差（越低越好）；与总是报出你自己的胜率相比"],
      [/^signature matches: unchanged since export$/, "签名一致：导出后没有改动"], [/^signature does not match: altered after export$/, "签名不一致：导出后被改动"],
      [/^no Loop signature line found: this file is unverified$/, "没有找到 Loop 签名行：这个文件未经验证"],
      [/^this server has no signing key, so it cannot check the signature$/, "这台服务器没有签名密钥，无法检查签名"],
      [/^balance change explained within the threshold$/, "余额变化在阈值内得到解释"],
      [/^UNEXPLAINED residual (.*) exceeds (.*) \((.*)% of start equity\); not assigned to any category$/, "无法解释的差额 $1 超过 $2（起始权益的 $3%）；不归入任何类别"],
    );
  }
})();
