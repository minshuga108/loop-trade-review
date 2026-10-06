"use strict";
// Renders /wrong, /proof and the Skills panel (external script: the CSP allows no new inline code).
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x) => (x == null ? "–" : (100 * x).toFixed(x > 0 && x < 0.1 ? 1 : 0) + "%");
  const ci = (c) => (c ? ` <small>[${pct(c[0])}, ${pct(c[1])}]</small>` : "");
  const rate = (r) => (r ? `${pct(r.rate)}${ci(r.ci)} <small>${esc(r.k)}/${esc(r.n)}</small>` : "–");
  const table = (head, rows) => `<div class="scroll"><table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  const card = (title, body) => `<section class="card"><h2>${title}</h2>${body}</section>`;
  const get = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  const fail = (id) => { const m = $(id); if (m) m.innerHTML = `<p class="err">The numbers could not be loaded. Nothing on this page is guessed.</p>`; };

  (function theme() {
    const root = document.documentElement, b = $("#themebtn");
    const isDark = () => root.dataset.theme === "dark" || (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    const apply = (v) => { if (v) root.dataset.theme = v; if (b) b.textContent = isDark() ? "◐ Light" : "◑ Dark"; };
    let t = null; try { t = localStorage.getItem("theme"); } catch (e) {}
    apply(t);
    if (b) b.addEventListener("click", () => { const v = isDark() ? "light" : "dark"; try { localStorage.setItem("theme", v); } catch (e) {} apply(v); });
  })();

  const SCEN = { null: "No leak at all", costless_habit: "A habit that costs nothing extra", costly_leak: "A real costly leak" };
  const TRUTH = { null: "nothing there", leak: "real leak", decay: "leak that faded" };
  const lab = (s) => `<span class="lab2 ${s === "author-blind" ? "blind" : "tuned"}">${esc(s)}</span>`;

  function renderWrong(d) {
    let h = "";
    h += card("Rules the court rejected or retired (public record)", d.record_events.length
      ? table(["#", "When", "Trader", "Rule", "What happened", "Reason"], d.record_events.map((e) =>
        `<tr><td class="n">${esc(e.seq)}</td><td class="n">${esc((e.at || "").slice(0, 16))}</td><td>${esc(e.trader)}</td><td>${esc(e.rule_id)}</td><td>${esc(e.event)}</td><td><small>${esc(e.reason)}</small></td></tr>`))
      : `<p class="tag">No rejected, underpowered or retired rule has been written to this server's record yet. The cohort below is the larger sample.</p>`);
    const c = d.cohort_rejections;
    if (c && c.per_rule) {
      h += card("Cohort: every rule the court tried on 60 wallets", table(["Rule size (x median)", "Rejected", "Underpowered", "Accepted"],
        Object.entries(c.per_rule).map(([k, v]) => `<tr><td class="n">${esc(k)}</td><td class="n">${esc(v.REJECTED)}</td><td class="n">${esc(v.UNDERPOWERED)}</td><td class="n">${esc(v.ACCEPTED)}</td></tr>`)) +
        `<p class="tag">${esc(c.trials)} trials, ${esc(c.wallets_with_any_accepted)} wallet(s) with any accepted rule, per-rule bar ${esc(c.alpha_per_rule)}. <a href="/proof">Proof</a></p>`);
    }
    h += card("Planted-suite misses (simulated traders)", `<p class="honest">Every row where the court accepted something that was not there, did not accept a real leak, or did not retire a faded one. The planted traders are simulated; nothing here is a real person.</p>` +
      table(["Cell", "Rule", "What", "Count", "Rate"], d.planted_misses.map((m) =>
        `<tr><td>${esc(m.cell)}</td><td>${esc(m.rule || "")}</td><td>${esc(m.what)}</td><td class="n">${esc(m.k)}/${esc(m.n)}</td><td class="n">${pct(m.rate)}${ci(m.ci)}</td></tr>`)));
    if (d.court_above_bar.length) {
      h += card("Court cells above its own bar", `<p class="tag">The court's per-rule bar is ${pct(d.court_above_bar[0].bar)}. These measured wrong-acceptance rates are above it (100 simulated traders per cell, so noisy).</p>` +
        table(["Cell", "Wrong acceptance"], d.court_above_bar.map((a) => `<tr><td>${esc(a.cell)}</td><td class="n">${pct(a.rate)}${ci(a.ci)}</td></tr>`)));
    }
    h += card("Chat router misses", d.router.length ? d.router.map((s) =>
      `<h3 style="font:600 15px var(--serif);margin:12px 0 4px">${esc(s.set)} ${lab(s.label)}</h3>` +
      `<p class="tag">${esc(s.correct_now)}/${esc(s.n)} now.${s.first_score ? ` First scoring: ${esc(s.first_score.k)}/${esc(s.first_score.n)} (${esc(s.first_score.file)}).` : ""} ${esc(s.why)}</p>` +
      (s.misses.length ? table(["Question", "Should be", "Routed to"], s.misses.map((m) => `<tr><td>${esc(m.text)}</td><td>${esc(m.gold)}</td><td>${esc(m.got)}</td></tr>`)) : `<p class="tag">No misses now (the router was tuned on this set, so this is not a performance estimate).</p>`)).join("")
      : `<p class="tag">proof_results.json has not been generated (run scripts/proof_baseline.py).</p>`);
    $("#main").innerHTML = h;
  }

  function renderProof(d) {
    let h = "";
    h += card("The court: measured wrong acceptance and power", `<p class="tag">${esc(d.court.sims_per_cell)} simulated traders per cell, per-rule bar ${pct(d.court.threshold_per_rule)}. Source: ${esc(d.court.file)}.</p>` +
      table(["Situation", "Trades", "Accepted", "Not enough trades to judge"], d.court.cells.map((c) =>
        `<tr><td>${SCEN[c.scenario] || esc(c.scenario)}</td><td class="n">${esc(c.trips)}</td><td class="n">${pct(c.accepted)}${ci(c.accepted_ci)}</td><td class="n">${pct(c.underpowered)}</td></tr>`)) +
      `<p class="honest">For the first two situations "Accepted" is the wrong-acceptance rate (lower is better); for the third it is power (higher is better). Power is low on short histories.</p>`);
    if (d.cohort) {
      const cc = d.cohort.court;
      h += card("The 60-wallet cohort", `<p class="tag">${esc(d.cohort.n_wallets)} public wallets. ${esc(d.cohort.provenance)}</p>` + table(["Rule size (x median)", "Rejected", "Underpowered", "Accepted"],
        Object.entries(cc.per_rule).map(([k, v]) => `<tr><td class="n">${esc(k)}</td><td class="n">${esc(v.REJECTED)}</td><td class="n">${esc(v.UNDERPOWERED)}</td><td class="n">${esc(v.ACCEPTED)}</td></tr>`)) +
        `<p class="tag">${esc(cc.wallets_with_any_accepted)} wallet(s) with any accepted rule; about ${esc(cc.expected_acceptances_if_no_leak_at_most)} expected by chance at most if no wallet leaked.</p>`);
    }
    if (d.router) {
      h += card("Chat router question sets", `<p class="honest">A set is blind only on its first scoring. Once the router was changed using a set's misses it is labelled tuned and its score is not an estimate for new questions.</p>` +
        table(["Set", "Label", "Questions", "First scoring", "Now"], d.router.sets.map((s) => `<tr><td>${esc(s.set)}<small>${esc(s.why)}</small></td><td>${lab(s.label)}</td><td class="n">${esc(s.n)}</td>` +
          `<td class="n">${s.first_score ? `${esc(s.first_score.k)}/${esc(s.first_score.n)} ${ci(s.first_score.ci)}` : "–"}</td><td class="n">${esc(s.correct_now)}/${esc(s.n)}</td></tr>`)) + `<p class="tag"><a href="/wrong">Every miss</a></p>`);
    }
    if (d.baseline) {
      h += card("Naive in-sample check against the court (planted suite)", `<p class="tag">${esc(d.baseline.what)}</p>` +
        table(["Cell", "Truth", "Naive: would have saved money", "Naive: p below 0.05", "Court accepts"], d.baseline.cells.map((c) =>
          `<tr><td>${esc(c.cell)}</td><td>${esc(TRUTH[c.truth] || c.truth)}</td><td class="n">${rate(c.naive_saves_money)}</td><td class="n">${rate(c.naive_p_below_0_05)}</td><td class="n">${rate(c.court_cap_accepts)}</td></tr>`)) +
        `<p class="honest">Read the "nothing there" rows as wrong acceptance and the "real leak" rows as power. On these simulated traders a plain p-value test finds a real leak more often than the court does, so the court pays for its caution in power; the check that only asks whether the cap would have saved money accepts about half of everything. Nobody else's method is run or named here.</p>`);
    } else {
      h += card("Naive in-sample check against the court", `<p class="tag">proof_results.json has not been generated (run scripts/proof_baseline.py).</p>`);
    }
    $("#main").innerHTML = h;
  }

  function renderSkills(d) {
    const sec = $("#skills"); if (!sec) return;
    const rows = d.calls.map((r) => `<tr><td>${esc(r.source)}<small>${esc(r.origin)}</small></td><td>${esc(r.operation)}</td><td class="n">${esc(r.last_status)}</td>` +
      `<td class="n">${r.last_latency_ms == null ? "–" : esc(r.last_latency_ms) + " ms"}<small>median ${r.median_latency_ms == null ? "–" : esc(r.median_latency_ms) + " ms"}</small></td>` +
      `<td class="n">${esc(r.ok)}/${esc(r.calls)}</td><td><span class="badge ${r.freshness === "live" ? "b-ok" : "b-warn"}">${esc(r.freshness)}</span><small>${esc((r.last_at || "").replace("T", " ").slice(0, 19))}</small></td></tr>`);
    const t = d.dry_run_ticket;
    sec.innerHTML = `<h2>Skills: what each public Bitget call returned</h2>
      <p class="tag">${esc(d.note)}</p>
      <div class="scroll"><table><thead><tr><th>Source</th><th>Call</th><th>Status</th><th>Timing</th><th>Answered</th><th>State</th></tr></thead><tbody>${rows.join("") || `<tr><td colspan="6">No calls logged yet.</td></tr>`}</tbody></table></div>
      <h2 style="margin-top:14px">Order-ticket preview</h2><p class="honest">${esc(t.what)}</p><pre>${esc(JSON.stringify(t.example_payload, null, 2))}</pre>
      <p class="tag">${t.not_included.map(esc).join(" · ")}</p>`;
  }

  const page = document.body.dataset.page;
  if (page === "wrong") get("/api/status/wrong").then(renderWrong).catch(() => fail("#main"));
  if (page === "proof") get("/api/status/proof").then(renderProof).catch(() => fail("#main"));
  if ($("#skills")) get("/api/status/skills").then(renderSkills).catch(() => { $("#skills").innerHTML = `<p class="err">Could not load the skills panel.</p>`; });
})();
