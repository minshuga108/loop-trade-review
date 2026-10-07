// Per-trade detail page. Every number comes from /api/trip/{trader}/{index}; this file only formats and draws.
(function () {
  const m = location.pathname.match(/^\/trade\/([^/]+)\/(\d+)$/);
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let lang = "en"; try { lang = localStorage.getItem("lang") === "zh" ? "zh" : "en"; } catch (e) {}
  try { const th = localStorage.getItem("theme"); if (th) document.documentElement.dataset.theme = th; } catch (e) {}
  const T = {
    en: { back: "Back to the review", prev: "< previous trade", next: "next trade >", title: "Trade", fills: "Fills", chart: "Price and fills", find: "Findings this trade contributes to",
      net: "Net result (USD)", fees: "Fees paid (USD)", hold: "Held", size: "First order (USD)", side: "Side", long: "long", short: "short", opened: "Opened (UTC)", closed: "Closed (UTC)",
      time: "Time (UTC)", op: "opens", cl: "closes", price: "Price", qty: "Size", fee: "Fee", real: "Realised", none: "This trade belongs to none of the four tested habit groups.",
      after_loss: ["Size after a loss", "It opened after a losing trade."], losing: ["Hold time: losing group", "It lost money, so it is in the losing group."],
      busiest_day: ["Overtrading clusters", "It opened on one of the busiest days."], reentry: ["Revenge re-entry: re-entries", "It re-entered shortly after a close."],
      revenge: ["Revenge re-entry: labelled sub-group", "It re-entered after a loss, inside the window."], open: "Back to the findings", lang: "中文",
      err: "Could not load this trade.", cap: "Price over time: line = stored candle closes, dots = this trade's fills (filled = opens, ring = closes)." },
    zh: { back: "返回复盘", prev: "< 上一笔", next: "下一笔 >", title: "交易", fills: "成交", chart: "价格与成交", find: "这笔交易参与的发现",
      net: "净结果（USD）", fees: "已付手续费（USD）", hold: "持有时间", size: "首单金额（USD）", side: "方向", long: "做多", short: "做空", opened: "开仓（UTC）", closed: "平仓（UTC）",
      time: "时间（UTC）", op: "开仓", cl: "平仓", price: "价格", qty: "数量", fee: "手续费", real: "已实现", none: "这笔交易不属于四个被检验习惯中的任何一组。",
      after_loss: ["亏损后的仓位大小", "它是在一笔亏损之后开仓的。"], losing: ["持有时间：亏损组", "这笔交易亏损，所以属于亏损组。"],
      busiest_day: ["过度交易集中日", "它开仓于最忙的日子之一。"], reentry: ["报复性再进场：再进场", "它在平仓后不久再次进场。"],
      revenge: ["报复性再进场：标记子组", "它在亏损之后的窗口内再次进场。"], open: "回到发现列表", lang: "EN",
      err: "无法加载这笔交易。", cap: "价格随时间：折线 = 已存蜡烛收盘价，圆点 = 这笔交易的成交（实心 = 开仓，空心 = 平仓）。" },
  };
  // server notes are English; the 中文 view maps the fixed sentences (numbers and symbols are carried through)
  const noteZh = (s) => {
    if (lang !== "zh" || !s) return s || "";
    let m;
    if (s.startsWith("This trader has no fill records (simulated")) return "这位交易者没有成交记录（只有模拟的完整交易），所以无法逐笔回放。";
    if (s.startsWith("This trader has no fill records: the real journal")) return "这位交易者没有成交记录：真实日志给出的是每个已平仓位（进场、离场、结果），而不是逐笔成交，所以无法逐笔回放。";
    if ((m = s.match(/^No candles for (.*) are stored offline/))) return "离线没有存储 " + m[1] + " 的K线，所以不画价格路径，也不计算最大不利/有利波动。不联网获取，也不猜测。";
    if (s.startsWith("MAE and MFE are approximate")) return "最大不利/有利波动是近似值：取自K线的最高价和最低价，可能包含交易时间窗口之外的价格。";
    return s;
  };
  const nf = (x, d = 2) => (x == null || x !== x ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d }));
  const sg = (x) => (x == null ? "–" : (x >= 0 ? "+" : "-") + nf(Math.abs(x)));
  const ut = (ms) => (ms == null ? "–" : new Date(ms).toISOString().slice(0, 16).replace("T", " "));
  const hold = (ms) => (ms < 3600e3 ? Math.max(1, Math.round(ms / 60e3)) + " min" : ms < 48 * 3600e3 ? (ms / 3600e3).toFixed(1) + " h" : (ms / 86400e3).toFixed(1) + " d");

  function chart(j, L) {
    const W = 900, H = 240, pl = 64, pr = 14, pt = 12, pb = 30;
    const candle = (j.candles ? j.candles.rows.map((c) => [c[0], c[4]]) : []);
    const dots = j.fills.map((f) => [f.t_ms, f.price, f.is_open]);
    const pts = candle.concat(dots.map((d) => [d[0], d[1]]));
    if (pts.length < 1) return `<p class="tag">${esc(noteZh(j.candles_note))}</p>`;
    let x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0])), y0 = Math.min(...pts.map((p) => p[1])), y1 = Math.max(...pts.map((p) => p[1]));
    if (x1 === x0) { x0 -= 6e4; x1 += 6e4; }
    if (y1 === y0) { y0 *= 0.999; y1 *= 1.001; }
    const X = (v) => pl + (v - x0) / (x1 - x0) * (W - pl - pr), Y = (v) => H - pb - (v - y0) / (y1 - y0) * (H - pt - pb);
    const line = candle.length > 1 ? `<polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${candle.map((p) => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ")}"/>` : "";
    const ds = dots.map((d) => `<circle cx="${X(d[0]).toFixed(1)}" cy="${Y(d[1]).toFixed(1)}" r="6" fill="${d[2] ? "var(--ink)" : "var(--surface)"}" stroke="var(--ink)" stroke-width="2"><title>${d[2] ? L.op : L.cl} ${nf(d[1], 6)} ${ut(d[0])}</title></circle>`).join("");
    const ticks = [y0, (y0 + y1) / 2, y1].map((v) => `<text x="${pl - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${nf(v, 4)}</text><line x1="${pl}" x2="${W - pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/>`).join("");
    const xt = `<text x="${pl}" y="${H - 8}" font-size="11" fill="var(--muted)">${ut(x0)}</text><text x="${W - pr}" y="${H - 8}" text-anchor="end" font-size="11" fill="var(--muted)">${ut(x1)}</text>`;
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(L.cap)}">${ticks}${xt}${line}${ds}</svg><p class="tag">${esc(L.cap)}</p><p class="tag">${esc(noteZh(j.candles_note))}</p>` +
      (j.mae_frac != null ? `<p class="tag">MAE ${(100 * j.mae_frac).toFixed(2)}% · MFE ${(100 * j.mfe_frac).toFixed(2)}%</p>` : "");
  }

  function render(j, tid, idx) {
    const L = T[lang], t = j.trip;
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    $("#back").textContent = L.back; $("#lang").textContent = L.lang;
    $("#prev").textContent = idx > 0 ? L.prev : ""; $("#prev").href = idx > 0 ? `/trade/${tid}/${idx - 1}` : "#";
    $("#next").textContent = L.next; $("#next").href = `/trade/${tid}/${idx + 1}`;
    document.title = `${L.title} ${t.symbol} #${idx} | Loop`;
    const fees = j.fills.length ? j.fills.reduce((a, f) => a + (Number(f.fee) || 0), 0) : null;
    const tags = t.tags.filter((g) => T.en[g]);
    const fnd = tags.length ? "<ul class=\"find\">" + tags.map((g) => `<li><b>${esc(L[g][0])}</b><br><span class="tag">${esc(L[g][1])}</span><br><a href="/#cards">${esc(L.open)}</a></li>`).join("") + "</ul>" : `<p class="tag">${esc(L.none)}</p>`;
    const rows = j.fills.map((f) => `<tr><td class="n">${ut(f.t_ms)}</td><td>${esc(f.side)}</td><td>${f.is_open ? L.op : L.cl}</td><td class="n">${nf(f.price, 6)}</td><td class="n">${nf(f.size, 4)}</td><td class="n">${nf(f.notional)}</td><td class="n">${nf(f.fee, 4)}</td><td class="n ${f.realized_pnl > 0 ? "pos" : f.realized_pnl < 0 ? "neg" : ""}">${sg(f.realized_pnl)}</td></tr>`).join("");
    $("#main").innerHTML = `<h1>${esc(L.title)} ${esc(t.symbol)} <span class="tag">#${idx} · ${esc(lang === "zh" ? ({ REAL_PLATFORM_PUBLIC: "真实公开数据", SIM_PLANTED: "模拟数据", REAL_OWN: "你自己的数据" }[t.provenance] || t.provenance) : t.provenance)}</span></h1>
      <section class="card" aria-label="facts"><div class="facts">
        <div class="fact"><span>${L.net}</span><b class="${t.net_pnl > 0 ? "pos" : t.net_pnl < 0 ? "neg" : ""}">${sg(t.net_pnl)}</b></div>
        <div class="fact"><span>${L.fees}</span><b>${fees == null ? "–" : nf(fees, 4)}</b></div>
        <div class="fact"><span>${L.hold}</span><b>${hold(t.hold_ms)}</b></div>
        <div class="fact"><span>${L.size}</span><b>${nf(t.first_order_notional, 0)}</b></div>
        <div class="fact"><span>${L.side}</span><b>${t.side === "buy" ? L.long : L.short}</b></div>
        <div class="fact"><span>${L.opened}</span><b style="font-size:14px">${ut(t.t_open_ms)}</b></div>
        <div class="fact"><span>${L.closed}</span><b style="font-size:14px">${ut(t.t_close_ms)}</b></div></div></section>
      <section class="card"><h2>${L.chart}</h2>${chart(j, L)}</section>
      <section class="card"><h2>${L.find}</h2>${fnd}</section>
      <section class="card scroll"><h2>${L.fills}</h2>${j.fills.length ? `<table><thead><tr><th scope="col">${L.time}</th><th scope="col">${L.side}</th><th scope="col"></th><th class="n" scope="col">${L.price}</th><th class="n" scope="col">${L.qty}</th><th class="n" scope="col">USD</th><th class="n" scope="col">${L.fee}</th><th class="n" scope="col">${L.real}</th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="tag">${esc(noteZh(j.fills_note))}</p>`}</section>`;
  }

  async function load() {
    if (!m) { $("#main").textContent = T[lang].err; return; }
    const tid = decodeURIComponent(m[1]), idx = +m[2];
    try {
      const r = await fetch(`/api/trip/${encodeURIComponent(tid)}/${idx}`);
      const j = await r.json();
      if (!r.ok) { $("#main").innerHTML = `<p class="tag">${esc(j.detail || T[lang].err)}</p>`; return; }
      window.__trade = { j, tid, idx }; render(j, tid, idx);
    } catch (e) { $("#main").innerHTML = `<p class="tag">${esc(T[lang].err)}</p>`; }
  }
  $("#lang").addEventListener("click", () => {
    lang = lang === "zh" ? "en" : "zh"; try { localStorage.setItem("lang", lang); } catch (e) {}
    if (window.__trade) render(window.__trade.j, window.__trade.tid, window.__trade.idx);
  });
  load();
})();
