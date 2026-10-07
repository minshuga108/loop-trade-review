"use strict";
// First-screen source-status strip + public record strip (reads /api/status/*, cached on the server).
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const hhmm = (iso) => (iso ? iso.slice(11, 19) + " UTC" : "");
  const host = document.createElement("div");
  host.className = "srcstrip"; host.id = "srcstrip"; host.setAttribute("aria-label", "Source status and public record");
  const anchor = document.getElementById("picker") || document.getElementById("strip");
  if (!anchor || !anchor.parentNode) return;
  anchor.parentNode.insertBefore(host, anchor);
  let src = null, rec = null;
  function paint() {
    let h = "";
    if (src && src.sources) {
      h += `<div class="row"><span class="lab">Sources</span>` + src.sources.map((s) =>
        `<span class="sx ${esc(s.state)}" title="${esc(s.detail)}"><i class="dot"></i>${esc(/^Qwen/.test(s.name) ? "Qwen" : s.name)}: <span class="st">${esc(/^Qwen/.test(s.name) ? (s.state === "live" ? "on" : "off") : s.state)}</span>` +
        `<time datetime="${esc(s.checked_at)}">${esc(hhmm(s.checked_at))}</time></span>`).join("") + `</div>`;
    }
    if (rec && rec.decisions_total != null) {
      h += `<div class="row"><span class="lab">Public record</span>` +
        `<span><b>${esc(rec.user_decisions)}</b> <span>user decisions</span></span>` +
        `<span><b>${esc(rec.decisions_total - rec.user_decisions)}</b> <span>sandbox, judge and test decisions</span></span>` +
        `<span><b>${esc(rec.rules_armed)}</b> <span>rules armed</span></span>` +
        `<span><b>${esc(rec.rules_retired)}</b> <span>rules retired</span></span>` +
        `<span><b>${esc(rec.rules_rejected)}</b> <span>rules rejected</span></span>` +
        `<a href="/wrong">What we got wrong</a><a href="/record">Verify the record</a><a href="/proof">Proof</a></div>`;
    }
    host.innerHTML = h;
  }
  const get = (u) => fetch(u).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  Promise.all([get("/api/status/sources"), get("/api/status/record")]).then(([s, r]) => { src = s; rec = r; paint(); });
})();
