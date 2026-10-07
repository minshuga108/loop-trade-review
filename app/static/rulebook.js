// Rulebook card and Rule Gate. Uses globals from index.html: $, esc, current, HDR.
const stBadge = (s) => ({
  ACCEPTED: ["b-ok", "✔ accepted, waiting for you"], ARMED: ["b-ok", "● armed"], PENDING_RETIREMENT: ["b-warn", "▲ pending retirement"],
  RETIRED: ["b-grey", "○ retired"], QUARANTINED: ["b-bad", "✖ quarantined"], UNDERPOWERED: ["b-grey", "◌ not enough trades yet"],
  CHECKS_PASSED: ["b-ok", "✔ checks passed"], CHECKS_PASSED_WITH_NOTES: ["b-warn", "▲ passed with notes"],
  REVIEW_NEEDED: ["b-bad", "✖ review needed"], BLOCKED_BY_YOUR_RULES: ["b-bad", "■ blocked by your rules"], COULD_NOT_CHECK: ["b-grey", "◌ could not check"],
}[s] || ["b-grey", s]);
const sb = (s) => { const [c, t] = stBadge(s); return `<span class="badge ${c}">${esc(t)}</span>`; };

// FastAPI errors carry detail as a string, or as a list of {msg} for a 422; a 429 has a plain detail too
const detailText = (d) => Array.isArray(d) ? d.map((x) => (x && x.msg) || String(x)).join("; ") : String(d == null ? "request refused" : d);

function effText(e) {
  if (e.status === "MEASURED") {
    return `n=${e.n_broke} broke it, ${e.n_kept} kept it; keeping it did ${e.better_when_kept >= 0 ? "better" : "worse"} by ` +
      `$${Math.abs(Math.round(e.better_when_kept)).toLocaleString("en-US")} per trade (p=${e.p.toFixed(3)})` +
      `${e.retire_suggested ? "; no effect seen at this sample" : ""}`;
  }
  if (e.status === "NOT_ENOUGH_TRADES") return "not enough trades yet: " + e.reason;
  return e.reason || "";
}

function renderBook(b) {
  if (!$("#rblist")) return;
  $("#rblist").innerHTML = b.entries.length ? b.entries.map((e) => {
    const btn = (a, label, cls) => `<button type="button" class="${cls || ""}" data-a="${a}" data-r="${esc(e.rule_id)}">${label}</button>`;
    let acts = "";
    if (e.state === "ACCEPTED") acts = btn("arm", "Arm this rule", "primary");
    if (e.state === "ARMED") acts = btn("retire_propose", "Propose retirement");
    if (e.state === "PENDING_RETIREMENT") acts = btn("retire_confirm", "Confirm retirement", "primary") + btn("keep", "Keep it");
    if (e.changelog.length > 1 && e.state !== "RETIRED") acts += btn("revert", "Revert to v" + esc(e.version - 1));
    return `<div class="rule"><b>${esc(e.rule_id)}</b> v${esc(e.version)} · cap opening size at ${esc(e.rule.value)}x your median after a loss ${sb(e.state)}
      <div class="tag">${esc(e.reason)} · evidence ${esc(e.evidence)}</div><div class="row">${acts}</div></div>`;
  }).join("") : '<p class="tag">No rules yet. Send one to the court; only a rule that passes on unseen trades can be armed.</p>';
  $("#rbchain").textContent = `${b.proposed} rules proposed so far (every proposal counts) · event log ${b.chain_ok ? "intact (hash-chained)" : "BROKEN"} · ${b.events} events`;
  $("#rbchk").innerHTML = b.checklist.length
    ? b.checklist.map((i) => `<div class="chk">${esc(i.text)}<small>${esc(effText(i.effect))}</small></div>`).join("")
    : '<p class="tag">No checklist items yet: they come from habits that pass the test and from rules you arm.</p>';
}

async function loadBook() {
  try {
    const r = await fetch("/api/rulebook/" + current, { headers: HDR });
    if (r.ok) renderBook(await r.json());
  } catch (e) { $("#rbmsg").textContent = "Could not reach the server. Nothing was changed; check your connection and try again."; }
}

async function bookAction(a, rid) {
  try {
    const r = await fetch("/api/rulebook/" + current + "/" + a, { method: "POST", headers: HDR, body: JSON.stringify({ rule_id: rid }) });
    if (r.ok) renderBook(await r.json()); else $("#rbmsg").textContent = detailText((await r.json()).detail);
  } catch (e) { $("#rbmsg").textContent = "Could not reach the server. Nothing was changed; check your connection and try again."; }
}

const GZH = () => typeof LANG !== "undefined" && LANG === "zh";
const GCHIPS = [["after_loss", "after a loss", "亏损之后"], ["bigger", "bigger than usual", "比平时更大"], ["closed_market", "in a closed market", "休市时"], ["high_funding", "at high funding", "资金费率偏高时"]];
let gScenario = new Set();

function gateChips() {
  const f = $("#gf"); if (!f || $("#gchips")) return;
  f.insertAdjacentHTML("afterend", '<div id="gchips" class="chips" role="group" aria-label="Scenario"></div>');
  const draw = () => { $("#gchips").innerHTML = GCHIPS.map(([k, en, zh]) => `<button type="button" data-sc="${k}" aria-pressed="${gScenario.has(k)}">${esc(GZH() ? zh : en)}</button>`).join(""); };
  draw();
  $("#gchips").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-sc]"); if (!b) return;
    const k = b.dataset.sc, c = GCHIPS.find((x) => x[0] === k), inp = $("#gi");
    if (gScenario.has(k)) { gScenario.delete(k); } else {
      gScenario.add(k);
      if (!inp.value.includes(c[1]) && !inp.value.includes(c[2])) inp.value = (inp.value.trim() + " " + (GZH() ? c[2] : c[1])).trim();
      if (k === "after_loss" && $("#gloss")) $("#gloss").checked = true;
    }
    draw(); inp.focus();
  });
}

function similarBlock(s) {
  if (!s) return "";
  const z = GZH(), usd = (v) => (v >= 0 ? "+" : "-") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const fl = s.filters, bandTxt = fl.size_band.kind === "idea_size_0.5x_to_2x" ? (z ? "金额在这笔想法的 0.5 到 2 倍" : "size 0.5x to 2x of this idea") : fl.size_band.kind === "above_1.5x_median" ? (z ? "金额高于中位数的 1.5 倍" : "size above 1.5x your median") : (z ? "任意金额" : "any size");
  const head = z ? `相似的过往交易（${fl.symbol || "任意品种"}、${fl.side === "buy" ? "做多" : fl.side === "sell" ? "做空" : "任意方向"}、${bandTxt}${fl.after_loss ? "、亏损之后" : ""}${fl.closed_market ? "、休市时" : ""}）` :
    `Similar past trades (${fl.symbol || "any symbol"}, ${fl.side || "any side"}, ${bandTxt}${fl.after_loss ? ", after a loss" : ""}${fl.closed_market ? ", in a closed market" : ""})`;
  const nt = (s.notes || []).map((x) => `<small class="gnote">${esc(z ? x.zh : x.en)}</small>`).join("");
  if (!s.n) return `<div class="chk"><b>${esc(head)}</b>${nt}<small>${z ? "你的记录里没有匹配的交易。" : "None of your past round trips match."}</small></div>`;
  const rows = s.rows.map((r) => `<li><a href="/trade/${encodeURIComponent(current)}/${r.index}">${esc(new Date(r.t_open_ms).toISOString().slice(0, 10))} ${esc(r.symbol)} ${esc(r.side)} $${Math.round(r.notional).toLocaleString("en-US")}</a>: <b>${esc(usd(r.net_pnl))}</b></li>`).join("");
  return `<details class="chk" open><summary><b>${esc(head)}</b>: ${s.n} ${z ? "笔，合计" : "trades, net"} ${esc(usd(s.net_total))}, ${s.wins} ${z ? "笔盈利" : "won"}</summary>${nt}<ul>${rows}</ul><small>${esc(z ? "这些是你自己记录里的事实，不是预测，也不是建议。" : s.label)}</small></details>`;
}

function wireBook() {
  gateChips();
  $("#rbgo").addEventListener("click", async () => {
    $("#rbmsg").textContent = "court is deciding…";
    try {
      const r = await fetch("/api/rulebook/" + current + "/propose", { method: "POST", headers: HDR, body: JSON.stringify({ multiple: parseFloat($("#rbm").value) }) });
      const j = await r.json();
      $("#rbmsg").textContent = r.ok ? `${j.state}: ${j.reason}` : detailText(j.detail);
      if (r.ok) renderBook(j.book);
    } catch (e) { $("#rbmsg").textContent = "Could not reach the server. Nothing was changed; check your connection and try again."; }
  });
  $("#rblist").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) bookAction(b.dataset.a, b.dataset.r); });
  $("#gf").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { text: $("#gi").value };
    if ($("#gloss").checked) body.after_loss = true;
    if (gScenario.size) body.scenario = [...gScenario];
    let r, j;
    try {
      r = await fetch("/api/gate/" + current, { method: "POST", headers: HDR, body: JSON.stringify(body) });
      j = await r.json();
    } catch (err) { $("#gres").innerHTML = '<p class="err">' + "Could not reach the server. Nothing was changed; check your connection and try again." + '</p>'; return; }
    $("#gres").innerHTML = r.ok
      ? `<p>${sb(j.state)}</p><p class="tag">Read: ${esc(j.idea.side || "?")} ${esc(j.idea.symbol || "?")} ${j.idea.notional ? "$" + esc(Number(j.idea.notional).toLocaleString("en-US")) : "(no size found)"}; ` +
        `last trade ${j.last_trade_was_loss ? "was a loss" : "was not a loss"}.</p>` +
        j.reasons.map((x) => `<p>${esc(x)}</p>`).join("") + checkLine(j.check_line) + ctxLine(j.context) + similarBlock(j.similar) + j.checklist.map((i) => `<div class="chk">${esc(i.text)}</div>`).join("") +
        `<p class="tag">${esc(j.note)}</p>`
      : `<p class="err">${esc(detailText(j.detail))}</p>`;
  });
  loadBook();
}

function checkLine(cl) {
  if (!cl) return "";
  if (!cl.available) return `<div class="chk"><b>Check line</b><small>${esc(cl.reason || "no recent book")}</small></div>`;
  const r = cl.report, c = r.cost;
  const fill = c.fill_fraction < 1 ? ` The visible book absorbs only ${(c.fill_fraction * 100).toFixed(0)}% of this size; the rest is not assumed to clear.` : "";
  return `<div class="chk"><b>Check line: about ${c.cost_bps == null ? "?" : c.cost_bps.toFixed(1)} bps versus mid</b>` +
    `<small>${esc(r.symbol)} ${esc(r.provenance)}; book ${Math.round(cl.cache_age_s)} s old${cl.stale ? " (stale: not used by the gate)" : ""}.${fill} ` +
    `${esc(r.slicing.advice || "")} ${esc(r.caveats[r.caveats.length - 1])}</small></div>`;
}

function ctxLine(c) {
  if (!c) return "";
  if (!c.available) return `<div class="chk"><b>Bitget context</b><small>${esc(c.text || "No Bitget skill answered just now.")}</small></div>`;
  return `<div class="chk"><b>Bitget context (not evidence)</b><small>${esc(c.text)} ${esc(c.label || "")}</small></div>`;
}
