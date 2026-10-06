// Bring your own export: paste or choose a Bitget website CSV (or a Hyperliquid fills CSV).
// It is sent to this server, parsed in memory for this session and never stored. Uses globals from home.js.
(function () {
  function panel() {
    let p = document.getElementById("importpanel");
    if (p) return p;
    p = document.createElement("section");
    p.id = "importpanel"; p.className = "card importpanel"; p.hidden = true;
    p.innerHTML = `<h2>Review your own history</h2>
      <p class="tag">Choose or paste the CSV from Bitget (Order Center, Export futures order history, English columns) or a Hyperliquid fills CSV. It is read in memory for this session only, is not stored, and needs no key. Opening fees are not in Bitget's export, so net results overstate by them.</p>
      <div class="askrow"><input type="file" id="importfile" accept=".csv,text/csv,text/plain" aria-label="Choose a CSV file"></div>
      <textarea id="importtext" rows="5" maxlength="2000000" placeholder="…or paste the CSV text here" aria-label="Paste CSV text"></textarea>
      <div class="askrow"><button type="button" id="importgo">Review it</button><span class="tag" id="importmsg" role="status"></span></div>`;
    const pk = document.getElementById("picker");
    pk.parentNode.insertBefore(p, pk.nextSibling);
    document.getElementById("importfile").addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      if (f.size > 2000000) { document.getElementById("importmsg").textContent = "That file is larger than 2 MB."; return; }
      const r = new FileReader();
      r.onload = () => { document.getElementById("importtext").value = String(r.result || ""); };
      r.readAsText(f);
    });
    document.getElementById("importgo").addEventListener("click", async () => {
      const msg = document.getElementById("importmsg");
      const text = document.getElementById("importtext").value;
      if (!text.trim()) { msg.textContent = "Choose a file or paste the CSV first."; return; }
      msg.textContent = "Reading…";
      try {
        const r = await fetch("/api/import", { method: "POST", headers: HDR, body: JSON.stringify({ text }) });
        const j = await r.json();
        if (!r.ok) { msg.textContent = j.detail || "That file could not be read."; return; }
        msg.textContent = `Read ${j.n_trips} round trips. ${j.notes}`;
        panel().hidden = true;
        document.getElementById("importbtn") && document.getElementById("importbtn").setAttribute("aria-expanded", "false");
        boot(j.id);
      } catch (e) { msg.textContent = "The server could not be reached; nothing was stored."; }
    });
    return p;
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#importbtn");
    if (!b) return;
    const p = panel();
    p.hidden = !p.hidden;
    b.setAttribute("aria-expanded", String(!p.hidden));
    if (!p.hidden) p.scrollIntoView({ block: "nearest" });
  });
})();
