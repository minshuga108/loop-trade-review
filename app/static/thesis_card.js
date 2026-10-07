// "Your trading thesis" card for the first screen. Fetches /api/thesis/<id>; every sentence is built on the server from engine facts.
// Both languages are rendered; home.css shows the one matching <html lang>. Loaded after home.js; home.js calls loadThesis(id).
(function () {
  const st = document.createElement("style");
  st.textContent = ".hero>.thesis{grid-column:1/-1;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 20px}" +
    ".thesis ol{margin:6px 0;padding-left:20px}.thesis li{margin:4px 0}.thesis .tbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}" +
    ".thesis code{font-size:12px;word-break:break-all}.thesis .tdiff{color:var(--warn)}";
  document.head.appendChild(st);
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const both = (en, zh) => `<span data-l="en">${E(en)}</span><span data-l="zh">${E(zh)}</span>`;
  let seq = 0;
  async function post(url, h) { const r = await fetch(url, { method: "POST", headers: h }); return r.json(); }
  function draw(host, t, id, extra) {
    const lines = t.text.en.map((en, i) => `<li>${both(en, t.text.zh[i])}</li>`).join("");
    const fr = t.frozen.length ? t.frozen.map((f) => `v${f.version} <code>${E(f.hash.slice(0, 12))}</code>`).join(" · ") : "";
    const df = t.diff.map((d) => `<li class="tdiff">${both(d.en, d.zh)}</li>`).join("");
    host.innerHTML = `<p class="eyebrow"><span class="no">+</span><span>${both("Your trading thesis", "你的交易论点")}</span><span class="fill"></span><span>${both("assembled only from engine facts", "只由引擎事实组成")}</span></p>
      <ol>${lines}</ol>${df ? "<ul>" + df + "</ul>" : ""}
      <p class="tag">${both("Thesis hash", "论点哈希")} <code>${E(t.hash.slice(0, 16))}</code> · ${E(t.date)}${fr ? " · " + both("frozen", "已冻结") + " " + fr : ""}</p>
      <div class="tbar"><button type="button" class="btn" id="th-freeze">${both("Freeze this thesis", "冻结这个论点")}</button>
        <button type="button" class="btn link" id="th-score">${both("Score thesis vs. new trades", "用新交易给论点打分")}</button>
        <a href="/thesis/${encodeURIComponent(id)}">${both("Open read-only page", "打开只读页面")}</a></div>
      <p class="tag" id="th-msg" aria-live="polite">${extra || ""}</p>`;
    const msg = host.querySelector("#th-msg");
    host.querySelector("#th-freeze").onclick = async () => {
      const j = await post(`/api/thesis/${encodeURIComponent(id)}/freeze`, HDR);
      if (j.record_error) { msg.innerHTML = E(j.record_error); return; }
      draw(host, j, id, j.already_frozen ? both("Already frozen: nothing changed since the last freeze.", "已冻结：自上次冻结以来没有变化。") :
        both(`Frozen as v${j.frozen_now.version}, written to the public record (entry ${j.frozen_now.seq}). Nothing was armed.`, `已冻结为 v${j.frozen_now.version}，写入公开记录（第 ${j.frozen_now.seq} 条）。没有启用任何规则。`));
    };
    host.querySelector("#th-score").onclick = async () => {
      msg.textContent = "…";
      const r = await fetch(`/api/thesis/${encodeURIComponent(id)}/score`, { headers: HDR });
      const j = await r.json();
      msg.innerHTML = j.summary ? both(j.summary.en, j.summary.zh) : E(j.detail || "error");
    };
  }
  window.loadThesis = async function (id) {
    const host = document.getElementById("thesis-card"); if (!host || !id) return;
    const mine = ++seq;
    try {
      const r = await fetch(`/api/thesis/${encodeURIComponent(id)}`, { headers: HDR });
      if (!r.ok || mine !== seq) return;
      draw(host, await r.json(), id);
    } catch (e) { host.innerHTML = ""; }
  };
})();
