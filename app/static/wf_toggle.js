// In-sample vs walk-forward view for one proposed rule, inside the rulebook card. Numbers come from /api/rulebook/<id>/walkforward (engine functions).
(function () {
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const both = (en, zh) => `<span data-l="en">${E(en)}</span><span data-l="zh">${E(zh)}</span>`;
  const usd = (x) => (x < 0 ? "-$" : "+$") + Math.abs(Math.round(x)).toLocaleString("en-US");
  const pf = (p) => (p == null ? "n/a" : p.toFixed(3));
  async function show(box) {
    const out = box.querySelector("#wfout"); out.textContent = "…";
    const m = document.getElementById("rbm").value;
    try {
      const r = await fetch(`/api/rulebook/${encodeURIComponent(current)}/walkforward?multiple=${encodeURIComponent(m)}`, { headers: HDR });
      const j = await r.json(); if (!r.ok) { out.textContent = String(j.detail || "error"); return; }
      const a = j.in_sample, w = j.walk_forward;
      const row = (lab, x, extra) => `<tr><td>${lab}</td><td class="n">${usd(x.effect)}</td><td class="n">${x.n_affected} / ${x.n_trips}</td><td class="n">${pf(x.p)}</td><td class="n">${x.alpha}</td><td>${extra}</td></tr>`;
      out.innerHTML = `<table><caption class="vh">In-sample versus walk-forward</caption><thead><tr><th>${both("View", "视角")}</th><th>${both("Effect", "效果")}</th><th>${both("Trades touched", "涉及的交易")}</th><th>p</th><th>${both("Bar", "门槛")}</th><th>${both("Result", "结果")}</th></tr></thead><tbody>` +
        row(both("In-sample: all trades, including those that surfaced the habit (labelled optimistic)", "样本内：全部交易，包括发现习惯的那些（标注为偏乐观）"), a, E(a.verdict)) +
        row(both(`Walk-forward: unseen trades only, ${j.trials} rules counted`, `滚动前向：只用没见过的交易，已计入 ${j.trials} 条规则`), w, E(w.verdict)) + `</tbody></table>` +
        `<p class="tag">${j.in_sample_flatters ? both("In-sample flatters this rule: it looks better on the trades that surfaced the habit than on unseen ones.", "样本内高估了这条规则：在发现习惯的交易上比在没见过的交易上好看。") : both("Here in-sample does not look better than the unseen result.", "这里样本内并不比未见交易的结果更好。")}</p>`;
    } catch (e) { out.textContent = "Could not reach the server."; }
  }
  function mount() {
    const msg = document.getElementById("rbmsg"), card = document.getElementById("rbcard");
    if (!msg || !card || card.querySelector("#wfbox")) return;
    const box = document.createElement("div"); box.id = "wfbox"; box.className = "tag"; box.style.margin = "8px 0";
    box.innerHTML = `<button type="button" class="btn link" id="wfbtn">${both("Compare in-sample vs walk-forward for the selected rule", "对比所选规则的样本内与滚动前向结果")}</button><div id="wfout" aria-live="polite"></div>`;
    msg.parentNode.insertAdjacentElement("afterend", box);
    box.querySelector("#wfbtn").onclick = () => show(box);
  }
  new MutationObserver(mount).observe(document.body, { childList: true, subtree: true });
  mount();
})();
