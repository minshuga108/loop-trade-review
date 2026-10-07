// Loop first screen. Loaded after i18n.js and before rulebook.js and cards.js, which use the globals
// defined here ($, esc, num, usd, badge, detName, current, HDR, render, select, ask, logs).
// Every number drawn here comes from an API response; nothing is computed for display beyond formatting.
const $ = (s) => document.querySelector(s);
const pct = (x) => (x == null || x !== x ? "–" : (100 * x).toFixed(1) + "%");
const pp = (x) => (x == null || x !== x ? "–" : (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + " pts");
const usd = (x) => (x < 0 ? "-$" : "+$") + Math.abs(Math.round(x)).toLocaleString("en-US");
const sign = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "zero");
const statusBadge = (s) => ({
  FLAGGED: ["b-warn", "▲ habit found"], SUGGESTIVE: ["b-warn", "△ suggestive, not proven"], NOT_FLAGGED: ["b-grey", "● nothing found"], UNDERPOWERED: ["b-grey", "◌ not enough trades yet"],
  ACCEPTED: ["b-ok", "✔ accepted"], REJECTED: ["b-bad", "✖ rejected"],
}[s] || ["b-grey", s]);
const badge = (s) => { const [c, t] = statusBadge(s); return `<span class="badge ${c}">${esc(t)}</span>`; };
const detName = { size_after_loss: "Size after a loss", hold_asymmetry: "Holding losers longer than winners", overtrading_clusters: "Trading more on your busiest days", revenge_reentry: "Re-entering the same symbol soon after a loss", chase_after_move: "Chasing a big prior move", off_hours_trading: "Trading stock perps outside US cash-session hours", averaging_down: "Adding at a worse price (averaging down)" };
// 27 starters in seven groups; every one is answered by the typed parser or the router (tests/test_chat_ux.py runs them all)
const CHIP_GROUPS = [
  ["New trader", ["Where does this data come from?", "How many trades are in this record?", "What is my win rate?", "Is this financial advice?"]],
  ["Review", ["What is my biggest costly habit?", "Show my weekly review", "What changed since my last review?", "What is my worst day?"]],
  ["Rules", ["Which rules were tested?", "What if I had kept rule 2?", "Did the court throw out any rules?", "Show my checklist"]],
  ["Costs", ["How much did I pay in fees?", "What share of my profit went to fees?", "What is my average loss?", "What is my profit factor?"]],
  ["中文", ["我最大的坏习惯是什么？", "给我看这周的复盘", "我的胜率是多少？", "哪天亏最多？", "手续费占了多少？"]],
  ["What would make this wrong", ["What would make this wrong?", "How sure are you about that?", "Could this just be luck?"]],
  ["What did the gate block", ["What did the gate block?", "Check an order idea: Buy $20k rNVDA", "Check an order idea: buy 100 DOGE"]],
];
const CHIPS = CHIP_GROUPS.flatMap((g) => g[1]);
const chipsHtml = () => CHIP_GROUPS.map(([g, qs]) => `<div class="chipgroup"><span class="cg-l">${esc(g)}</span>` + qs.map((c) => `<button type="button">${esc(c)}</button>`).join("") + "</div>").join("");
let traders = [], current = null, showRule = true, ruleKey = "cap";
let SID = "s" + Math.random().toString(36).slice(2, 10);
try { SID = localStorage.getItem("sid") || SID; localStorage.setItem("sid", SID); } catch (e) {}
const HDR = { "Content-Type": "application/json", "X-Session": SID };
const logs = {};
let LAST = null;                                   // {r, t} of the trader on screen, for redraws that need no fetch
// every server string goes through esc() before innerHTML; quotes too, so it is safe inside attributes
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (x) => (typeof x === "number" ? x : esc(x));
const day = (ms) => new Date(ms).toISOString().slice(0, 10);

// ---------------------------------------------------------------- theme (tokens live in home.css)
(function theme() {
  const root = document.documentElement, b = $("#themebtn");
  let t = null; try { t = localStorage.getItem("theme"); } catch (e) {}
  const apply = (v) => { if (v) root.dataset.theme = v; else delete root.dataset.theme; if (b) b.textContent = isDark() ? "◐ Light" : "◑ Dark"; };
  const isDark = () => root.dataset.theme === "dark" || (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  apply(t);
  if (b) b.addEventListener("click", () => { const v = isDark() ? "light" : "dark"; try { localStorage.setItem("theme", v); } catch (e) {} apply(v); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => apply(root.dataset.theme || null));
})();

// ---------------------------------------------------------------- markdown (chat reports) and chat log
function md(src) {
  const out = []; let inList = false;
  for (const raw of esc(src).split("\n")) {
    let l = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<em>$2</em>");
    const li = /^\s*- (.*)/.exec(l);
    if (li) { if (!inList) { out.push("<ul>"); inList = true; } out.push("<li>" + li[1] + "</li>"); continue; }
    if (inList) { out.push("</ul>"); inList = false; }
    const hd = /^(#{1,3}) (.*)/.exec(l);
    if (hd) out.push("<h3>" + hd[2] + "</h3>"); else if (l.trim()) out.push("<p>" + l + "</p>");
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

function cardHtml(c) {
  if (!c) return "";
  if (c.type === "tiles") return '<div class="qa-tiles">' + c.tiles.map((t) => `<div class="qa-tile"><b>${esc(String(t.value))}</b><span>${esc(String(t.label))}</span></div>`).join("") + "</div>";
  if (c.type === "bars") {
    const max = Math.max(1e-9, ...c.items.map((i) => Math.abs(Number(i.value) || 0)));
    return '<div class="qa-bars">' + c.items.map((i) => `<div class="qa-bar"><span class="qa-bl">${esc(String(i.label))}</span><span class="qa-bt"><i class="${Number(i.value) < 0 ? "neg" : "pos"}" style="width:${Math.max(2, 100 * Math.abs(Number(i.value) || 0) / max)}%"></i></span><span class="qa-bv">${esc(String(i.text))}${i.n != null ? " · n=" + esc(String(i.n)) : ""}</span></div>`).join("") + "</div>";
  }
  if (c.type === "table") return '<div class="scroll"><table><thead><tr>' + c.columns.map((x) => `<th>${esc(String(x))}</th>`).join("") + "</tr></thead><tbody>" +
    c.rows.map((r) => "<tr>" + r.map((x) => `<td class="n">${esc(String(x))}</td>`).join("") + "</tr>").join("") + "</tbody></table></div>";
  if (c.type === "clarify") return `<div class="chips"><span class="tag">${esc(c.question || "")}</span>` + (c.options || []).map((o) => `<button type="button" data-q="${esc(o.label)}">${esc(o.label)}</button>`).join("") + "</div>";
  return "";
}
function traceHtml(r) {
  const t = r.tool_trace; if (!t || !t.length) return "";
  const z = typeof LANG !== "undefined" && LANG === "zh";
  const body = t.map((x) => `<li><b>${esc(x.tool)}</b> ${esc(JSON.stringify(x.inputs || {}))}${x.rows != null ? " · " + num(x.rows) + (z ? " 笔" : " rows") : ""} · ${z ? "数字锁" : "number-lock"}: ${esc(x.number_lock)} · ${z ? "措辞" : "phrased by"}: ${esc(x.phrased_by)}${x.what ? " · " + esc(x.what) : ""}</li>`).join("");
  return `<li><details class="how"><summary><b>${z ? "我是怎么回答的" : "How I answered"}</b></summary><ul>${body}</ul></details></li>`;
}
function receiptHtml(m, i) {
  const r = m.receipt; if (!r) return "";
  const rows = r.rows ? `${num(r.rows.used)}${r.rows.of != null && r.rows.of !== r.rows.used ? " of " + num(r.rows.of) : ""} round trips` : "";
  const li = (k, v) => (v ? `<li><b>${k}</b> <span>${v}</span></li>` : "");
  const fb = m.fb && m.fb.vote ? `<span class="fbdone" role="status">${m.fb.vote === "up" ? "Marked helpful" : "Marked not helpful"}. Saved to the public record as entry #${num(m.fb.seq)}, tagged feedback.</span>`
    : m.fb && m.fb.error ? `<span class="err" role="status">${esc(m.fb.error)}</span>`
    : `<span class="fbq">Did this answer your question?</span><button type="button" class="fb" data-fb="up" data-i="${i}" ${m.fb ? "disabled" : ""}>Helpful</button><button type="button" class="fb" data-fb="down" data-i="${i}" ${m.fb ? "disabled" : ""}>Not helpful</button>`;
  return `<div class="receipt"><p class="rc-h">Receipt</p><ul>
    ${li("Sources", (r.sources || []).map(esc).join("; "))}${li("Computed", (r.computations || []).map(esc).join("; "))}${li("Rows", rows)}
    ${li("Ledger", r.ledger ? esc(r.ledger.note) : "")}${li("Trace", (r.trace || []).map(esc).join(" › "))}${traceHtml(r)}${li("Numbers", r.facts ? num(r.facts) + " computed facts; lock " + esc(r.number_lock) : esc(r.number_lock))}</ul>
    <div class="fbrow">${fb}<button type="button" class="fb full" data-full="${m.lang === "zh" ? "zh" : "en"}">Run the full review on this</button></div></div>`;
}
async function sendFeedback(i, vote) {
  const m = (logs[current] || [])[i]; if (!m || m.fb) return;
  m.fb = { pending: true }; renderLog();
  try {
    const r = await fetch("/api/feedback", { method: "POST", headers: HDR, body: JSON.stringify({ trader: current, intent: m.intent || "", vote }) });
    const j = await r.json().catch(() => ({}));
    m.fb = r.ok ? { vote, seq: j.seq } : { error: "Feedback was not saved: " + (typeof j.detail === "string" ? j.detail : "HTTP " + r.status) };
  } catch (e) { m.fb = { error: "Feedback was not saved: the server could not be reached." }; }
  renderLog();
}
function renderLog() {
  const el = $("#chatlog"); if (!el) return;
  if ($("#asklog")) $("#asklog").classList.toggle("has", !!(logs[current] || []).length);
  el.innerHTML = (logs[current] || []).map((m, i) => {
    if (m.me) return `<div class="msg me">${esc(m.text)}</div>`;
    if (m.failed) return `<div class="msg"><span class="err">■ No answer came back</span>: <span>${esc(m.text)}</span><div class="chips retry"><button type="button" data-q="${esc(m.q)}">Ask again</button></div></div>`;
    const steps = m.steps ? `<span class="ichip">${m.steps.map((s) => esc(s.name) + " " + num(s.ms) + " ms").join(" › ")}</span>` : "";
    return `<div class="msg"><div class="interp"><span>Interpreted as: ${esc(m.interpreted || m.intent || "")}</span>${steps}</div>${m.kind === "report" ? '<div class="md">' + md(m.markdown) + "</div>" : esc(m.text)}${cardHtml(m.card)}
      <details><summary>Numbers locked: ${m.number_lock === "passed" ? "every number comes from a computed fact" : esc(m.number_lock)}</summary>
      ${m.facts && m.facts.length ? "<table>" + m.facts.map((f) => `<tr><td>${esc(f.fact)}</td><td>${num(f.value)}</td></tr>`).join("") + "</table>" : "<span>(report: all numbers computed from fills)</span>"}</details>${receiptHtml(m, i)}${m.next ? '<div class="chips">' + m.next.map((n) => `<button type="button" data-q="${esc(n)}">${esc(n)}</button>`).join("") + "</div>" : ""}</div>`;
  }).join("");
}
async function ask(msg) {
  msg = (msg || "").trim(); if (!msg) return;
  (logs[current] = logs[current] || []).push({ me: true, text: msg }); renderLog();
  const log = $("#chatlog");
  const pending = document.createElement("div"); pending.className = "msg-pending"; pending.setAttribute("role", "status");
  pending.innerHTML = '<span class="spin" aria-hidden="true"></span><span>Computing from fills…</span>'; log.appendChild(pending);
  if ($("#asklog")) $("#asklog").classList.add("has");
  if (innerWidth <= 900) pending.scrollIntoView({ block: "center" });      // on a phone the ask bar is fixed at the bottom; bring the answer area into view
  const tid = current;
  let j;
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: HDR, body: JSON.stringify({ trader: tid, message: msg, history: (logs[tid] || []).filter((m) => !m.me && !m.failed).slice(-4).map((m) => ({ intent: m.intent, plan: m.plan })) }) });
    j = r.ok ? await r.json() : { failed: true, q: msg, text: r.status === 429 ? "too many questions at once; wait a moment." : "the service answered " + r.status + ". The numbers on the page are still correct." };
  } catch (e) { j = { failed: true, q: msg, text: "the service could not be reached. The numbers on the page are still correct." }; }
  pending.remove();
  (logs[tid] = logs[tid] || []).push(j);
  if (tid === current) {
    renderLog(); if (j.llm) $("#llmnote").textContent = "Language model: " + j.llm;
    if (innerWidth <= 900 && $("#chatlog").lastElementChild) $("#chatlog").lastElementChild.scrollIntoView({ block: "start" });
  }
}

// ---------------------------------------------------------------- skeleton and degraded state
const SKELETON = `<div class="sk" aria-hidden="true">
  <div class="sk-box"><div class="sk-line w40"></div><div class="sk-line tall"></div><div class="sk-line w90"></div><div class="sk-line money"></div><div class="sk-line"></div><div class="sk-line w90"></div></div>
  <div class="sk-box"><div class="sk-line w40"></div><div class="sk-line plot"></div><div class="sk-line w90"></div></div></div>`;
function skeleton(text) { $("#main").innerHTML = `<p class="vh" role="status">${esc(text)}</p>` + SKELETON; }
function down(kind, detail, retry) {
  const first = kind === "boot";
  $("#main").innerHTML = `<section class="down" role="alert" aria-live="assertive">
    <h2><span class="ic" aria-hidden="true">■</span>${first ? "The review engine is not reachable" : "This trader could not be loaded right now"}</h2>
    <p>${first ? "This page draws every number from the Loop API when it loads, and no answer came back." : "The server may be busy computing another review."} <span class="tag">${esc(detail || "")}</span></p>
    <p>Nothing is shown from a cache or typed by hand, so instead of a stale number you see this notice. When the API is up, this screen shows:</p>
    <ul><li>one habit per trader, tested within that trader's own fills and priced in dollars,</li><li>the profit curve with and without a rule, split into learned-on and never-seen trades,</li><li>the rule court, your rulebook and the order gate, and a chat that answers in English or 中文.</li></ul>
    <div class="actions"><button type="button" class="btn primary" id="retry">Try again <span class="arrow">→</span></button><a class="btn" href="/cockpit">Judge cockpit</a><a class="btn" href="/api/health">/api/health</a></div>
    <p class="tag" id="retrynote"></p></section>`;
  $("#retry").addEventListener("click", retry);
  let n = 0; const tick = setInterval(() => { if (!$("#retrynote")) return clearInterval(tick); n += 1; $("#retrynote").textContent = `Retrying by itself in ${Math.max(0, 10 - n)} s…`; if (n >= 10) { clearInterval(tick); retry(); } }, 1000);
}

// ---------------------------------------------------------------- boot and trader switch
// imports are named "Your import", "Your import 2" ... never by their raw id
function yourImport(id) {
  const imps = traders.filter((x) => x.role === "import");
  return imps.length > 1 ? "Your import " + (imps.findIndex((x) => x.id === id) + 1) : "Your import";
}

async function boot(selectId) {
  skeleton("Loading…");
  try {
    const tr = await fetch("/api/traders", { headers: HDR });
    if (!tr.ok) throw new Error("HTTP " + tr.status);
    traders = await tr.json();
  } catch (e) { down("boot", e.message, boot); return; }
  $("#picker").innerHTML = `<div class="picker-row"><div class="tswitch" role="group" aria-label="Choose a trader">` + traders.map((t) =>
    `<button type="button" data-id="${esc(t.id)}" aria-pressed="false" title="${esc(t.blurb)}"><b>${t.role === "import" ? yourImport(t.id) : "Wallet " + esc(t.id)}</b>${t.role === "control" ? "<small>control</small>" : t.role === "planted" ? "<small>simulated</small>" : t.role === "real_bitget" ? "<small>real Bitget</small>" : t.role === "import" ? "<small>yours</small>" : ""}</button>`).join("") +
    `</div><button type="button" id="importbtn" class="importbtn" aria-expanded="false" aria-controls="importpanel">＋ Import your history</button>` +
    `<span class="tag">Read-only. No login. No key.</span><span class="tag">Every number computed from fills at load</span></div><p class="tcap" id="tcap"></p>`;
  $("#picker").addEventListener("click", (e) => { const b = e.target.closest("button[data-id]"); if (b) select(b.dataset.id); });
  wireNav();
  await select((traders.find((t) => t.id === (selectId || "B")) || traders[0]).id);
}

async function select(id) {
  current = id;
  const t = traders.find((x) => x.id === id) || {};
  document.querySelectorAll("#picker button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.id === id));
  if ($("#tcap")) $("#tcap").innerHTML = `<b>${t.role === "import" ? yourImport(id) : "Wallet " + esc(id)}</b> · <span>${esc(t.blurb || "")}</span> · <span>${num(t.n_trips)} trips</span>`;
  skeleton("Computing from fills…");
  let r, tg;
  try {
    const [a, b] = await Promise.all([fetch("/api/review/" + id), fetch("/api/toggle/" + id + "?rule=" + ruleKey)]);
    if (!a.ok || !b.ok) throw new Error("HTTP " + (a.ok ? b : a).status);
    [r, tg] = await Promise.all([a.json(), b.json()]);
  } catch (e) {
    if (current === id) down("trader", e.message, () => select(id));
    return;
  }
  if (current !== id) return;
  LAST = { r, t: tg };
  render(r, tg);
  updateBanner(id);
}
// the first-byte banner is rendered by the server for wallet B; this keeps it true for whichever trader is on screen
async function updateBanner(id) {
  const line = $("#vbline"); if (!line) return;
  try {
    const r = await fetch("/api/banner/" + encodeURIComponent(id)); if (!r.ok || current !== id) return;
    const b = await r.json();
    line.innerHTML = `<span data-l="en">${esc(b.en)}</span><span data-l="zh">${esc(b.zh)}</span>`;
    const t = traders.find((x) => x.id === id) || {};
    if (t.role === "import") line.insertAdjacentHTML("beforeend", `<span class="vb-you" data-l="en"> Your habit, your rule, your gate: the finding is below, a rule that passes can be armed in the Rulebook, and the gate then checks your next order idea.</span><span class="vb-you" data-l="zh"> 你的习惯、你的规则、你的闸门：发现在下方，通过的规则可在规则手册里启用，之后闸门会检查你的下一个下单想法。</span>`);
  } catch (e) { /* the server-rendered sentence stays */ }
}

// ---------------------------------------------------------------- the fills tile: drop a CSV, or use the shipped sample
async function importFills(text, what) {
  const msg = $("#dzmsg"); if (!msg) return;
  if (!text || !text.trim()) { msg.textContent = "That file is empty."; return; }
  msg.textContent = "Reading " + what + "…";
  try {
    const r = await fetch("/api/import", { method: "POST", headers: HDR, body: JSON.stringify({ text }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { msg.textContent = typeof j.detail === "string" ? j.detail : "That file could not be read."; return; }
    msg.textContent = `Read ${j.n_trips} round trips. Your habit, your rule and your gate are below.`;
    await boot(j.id);
    const f = $("#onelook"); if (f) { f.scrollIntoView({ block: "start" }); flash(f); }
  } catch (e) { msg.textContent = "The server could not be reached; nothing was stored."; }
}
function wireFills() {
  const z = $("#dropzone"); if (!z || z.dataset.wired) return; z.dataset.wired = "1";
  const readFile = (f) => {
    if (!f) return;
    if (f.size > 2000000) { $("#dzmsg").textContent = "That file is larger than 2 MB."; return; }
    const rd = new FileReader(); rd.onload = () => importFills(String(rd.result || ""), f.name); rd.readAsText(f);
  };
  $("#dzfile").addEventListener("change", (e) => readFile(e.target.files && e.target.files[0]));
  $("#dzsample").addEventListener("click", async () => {
    $("#dzmsg").textContent = "Loading the sample…";
    try { const r = await fetch("/api/sample-fills"); if (!r.ok) throw new Error(r.status); await importFills(await r.text(), "the sample"); }
    catch (e) { $("#dzmsg").textContent = "The sample could not be loaded."; }
  });
  ["dragenter", "dragover"].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.remove("over"); }));
  z.addEventListener("drop", (e) => readFile(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]));
  const vb = $("#vbanner"); if (vb) vb.addEventListener("click", (e) => { const b = e.target.closest("button[data-pick]"); if (b) { select(b.dataset.pick); const m = $("#onelook"); if (m) m.scrollIntoView({ block: "start" }); } });
}

// ---------------------------------------------------------------- the hero chart
function chart(t) {
  const W = 760, H = 232, pad = { l: 58, r: 14, t: 26, b: 28 };
  const a = t.curve_actual, b = t.curve_rule;
  const xs = a.map((p) => p[0]), x0 = Math.min(...xs), x1 = Math.max(...xs);
  const ys = a.concat(showRule ? b : []).map((p) => p[1]);
  let y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys); if (y1 === y0) y1 = y0 + 1;
  const X = (x) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const Y = (y) => pad.t + (1 - (y - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const path = (pts) => pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
  const cutX = X(t.cut_time_ms);
  const tickVals = [y0, y0 + (y1 - y0) / 2, y1];
  const ticks = tickVals.map((v) => `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--line-2)"/><text x="${pad.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${usd(v).replace("+", "")}</text>`).join("");
  const zero = (y0 < 0 && y1 > 0) ? `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="var(--muted)" stroke-width="1"/>` : "";
  const endA = a[a.length - 1][1], endB = b[b.length - 1][1];
  const last = (pts, cls, r) => { const p = pts[pts.length - 1]; return `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="${r}" fill="${cls}" stroke="var(--surface)" stroke-width="2"/>`; };
  const sv = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative profit and loss by trip, with and without the rule; the shaded part is trades the rule never saw">
    <title>What happened: ${usd(endA)}. With the rule: ${usd(endB)}.</title>
    ${ticks}
    <rect x="${cutX.toFixed(1)}" y="${pad.t}" width="${(W - pad.r - cutX).toFixed(1)}" height="${H - pad.t - pad.b}" fill="var(--shade)"/>
    <line x1="${cutX.toFixed(1)}" x2="${cutX.toFixed(1)}" y1="${pad.t - 4}" y2="${H - pad.b}" stroke="var(--accent)" stroke-dasharray="4 3"/>
    <text x="${(cutX - 6).toFixed(1)}" y="${pad.t - 10}" text-anchor="end" font-size="11" fill="var(--muted)">rule learned on this part</text>
    <text x="${(cutX + 6).toFixed(1)}" y="${pad.t - 10}" font-size="11" font-weight="600" fill="var(--accent)">tested on trades it never saw</text>
    ${zero}
    <path d="${path(a)}" fill="none" stroke="var(--curve)" stroke-width="2" stroke-linejoin="round"/>
    ${showRule ? `<path d="${path(b)}" fill="none" stroke="var(--accent)" stroke-width="2.6" stroke-linejoin="round"/>` : ""}
    ${last(a, "var(--curve)", 4)}${showRule ? last(b, "var(--accent)", 4.5) : ""}
    <text x="${pad.l}" y="${H - 8}" font-size="11" fill="var(--muted)">${day(x0)}</text>
    ${cutX - pad.l > 90 && W - pad.r - cutX > 90 ? `<text x="${cutX.toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${day(t.cut_time_ms)}</text>` : ""}
    <text x="${W - pad.r}" y="${H - 8}" text-anchor="end" font-size="11" fill="var(--muted)">${day(x1)}</text>
    <rect class="hit" x="${pad.l}" y="${pad.t}" width="${W - pad.l - pad.r}" height="${H - pad.t - pad.b}" fill="transparent"/>
  </svg>`;
  const legend = `<div class="legend"><span><i aria-hidden="true"></i><span>what happened:</span> <b>${usd(endA)}</b></span>${showRule ? `<span><i class="rl" aria-hidden="true"></i><span>with the rule:</span> <b>${usd(endB)}</b></span>` : ""}<span><i class="shade" aria-hidden="true"></i><span>trades the rule never saw</span></span><span class="tag">Net of fees.</span></div>`;
  return { svg: sv, legend, X, Y, a, b, pad, W, H };
}
function wireHover(host, c) {
  const svg = host.querySelector("svg"), tip = host.querySelector(".tip"); if (!svg || !tip) return;
  const move = (ev) => {
    const box = svg.getBoundingClientRect(); const fx = (ev.clientX - box.left) / box.width * c.W;
    let best = 0, d = Infinity;
    c.a.forEach((p, i) => { const dd = Math.abs(c.X(p[0]) - fx); if (dd < d) { d = dd; best = i; } });
    const p = c.a[best], q = c.b[best];
    tip.innerHTML = `${day(p[0])}<br><span>what happened</span> <b>${usd(p[1])}</b>${showRule && q ? `<br><span>with the rule</span> <b>${usd(q[1])}</b>` : ""}`;
    tip.style.left = (c.X(p[0]) / c.W * box.width) + "px"; tip.style.top = (c.Y(p[1]) / c.H * box.height) + "px"; tip.style.display = "block";
  };
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerleave", () => { tip.style.display = "none"; });
}

// ---------------------------------------------------------------- the one finding
const PROV = { REAL_PLATFORM_PUBLIC: "Real public data", REAL_OWN: "Your own data (as imported)", SIM_PLANTED: "Simulated", SIM_PAPER: "Paper", REPLAY_NATIVE: "Recorded Bitget book" };
function findingHtml(r, t) {
  const h = r.headline, f = h.finding, sg = h.suggestive, p = h.priced;
  const ruleStatus = (t && t.rule_key === "cap") ? t.status : p.status;
  const ruleWhy = ruleStatus === "ACCEPTED" ? "On trades it never saw, the rule helped." : ruleStatus === "UNDERPOWERED" ? "Not enough trades to judge this rule yet." : "On trades it never saw, the rule did not hold up.";
  let head, habitBadge, why;
  const x = f || sg;
  if (x) {
    head = `<span class="hl-name">${esc(detName[x.detector] || x.detector)}</span>: <span class="ratio">${x.ratio.toFixed(2)}×</span>
      <small><span>median ratio,</span> <span>range ${x.ci[0].toFixed(2)} to ${x.ci[1].toFixed(2)}, p=${x.p.toFixed(3)}</span> · <span>${num(x.n_a)} vs ${num(x.n_b)} trips</span></small>`;
    habitBadge = badge(f ? "FLAGGED" : "SUGGESTIVE");
    why = f ? `<span>Tested within this trader's own fills, not against other people. The pre-declared cap rule prices it below.</span>`
      : `<span>Looks real on its own (p=${x.p.toFixed(3)}) but does not survive the correction for the ${num(r.findings.length)} habit tests run (adjusted p=${x.p_adj.toFixed(3)}), so it is not called a habit.</span>`;
  } else {
    head = `<span>No habit passes the test for this trader.</span><small><span>${h.underpowered ? num(h.underpowered) + " of " + num(r.findings.length) + " checks do not have enough trades yet." : "All " + num(r.findings.length) + " checks ran."}</span></small>`;
    habitBadge = badge(h.underpowered && h.underpowered >= r.findings.length ? "UNDERPOWERED" : "NOT_FLAGGED");
    why = `<span>That is a result, not a gap: the engine is meant to leave a trader alone when the data does not call for a rule.</span>`;
  }
  const c = h.court;
  const arm = c.accepted ? "Rules that passed can be sent to your rulebook below and armed with one click." : "No rule has earned arming yet.";
  const primary = ruleStatus === "ACCEPTED"
    ? `<button type="button" class="btn primary" id="act-court">Send this rule to the court, then arm it <span class="arrow">→</span></button><button type="button" class="btn link" id="act-ask">Ask: what is my biggest costly habit?</button>`
    : `<button type="button" class="btn primary" id="act-ask">Ask: what is my biggest costly habit? <span class="arrow">→</span></button><button type="button" class="btn link" id="act-court">Send this rule to the court anyway</button>`;
  return `<article class="finding" id="onelook" aria-labelledby="hero-h">
    <p class="eyebrow"><span class="no">01</span><span>The one finding</span><span class="fill"></span><span>${r.trader.role === "import" ? "Your import" : "Wallet " + esc(r.trader.id)}</span></p>
    <h2 class="finding-h" id="hero-h">${head}</h2>
    <div class="verdicts">
      <div class="verdict"><span class="vlabel">Habit</span>${habitBadge}</div>
      <div class="verdict"><span class="vlabel">Rule: cap at 1.5x after a loss</span>${badge(ruleStatus)}</div>
    </div>
    <div class="price">
      <div class="price-big"><b class="money ${ruleStatus === "UNDERPOWERED" ? "zero" : sign(p.held_out_effect)}">${usd(p.held_out_effect)}</b><span>on trades the rule never saw</span></div>
      <div class="price-small"><b class="${ruleStatus === "UNDERPOWERED" ? "zero" : sign(p.all_history_effect)}">${usd(p.all_history_effect)}</b> <span>over the whole history</span><span class="range"><span>range ${usd(p.all_history_ci[0])} to ${usd(p.all_history_ci[1])}</span></span></div>
    </div>
    <p class="finding-plain">${esc(h.plain || "")}</p>
    <details class="finding-details"><summary>The numbers behind this</summary><p class="finding-why">${why} <span>${ruleWhy}</span></p></details>
    <div class="actions">${primary}</div>
    ${r.validation_note ? `<p class="finding-note" role="note"><span data-l="en">${esc(r.validation_note.en)} <a href="${r.validation_note.doc_url}">${esc(r.validation_note.doc)}</a> · <a href="${r.validation_note.proof_url}">proof</a></span><span data-l="zh">${esc(r.validation_note.zh)} <a href="${r.validation_note.doc_url}">${esc(r.validation_note.doc)}</a> · <a href="${r.validation_note.proof_url}">证明</a></span></p>` : ""}
    <p class="finding-court">Rule court: ${num(c.proposed)} proposed, ${num(c.tested)} tested, ${num(c.accepted)} accepted on unseen trades. ${arm}</p>
  </article>`;
}

// ---------------------------------------------------------------- page
function chartCard(t) {
  const c = chart(t);
  const hold = t.status === "UNDERPOWERED"
    ? `<span>Not enough trades to judge this rule yet:</span> <span>${esc(t.reason)}.</span>`
    : `<span>${t.status === "ACCEPTED" ? "On trades it never saw, the rule helped." : "On trades it never saw, the rule did not hold up."}</span> <span>${esc(t.reason)}.</span>`;
  return `<figcaption class="chart-head">
      <p class="eyebrow"><span class="no">02</span><span>Profit and loss, with and without the rule</span></p>
      <div class="toggle"><label class="switch" for="tg"><input type="checkbox" id="tg" ${showRule ? "checked" : ""}><span>Apply rule:</span></label>
        <select id="rk" aria-label="Choose a rule"><option value="cap" ${ruleKey === "cap" ? "selected" : ""}>cap opening size after a loss at 1.5x your median</option><option value="halt" ${ruleKey === "halt" ? "selected" : ""}>halt for the day after 2 consecutive losing trips</option></select></div>
    </figcaption>
    <div class="chartwrap">${c.svg}<div class="tip" role="presentation"></div></div>${c.legend}
    <div class="nums">
      <div class="num"><span class="lbl">Learned on</span><b class="${t.status === "UNDERPOWERED" ? "zero" : sign(t.in_sample.effect)}">${usd(t.in_sample.effect)}</b><span>on the trades it was built from (${num(t.in_sample.n_skipped)} trips skipped)</span></div>
      <div class="num held"><span class="lbl">Never seen</span><b class="${t.status === "UNDERPOWERED" ? "zero" : sign(t.held_out.effect)}">${usd(t.held_out.effect)}</b><span>on trades it never saw (${num(t.held_out.n_skipped)} skipped)</span></div>
    </div>
    <div class="chart-foot">${badge(t.status)}<span class="foot-why">${hold}</span></div><p class="chart-note">${esc(t.note)}</p>`;
}
function drawChart(t) {
  const fig = $("#hero-chart"); if (!fig) return;
  fig.innerHTML = chartCard(t);
  wireHover(fig.querySelector(".chartwrap"), chart(t));
  $("#tg").addEventListener("change", (e) => { showRule = e.target.checked; drawChart(t); });
  $("#rk").addEventListener("change", (e) => { ruleKey = e.target.value; select(current); });
}
function render(r, t) {
  $("#strip").innerHTML = `<span class="chip prov"><span class="dot" aria-hidden="true"></span>${esc(PROV[r.trader.provenance] || r.trader.provenance)}</span><span class="chip">${r.ledger.fills ? r.ledger.fills.toLocaleString() + " fills → " + r.ledger.orders.toLocaleString() + " orders → " : "simulated, "}${num(r.ledger.round_trips)} round trips</span><span class="chip">${esc(r.trader.label)}</span>`;
  const f = r.findings.map((x) => `<tr><td>${esc(detName[x.detector] || x.detector)}</td><td>${badge(x.status)}</td>
      <td class="n">${x.ratio == null ? "–" : x.ratio.toFixed(2) + "×"}</td><td class="n">${x.ci ? "[" + x.ci[0].toFixed(2) + ", " + x.ci[1].toFixed(2) + "]" : "–"}</td>
      <td class="n">${x.p == null ? "–" : x.p.toFixed(3)}</td><td class="n">${x.p_adj == null ? "–" : x.p_adj.toFixed(3)}</td><td class="n">${num(x.n_a)} / ${num(x.n_b)}</td></tr>`).join("");
  const v = r.court.verdicts.map((x) => `<tr><td>${esc(x.rule)}</td><td>${badge(x.status)}</td><td class="n ${sign(x.held_out_effect)}">${usd(x.held_out_effect)}</td>
      <td class="n">${num(x.affected)} of ${num(x.test_trips)}</td><td class="n">${x.p == null ? "–" : x.p.toFixed(3)}</td><td class="n">${num(x.threshold)}</td></tr>`).join("");
  const _fid = document.activeElement && document.activeElement.id;   // keep keyboard focus across a re-render
  $("#main").innerHTML = `
  <section class="hero" aria-label="The finding and the rule chart">
    ${findingHtml(r, t)}
    <figure class="chartcard" id="hero-chart"></figure>
    <section class="thesis" id="thesis-card" aria-label="Your trading thesis"></section>
    <section class="ask" id="ask" aria-labelledby="ask-h">
      <div class="askbar">
        <p class="eyebrow" id="ask-h"><span class="no">03</span><span>Ask about this trader</span><span class="fill"></span><span>English or 中文</span></p>
        <form class="askrow" id="cf"><input id="ci" maxlength="500" placeholder="Ask in English or 中文, for example: what is my biggest costly habit?" aria-label="Ask a question" autocomplete="off"><button type="submit">Ask</button></form>
        <div class="chips grouped" id="chips"></div>
      </div>
      <div class="asklog" id="asklog">
        <div id="chatlog" aria-live="polite"></div><div class="tag" id="llmnote"></div>
        <p class="ask-note">Answers are computed; a language model only reads an unclear question and never writes a number.</p>
      </div>
    </section>
  </section>
  <section class="sec scroll" id="court" aria-labelledby="court-h">
    <p class="eyebrow"><span class="no">04</span><span>Evidence</span></p>
    <h2 class="sec-h" id="court-h">Habits found, each tested within this one trader</h2>
    <table><caption class="vh">Habit tests: result, effect size and adjusted p</caption><thead><tr><th>Habit</th><th>Result</th><th>Size of effect</th><th>Range (95%)</th><th>p</th><th>Adjusted p</th><th>Trades in each group</th></tr></thead><tbody>${f}</tbody></table>
    <h2 class="sec-h" style="margin-top:18px">Rule court: ${num(r.court.proposed)} rules proposed, ${num(r.court.tested)} tested, ${num(r.court.accepted)} accepted</h2>
    ${r.validation_note ? `<p class="finding-note" role="note"><span data-l="en">${esc(r.validation_note.en)}</span><span data-l="zh">${esc(r.validation_note.zh)}</span></p>` : ""}
    <p class="sec-lead">Every proposal is counted, so the bar for acceptance rises with each rule tried.</p>
    <table><caption class="vh">Rule court: verdict on unseen trades</caption><thead><tr><th>Rule</th><th>Verdict</th><th>Effect on unseen trades</th><th>Trades it touched</th><th>p</th><th>Bar to clear</th></tr></thead><tbody>${v}</tbody></table></section>
  <section class="sec" id="rbcard" aria-labelledby="rb-h">
    <p class="eyebrow"><span class="no">05</span><span>Act</span></p>
    <h2 class="sec-h" id="rb-h">Rulebook and Rule Gate</h2>
    <p class="sec-lead">Your own sandbox: nothing here places an order, and it resets when your session ends. A rule only guards your orders after you click Arm.</p>
    <div class="rb">
      <div>
        <div class="rbbar"><span>Send a rule to the court:</span>
          <select id="rbm" aria-label="Rule to test"><option value="1.0">cap at 1.0x median</option><option value="1.5" selected>cap at 1.5x median</option><option value="2.0">cap at 2.0x median</option><option value="3.0">cap at 3.0x median</option></select>
          <button type="button" id="rbgo">Test it</button><span class="tag" id="rbmsg" aria-live="polite"></span></div>
        <div id="rblist"></div><div class="tag" id="rbchain"></div>
        <h2 style="margin-top:14px" id="checklist">Your checklist (most five stored, three shown)</h2><div id="rbchk"></div>
      </div>
      <div class="gate" id="gate">
        <h2>Check an order idea</h2>
        <form class="askrow" id="gf"><input id="gi" maxlength="300" placeholder="e.g. Buy $20k rNVDA" aria-label="Order idea"><button class="gatebtn" type="submit">Check</button></form>
        <label class="tag"><input type="checkbox" id="gloss"> my last trade was a loss (otherwise taken from the record)</label>
        <div id="gres" aria-live="polite"></div>
      </div>
    </div></section>
  <section class="sec" id="winrate-card" aria-labelledby="wr-h">
    <p class="eyebrow"><span class="no">06</span><span>Costs</span></p>
    <h2 class="sec-h" id="wr-h">Do your costs leave room? Required win rate at your real costs</h2>
    <div class="nums">
      <div class="num"><b>${pct(r.winrate.breakeven)}</b><span>win rate you need to break even (95% range ${pct(r.winrate.breakeven_ci[0])} to ${pct(r.winrate.breakeven_ci[1])})</span></div>
      <div class="num"><b>${pct(r.winrate.actual)}</b><span>win rate you have; gap range ${pp(r.winrate.margin_ci[0])} to ${pp(r.winrate.margin_ci[1])}</span></div>
    </div>
    <p class="tag" style="margin:8px 0 0">Without your single best trade the break-even win rate is ${pct(r.winrate.without_best.breakeven)}. ${r.fee_drag ? "Fees took " + pct(r.fee_drag.share) + " of gross profit (range " + (r.fee_drag.ci ? pct(r.fee_drag.ci[0]) + " to " + pct(r.fee_drag.ci[1]) : "n/a") + ")." : ""} These are intervals, not probabilities.</p>
  </section>`;
  if (_fid) { const el = document.getElementById(_fid); if (el && el.closest("#main")) el.focus({ preventScroll: true }); }
  drawChart(t);
  $("#chips").innerHTML = chipsHtml();
  $("#chips").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) ask(b.textContent); });
  $("#chatlog").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-q]"); if (b) return ask(b.dataset.q);
    const f = e.target.closest("button[data-fb]"); if (f) return sendFeedback(+f.dataset.i, f.dataset.fb);
    const u = e.target.closest("button[data-full]"); if (u) ask(u.dataset.full === "zh" ? "给我看这周的复盘" : "Show my weekly review");
  });
  $("#cf").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#ci").value; $("#ci").value = ""; ask(v); });
  $("#act-ask").addEventListener("click", () => { ask("What is my biggest costly habit?"); $("#ask").scrollIntoView({ block: "start" }); $("#ci").focus({ preventScroll: true }); });
  $("#act-court").addEventListener("click", () => { $("#rbm").value = "1.5"; $("#rbcard").scrollIntoView({ block: "start" }); $("#rbgo").click(); flash($("#rbcard")); });
  renderLog();
  wireBook();
  if (window.loadThesis) loadThesis(r.trader.id);
}
function flash(el) { if (!el) return; el.classList.add("hl"); setTimeout(() => el.classList.remove("hl"), 1800); }

// ---------------------------------------------------------------- sticky mini-nav: current section
function wireNav() {
  const links = [...document.querySelectorAll(".mini a")]; if (!links.length || !("IntersectionObserver" in window)) return;
  const seen = new Map();
  const io = new IntersectionObserver((es) => {
    es.forEach((e) => seen.set(e.target.id, e.isIntersecting));
    const first = links.map((l) => l.getAttribute("href").slice(1)).find((id) => seen.get(id));
    links.forEach((l) => l.setAttribute("aria-current", l.getAttribute("href") === "#" + first ? "true" : "false"));
  }, { rootMargin: "-56px 0px -60% 0px" });
  const watch = () => links.forEach((l) => { const el = document.getElementById(l.getAttribute("href").slice(1)); if (el) io.observe(el); });
  new MutationObserver(watch).observe($("#main"), { childList: true });
  watch();
}

// ---------------------------------------------------------------- 中文 for the strings this file adds (English is the source)
if (typeof ZH_EXACT !== "undefined") {
  Object.assign(ZH_EXACT, {
    "Trade review that tests its own rules": "先测试自己的规则，再让你相信的交易复盘",
    "Finding": "发现", "Chart": "曲线", "Ask": "提问", "Court": "法庭", "Rulebook": "规则手册", "Costs": "成本", "Report": "报告",
    "What we got wrong": "我们错在哪里", "Cockpit": "评委驾驶舱", "Skip to the review": "跳到复盘",
    "◑ Dark": "◑ 深色", "◐ Light": "◐ 浅色",
    "Every number computed from fills at load": "每个数字都在加载时由成交记录计算",
    "control": "对照组", "simulated": "模拟", "The one finding": "唯一的发现", "Habit": "习惯",
    "Rule: cap at 1.5x after a loss": "规则：亏损后上限 1.5 倍", "△ suggestive, not proven": "△ 有提示，未证实",
    "Not enough trades to judge this rule yet:": "交易还不够，暂时无法判断这条规则：",
    "median ratio,": "中位数比值，", "on trades the rule never saw": "在规则没见过的交易上", "over the whole history": "整段历史",
    "On trades it never saw, the rule helped.": "在没见过的交易上，这条规则有帮助。",
    "On trades it never saw, the rule did not hold up.": "在没见过的交易上，这条规则没有站住。",
    "Not enough trades to judge this rule yet.": "交易还不够，暂时无法判断这条规则。",
    "Tested within this trader's own fills, not against other people. The pre-declared cap rule prices it below.": "只在这位交易者自己的成交记录里检验，不与他人比较。下面用事先定好的上限规则给它定价。",
    "No habit passes the test for this trader.": "这位交易者没有习惯通过检验。",
    "That is a result, not a gap: the engine is meant to leave a trader alone when the data does not call for a rule.": "这是一个结果，不是缺口：数据不需要规则时，引擎就该放过交易者。",
    "Ask: what is my biggest costly habit?": "提问：我最大的坏习惯是什么？",
    "Send this rule to the court, then arm it": "把这条规则送去法庭，然后启用它", "Send this rule to the court anyway": "还是把这条规则送去法庭试试",
    "Profit and loss, with and without the rule": "有规则与无规则的盈亏对比",
    "cap opening size after a loss at 1.5x your median": "亏损后把开仓大小限制在你中位数的 1.5 倍",
    "what happened:": "实际发生：", "with the rule:": "套用规则：", "trades the rule never saw": "规则没见过的交易", "Net of fees.": "已扣手续费。",
    "what happened": "实际发生", "with the rule": "套用规则", "Learned on": "建立规则的部分", "Never seen": "没见过的部分",
    "English or 中文": "中文或 English", "Evidence": "证据", "Act": "行动",
    "Answers are computed; a language model only reads an unclear question and never writes a number.": "答案都是计算出来的；语言模型只用来读懂不清楚的问题，从不写数字。",
    "Computing from fills…": "正在根据成交记录计算…", "Ask again": "再问一次", "■ No answer came back": "■ 没有收到回答",
    "the service could not be reached. The numbers on the page are still correct.": "无法连接服务。页面上的数字仍然正确。",
    "too many questions at once; wait a moment.": "问题太多了，请稍等。",
    "The review engine is not reachable": "无法连接复盘引擎", "This trader could not be loaded right now": "暂时无法加载这位交易者",
    "This page draws every number from the Loop API when it loads, and no answer came back.": "本页的每个数字都在加载时从 Loop API 获取，但没有收到回应。",
    "The server may be busy computing another review.": "服务器可能正忙于计算另一份复盘。",
    "Nothing is shown from a cache or typed by hand, so instead of a stale number you see this notice. When the API is up, this screen shows:": "不展示缓存或手填的数字，所以你看到的是这条提示而不是过期数据。API 恢复后，这个页面会显示：",
    "one habit per trader, tested within that trader's own fills and priced in dollars,": "每位交易者一个习惯，只在其自己的成交记录里检验，并以美元定价；",
    "the profit curve with and without a rule, split into learned-on and never-seen trades,": "有规则与无规则的盈亏曲线，分为建立规则的交易和没见过的交易；",
    "the rule court, your rulebook and the order gate, and a chat that answers in English or 中文.": "规则法庭、你的规则手册和下单闸门，以及中英文都能回答的对话。",
    "Try again": "重试", "Judge cockpit": "评委驾驶舱",
    "Receipt": "回执", "Sources": "来源", "Computed": "计算", "Rows": "数据行", "Ledger": "记录", "Trace": "过程", "Numbers": "数字",
    "Did this answer your question?": "这个回答解决了你的问题吗？", "Helpful": "有帮助", "Not helpful": "没帮助", "Run the full review on this": "对此运行完整复盘",
    "New trader": "新手", "Review": "复盘", "Rules": "规则", "What would make this wrong": "什么情况下会错", "What did the gate block": "闸门拦下了什么",
    "Marked helpful": "已标记为有帮助", "Marked not helpful": "已标记为没帮助",
  });
  ZH_PATTERNS.push(
    [/^out-of-sample effect is not positive\.?$/, "未见交易上的效果不是正的。"],
    [/^out-of-sample effect is positive but p=([\d.]+) does not clear the trial-adjusted threshold ([\d.]+)\.?$/, "未见交易上的效果是正的，但 p=$1 没有跨过按试验次数调整的门槛 $2。"],
    [/^out-of-sample effect is positive and p=([\d.]+) is below the trial-adjusted threshold ([\d.]+)\.?$/, "未见交易上的效果是正的，且 p=$1 低于按试验次数调整的门槛 $2。"],
    [/^out-of-sample part has (\d+) trips and the rule touches (\d+); needs (\d+) and (\d+)\.?$/, "未见部分有 $1 笔交易，规则只涉及 $2 笔；需要 $3 和 $4。"],
    [/^held-out effect is not positive\.?$/, "未见交易上的效果不是正的。"],
    [/^(\d+) trips$/, "$1 笔交易"],
    [/^range ([\d.]+) to ([\d.]+), p=([\d.]+)$/, "范围 $1 到 $2，p=$3"],
    [/^(\d+) vs (\d+) trips$/, "两组 $1 笔对 $2 笔"],
    [/^range (.*) to (.*)$/, "范围 $1 到 $2"],
    [/^Looks real on its own \(p=([\d.]+)\) but does not survive the correction for the (\d+) habit tests run \(adjusted p=([\d.]+)\), so it is not called a habit\.$/, "单看像是真的（p=$1），但经过 $2 项习惯检验的多重校正后站不住（校正后 p=$3），所以不算习惯。"],
    [/^(\d+) of (\d+) checks do not have enough trades yet\.$/, "$2 项检查中有 $1 项交易还不够。"],
    [/^All (\d+) checks ran\.$/, "全部 $1 项检查都已运行。"],
    [/^What happened: (.*)\. With the rule: (.*)\.$/, "实际发生：$1。套用规则：$2。"],
    [/^Retrying by itself in (\d+) s…$/, "$1 秒后自动重试…"],
    [/^(\d+) of (\d+) round trips$/, "$2 笔完整交易中的 $1 笔"], [/^(\d+) round trips$/, "$1 笔完整交易"],
    [/^(\d+) computed facts; lock (.*)$/, "$1 个计算出的事实；数字锁：$2"],
    [/^Read (\d+) round trips\. Your habit, your rule and your gate are below\.$/, "已读取 $1 笔完整交易。你的习惯、你的规则和你的闸门在下方。"],
    [/^the service answered (\d+)\. The numbers on the page are still correct\.$/, "服务返回了 $1。页面上的数字仍然正确。"],
  );
}

wireFills();
boot();
