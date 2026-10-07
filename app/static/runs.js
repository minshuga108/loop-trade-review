"use strict";
// Renders /runs from /api/runs (external script: the CSP allows no inline code).
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  (function theme() {
    const root = document.documentElement, b = $("#themebtn");
    const isDark = () => root.dataset.theme === "dark" || (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    const apply = (v) => { if (v) root.dataset.theme = v; if (b) b.textContent = isDark() ? "◐ Light" : "◑ Dark"; };
    let t = null; try { t = localStorage.getItem("theme"); } catch (e) {}
    apply(t);
    if (b) b.addEventListener("click", () => { const v = isDark() ? "light" : "dark"; try { localStorage.setItem("theme", v); } catch (e) {} apply(v); });
  })();
  const badge = (s) => `<span class="badge ${s === "scored" ? "b-ok" : s === "missed" ? "b-bad" : "b-warn"}">${esc(s)}</span>`;
  const when = (ts) => new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + "Z";
  const comps = (e) => Object.entries(e.components).map(([k, c]) =>
    `<li><b>${esc(k)}</b> ${badge(c.state)} <small>${esc(c.basis || "")}${typeof c.detail === "string" ? " " + esc(c.detail) : ""}</small></li>`).join("");
  function render(d) {
    const c = d.counts;
    const head = `<p class="tag">${d.n} runs, ${c.scored} scored, ${c.missed} missed, ${c.pending} pending. ${d.chain_ok ? "Chain verified." : "CHAIN BROKEN at entry " + esc(d.broken_at) + "."}</p>
      <p class="honest">Tip <code>${esc(d.tip.slice(0, 16))}</code>. ${esc(d.note)}</p>`;
    if (!d.n) { $("#main").innerHTML = head + `<p class="tag">No runs have been frozen yet.</p>`; return; }
    const rows = d.entries.map((e) => {
      const t = e.predictions.thesis, k = e.predictions.cost;
      return `<tr><td class="n">${esc(e.seq)}</td><td>${esc(when(e.ts))}</td><td>${esc(e.trader)}</td>
        <td><span data-l="en">${esc(t.claim_en)}</span><span data-l="zh">${esc(t.claim_zh)}</span><small>thesis ${esc(t.thesis_hash.slice(0, 12))}${k.available ? " · BTCUSDT cost " + esc(k.cost_bps.toFixed(2)) + " bps" : " · cost unavailable"}</small></td>
        <td><code>${esc(e.hash.slice(0, 12))}</code>${e.chain_ok ? "" : " (chain break)"}<small>prev ${esc(e.prev.slice(0, 8))}</small></td>
        <td>${badge(e.state)}<ul class="plain">${comps(e)}</ul></td></tr>`;
    }).join("");
    $("#main").innerHTML = head + `<div class="scroll"><table><thead><tr><th>#</th><th>Frozen</th><th>Trader</th><th>Prediction</th><th>Hash</th><th>State</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="tag">rule and cost use live data; reproduce is a replay of the engine on the frozen day.</p>`;
  }
  fetch("/api/runs").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(render)
    .catch(() => { $("#main").innerHTML = `<p class="err">The runs could not be loaded. Nothing on this page is guessed.</p>`; });
})();
