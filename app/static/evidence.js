"use strict";
// Script for /evidence (external so the CSP needs no new inline hash).
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const vbadge = (v) => {
  const m = { "answers": ["b-ok", "answers"], "handshake only": ["b-warn", "handshake only, data calls fail"], "no answer": ["b-bad", "no answer"],
              "answering": ["b-ok", "answering"], "down": ["b-bad", "down"], "not asked yet": ["b-grey", "not asked yet"],
              "error": ["b-bad", "error"], "empty": ["b-warn", "empty"], "needs key": ["b-grey", "needs key"] }[v] || ["b-grey", v];
  return `<span class="badge ${m[0]}">${esc(m[1])}</span>`;
};
function pathBlock(p) {
  const rows = [...p.answered, ...p.not_answered].map((o) => `<tr><td>${esc(o.operation)}${o.note ? `<small>${esc(o.note)}</small>` : ""}</td>
    <td class="n">${esc(o.status)}</td><td class="n">${o.latency_ms == null ? "–" : esc(o.latency_ms) + " ms"}</td><td>${vbadge(o.verdict)}</td></tr>`).join("");
  return `<div class="path"><h3>${esc(p.label)}</h3>${vbadge(p.verdict)}<span class="tag">${esc(p.data_calls_answered)} data call(s) answered of ${esc(p.calls)} calls</span></div>
    <div class="scroll"><table><thead><tr><th>Call</th><th>Status</th><th>Latency</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function render(d) {
  const h = d.headline, pr = d.probe, ca = d.context_adapter;
  const probeOrigin = (d.call_log.by_origin || {}).probe || { calls: 0, distinct_operations: 0, distinct_operations_answered: 0 };
  let html = `<section class="card"><h2>What the product calls</h2>
    <div class="nums">
      <div class="num"><b>${esc(h.product_bitget_operations_called)}</b><span>distinct Bitget operations the running product called (handshakes not counted)</span></div>
      <div class="num"><b>${esc(h.product_bitget_operations_answered)}</b><span>of those answered at least once</span></div>
      <div class="num"><b>${esc(h.product_calls)}</b><span>product calls in the log</span></div>
      <div class="num"><b>${esc(probeOrigin.distinct_operations_answered)} / ${esc(probeOrigin.distinct_operations)}</b><span>probe operations answered / tried</span></div>
    </div><p class="honest">${esc(h.note)}</p></section>`;
  html += `<section class="card"><h2>Context adapter (background, never on the request path)</h2>
    <p class="tag">Last pass ${esc(ca.last_pass || "never")} · passes ${esc(ca.passes)} · refresher ${esc(ca.refresher)}</p>
    <div class="scroll"><table><thead><tr><th>Source</th><th>State</th><th>Last answer</th><th>Detail</th></tr></thead><tbody>
    ${ca.sources.map((s) => `<tr><td>${esc(s.name)}</td><td>${vbadge(s.state)}</td><td class="n">${esc(s.last_ok || "–")}</td><td><small>${esc(s.detail)}</small></td></tr>`).join("")}
    </tbody></table></div>
    <div class="ctx"><input id="sym" value="NVDA" aria-label="Symbol" maxlength="32"><input id="day" type="date" aria-label="Trade day"><button id="go" type="button">Show the context line</button></div>
    <div id="ctxout"></div></section>`;
  if (pr) {
    html += `<section class="card"><h2>Probe of every keyless Bitget AI tool path</h2>
      <p class="tag">File ${esc(d.evidence_file)} · run ${esc(pr.generated_at)} · ${esc(pr.rules)}</p>
      ${pr.paths.map(pathBlock).join("")}`;
    if (pr.agent_hub_surface) {
      const s = pr.agent_hub_surface;
      html += `<div class="path"><h3>Agent Hub surface (bgc discover)</h3><span class="tag">${esc(s.public)} public of ${esc(s.operations)} operations; every other one needs a key</span></div>
        <div class="scroll"><table><thead><tr><th>Domain</th><th>Operations</th><th>Public</th><th>Writes</th></tr></thead><tbody>
        ${Object.entries(s.by_domain).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${esc(v.operations)}</td><td class="n">${esc(v.public)}</td><td class="n">${esc(v.writes)}</td></tr>`).join("")}
        </tbody></table></div>`;
    }
    html += `</section>`;
  } else {
    html += `<section class="card"><h2>Probe</h2><p class="err">${esc(d.probe_missing_reason)}</p></section>`;
  }
  $("#main").innerHTML = html;
  $("#day").value = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  $("#go").onclick = async () => {
    const out = $("#ctxout");
    try {
      const r = await fetch(`/api/evidence/context?symbol=${encodeURIComponent($("#sym").value)}&day=${encodeURIComponent($("#day").value)}`);
      const c = await r.json();
      if (!r.ok) { out.innerHTML = `<p class="err">Could not read that (${esc(r.status)}).</p>`; return; }
      out.innerHTML = c.available
        ? `<p class="honest"><span class="badge b-grey">${esc(c.label)}</span> ${esc(c.text)}<br><small class="tag">${esc(c.source_name)} · ${esc(c.operation)} · fetched ${esc(c.fetched_at)}${c.state === "stale" ? " · stale" : ""}</small></p>`
        : `<p class="honest"><span class="badge b-grey">${esc(c.label)}</span> ${esc(c.text)}</p>`;
    } catch (e) { out.innerHTML = `<p class="err">Could not reach the server.</p>`; }
  };
}
fetch("/api/evidence").then((r) => r.json()).then(render).catch(() => { $("#main").innerHTML = `<p class="err">Could not load /api/evidence.</p>`; });
