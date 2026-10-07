// "Tested on real wallets" card: fetches /api/cohort_card (numbers read from cohort_results.json by the server). Not rendered if unavailable.
(function () {
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const both = (en, zh) => `<span data-l="en">${E(en)}</span><span data-l="zh">${E(zh)}</span>`;
  const n = (x) => Number(x).toLocaleString("en-US");
  async function init() {
    const main = document.getElementById("main"); if (!main) return;
    try {
      const r = await fetch("/api/cohort_card"); if (!r.ok) return;
      const c = await r.json();
      const sec = document.createElement("section");
      sec.className = "cohortcard"; sec.id = "cohort-card"; sec.setAttribute("aria-label", "Tested on real wallets");
      sec.innerHTML = `<p class="eyebrow"><span class="no">+</span><span>${both("Tested on real wallets", "在真实钱包上测试过")}</span></p>
        <ul>
        <li>${both(`${c.n_wallets} real public wallets, ${n(c.n_round_trips)} round trips, each tested only against its own history.`, `${c.n_wallets} 个真实公开钱包，${n(c.n_round_trips)} 笔完整交易，每个钱包只和自己的历史比较。`)}</li>
        <li>${both(`The "bigger bets after a loss" habit shows in ${c.habit_after_correction} of ${c.tested} testable wallets after correcting for testing them all at once (BH q ${c.fdr_q}).`, `在校正了同时检验所有钱包之后，“亏损后加大仓位”的习惯出现在 ${c.tested} 个可检验钱包中的 ${c.habit_after_correction} 个（BH q ${c.fdr_q}）。`)}</li>
        <li>${both(`Pooled across traders it looks strong (p = ${c.pooled_p}); within each trader it disappears (p = ${c.within_trader_p}).`, `把所有交易者混在一起看似很强（p = ${c.pooled_p}）；只在每个交易者自己内部比较时消失（p = ${c.within_trader_p}）。`)}</li>
        </ul>
        <p class="tag">${both("The cohort is public Hyperliquid wallets, not Bitget users.", "样本是 Hyperliquid 的公开钱包，不是 Bitget 用户。")} <a href="${E(c.proof)}">${both("See the proof page", "查看证明页面")}</a></p>`;
      main.parentNode.insertBefore(sec, main);
    } catch (e) { /* card stays absent */ }
  }
  init();
})();
