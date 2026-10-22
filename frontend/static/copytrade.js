/* Copy trading · Solana (Trading tab). Engine: app/trading/onchain/copytrade.py.
 * Reads /api/copytrade every few seconds while the section is open; text is
 * English and goes through i18n.js like the rest of the page. */
(function () {
  "use strict";
  const root = document.getElementById("copytrade-details");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const POLL_MS = 5000;
  let timer = null;
  let state = null;
  let editing = null;            // address being edited, if any

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const short = (a) => (a ? `${a.slice(0, 4)}…${a.slice(-4)}` : "");
  const usd = (v) => (v == null ? "—" : `$${Math.abs(v) >= 100 ? Math.round(v).toLocaleString("en-US") : Number(v).toFixed(2)}`);
  const signed = (v) => (v == null ? "" : `${v >= 0 ? "+" : "−"}${usd(Math.abs(v))}`);
  const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`; };
  const MODE = { sim: "Simulated", real: "Real", off: "Paused" };

  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Error ${res.status}`);
    return body;
  }

  function msg(text, bad) {
    const el = $("ct-msg");
    el.textContent = text || "";
    el.classList.toggle("is-error", !!bad);
  }

  function sizingLabel() {
    const fixed = document.querySelector('input[name="ct-sizing"]:checked').value === "fixed";
    $("ct-size-label").textContent = fixed ? "Fixed $ per new position" : "% of his trade";
    return fixed;
  }

  function renderStatus() {
    const s = state.server, w = state.wallet;
    const live = s.ws === "connected";
    const parts = [
      `<span class="ct-dot ${live ? "is-on" : s.addresses ? "is-warn" : ""}"></span>`,
      `<span>${live ? "Watching live" : s.addresses ? "Reconnecting" : "Nothing to watch"}</span>`,
      s.source ? `<span class="ct-dim">${s.source === "helius" ? "Helius" : "Public node (slower)"}</span>` : "",
      `<b class="${s.real_enabled ? "ct-up" : "ct-down"}">${s.real_enabled ? "Real execution switched on on the server" : "Real execution switched off on the server"}</b>`,
      w.address ? `<span class="ct-dim">Copy wallet</span> <span class="ct-mono">${short(w.address)}</span> <b>${w.sol == null ? "—" : `${w.sol.toFixed(3)} SOL`}</b>`
        : `<span class="ct-down">No Solana wallet: create it in On-chain wallet below</span>`,
      `<span class="ct-dim">Spent today</span> <b>${usd(state.spent_today)} / ${usd(state.limits.max_day_usd)}</b>`,
    ];
    $("ct-status").innerHTML = parts.filter(Boolean).join(" ");
  }

  function renderFollows() {
    const ul = $("ct-follows");
    if (!state.follows.length) { ul.innerHTML = `<li class="ct-empty">No wallet followed yet.</li>`; return; }
    ul.innerHTML = state.follows.map((f) => `
      <li class="ct-row" data-address="${esc(f.address)}">
        <span class="ct-badge is-${f.mode}">${MODE[f.mode]}</span>
        <span class="ct-grow"><b>${esc(f.label || short(f.address))}</b> <a class="ct-mono ct-dim" href="https://solscan.io/account/${esc(f.address)}" target="_blank" rel="noopener">${short(f.address)}</a></span>
        <span class="ct-dim">${f.copy === "both" ? "Entries and exits" : "Entries only"}</span>
        <span>${f.sizing === "pct" ? `${f.pct}%` : `${usd(f.fixed_usd)} / position`}</span>
        <button type="button" class="section-action-btn" data-act="edit">Edit</button>
        <button type="button" class="section-action-btn" data-act="toggle">${f.mode === "off" ? "Resume" : "Pause"}</button>
        <button type="button" class="section-action-btn" data-act="remove">Remove</button>
      </li>`).join("");
  }

  function renderPositions() {
    const ul = $("ct-positions");
    if (!state.positions.length) { ul.innerHTML = `<li class="ct-empty">No open position.</li>`; return; }
    const names = Object.fromEntries(state.follows.map((f) => [f.address, f.label || short(f.address)]));
    ul.innerHTML = state.positions.map((p) => `
      <li class="ct-row" data-leader="${esc(p.leader)}" data-mint="${esc(p.mint)}">
        <span class="ct-badge is-${p.real ? "real" : "sim"}">${p.real ? "Real" : "Simulated"}</span>
        <span class="ct-grow"><a class="ct-mono" href="https://dexscreener.com/solana/${esc(p.mint)}" target="_blank" rel="noopener">${short(p.mint)}</a> <span class="ct-dim">·</span> ${esc(names[p.leader] || short(p.leader))}</span>
        <span>${usd(p.cost_usd)}</span>
        <span class="ct-dim">${ago(p.opened_at)}</span>
        <button type="button" class="section-action-btn" data-act="close">Sell all</button>
      </li>`).join("");
  }

  function renderLog() {
    const st = state.stats;
    $("ct-stats").textContent = `${st.copied} copied · ${st.skipped} skipped · ${signed(st.realized_usd) || "$0"}${st.median_latency_s != null ? ` · ${st.median_latency_s}s` : ""}`;
    const ul = $("ct-log");
    if (!state.trades.length) { ul.innerHTML = `<li class="ct-empty">Nothing copied yet: the first trade of a followed wallet shows up here.</li>`; return; }
    const names = Object.fromEntries(state.follows.map((f) => [f.address, f.label || short(f.address)]));
    ul.innerHTML = state.trades.map((t) => {
      const ok = t.status === "sim" || t.status === "submitted";
      const tx = t.tx ? ` <a class="ct-dim" href="https://solscan.io/tx/${esc(t.tx)}" target="_blank" rel="noopener">tx</a>` : "";
      return `
      <li class="ct-row ${ok ? "" : "is-muted"}">
        <span class="ct-dim ct-time">${ago(t.t)}</span>
        <span class="ct-side is-${t.side}">${t.side === "buy" ? "BUY" : "SELL"}</span>
        <span class="ct-grow"><a class="ct-mono" href="https://dexscreener.com/solana/${esc(t.mint)}" target="_blank" rel="noopener">${short(t.mint)}</a>
          <span class="ct-dim">${t.manual ? "by hand" : esc(names[t.leader] || t.label || short(t.leader))}</span>
          ${t.leader_usd != null ? `<span class="ct-dim">his trade</span> ${usd(t.leader_usd)}` : ""}
          ${t.usd != null ? `<span class="ct-dim">our copy</span> <b>${usd(t.usd)}</b>` : ""}
          ${t.pnl_usd != null ? `<b class="${t.pnl_usd >= 0 ? "ct-up" : "ct-down"}">${signed(t.pnl_usd)}</b>` : ""}${tx}</span>
        <span class="ct-badge is-${ok ? t.mode : t.status}">${ok ? (t.status === "submitted" ? "Sent" : "Simulated") : t.status === "failed" ? "Failed" : "Skipped"}</span>
        ${t.latency_s != null ? `<span class="ct-dim">${t.latency_s}s</span>` : ""}
        ${ok ? "" : `<span class="ct-reason">${esc(t.reason || "")}</span>`}
      </li>`;
    }).join("");
  }

  function render() {
    renderStatus();
    renderFollows();
    renderPositions();
    renderLog();
    const lim = state.limits;
    for (const [id, k] of [["ct-max-trade", "max_trade_usd"], ["ct-max-day", "max_day_usd"], ["ct-max-open", "max_open"]]) {
      if (document.activeElement !== $(id)) $(id).value = lim[k];
    }
    $("ct-real-ok").checked = state.real_ok;
    $("ct-mode").querySelector('option[value="real"]').disabled = !state.real_ok;
  }

  async function load() {
    try { state = await api("/api/copytrade"); render(); }
    catch (e) { $("ct-status").textContent = e.message; }
  }

  function poll() {
    clearInterval(timer);
    timer = null;
    if (!root.open) return;
    load();
    timer = setInterval(() => { if (document.visibilityState === "visible") load(); }, POLL_MS);
  }

  function fill(f) {
    editing = f.address;
    $("ct-address").value = f.address;
    $("ct-address").readOnly = true;
    $("ct-label").value = f.label || "";
    document.querySelector(`input[name="ct-copy"][value="${f.copy}"]`).checked = true;
    document.querySelector(`input[name="ct-sizing"][value="${f.sizing}"]`).checked = true;
    $("ct-size").value = sizingLabel() ? f.fixed_usd : f.pct;
    $("ct-mode").value = f.mode;
    $("ct-chase").value = f.max_chase_pct;
    $("ct-slip").value = f.slippage_pct;
    $("ct-save").textContent = "Save";
    $("ct-address").scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function reset() {
    editing = null;
    $("ct-form").reset();
    $("ct-address").readOnly = false;
    $("ct-save").textContent = "Follow";
    sizingLabel();
  }

  $("ct-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fixed = sizingLabel();
    const size = Number($("ct-size").value);
    const body = {
      address: $("ct-address").value.trim(), label: $("ct-label").value.trim(),
      mode: $("ct-mode").value,
      copy: document.querySelector('input[name="ct-copy"]:checked').value,
      sizing: fixed ? "fixed" : "pct",
      [fixed ? "fixed_usd" : "pct"]: size,
      max_chase_pct: Number($("ct-chase").value), slippage_pct: Number($("ct-slip").value),
    };
    if (body.mode === "real" && !confirm("Real mode: this wallet's trades will be copied with real money, automatically. Continue?")) return;
    try {
      await api("/api/copytrade/follow", { method: "POST", body: JSON.stringify(body) });
      msg(editing ? "Saved." : "Following.");
      reset();
      load();
    } catch (e) { msg(e.message, true); }
  });

  document.querySelectorAll('input[name="ct-sizing"]').forEach((r) => r.addEventListener("change", () => {
    $("ct-size").value = sizingLabel() ? 50 : 10;
  }));

  $("ct-follows").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const address = btn.closest("li").dataset.address;
    const f = state.follows.find((x) => x.address === address);
    try {
      if (btn.dataset.act === "edit") return fill(f);
      if (btn.dataset.act === "remove") {
        if (!confirm("Stop following this wallet? Open copied positions stay, and can be sold from the list.")) return;
        await api(`/api/copytrade/follow/${encodeURIComponent(address)}`, { method: "DELETE" });
      } else {
        await api("/api/copytrade/follow", { method: "POST", body: JSON.stringify({ address, mode: f.mode === "off" ? "sim" : "off" }) });
      }
      load();
    } catch (e) { msg(e.message, true); }
  });

  $("ct-positions").addEventListener("click", async (ev) => {
    const btn = ev.target.closest('button[data-act="close"]');
    if (!btn) return;
    const li = btn.closest("li");
    if (!confirm("Sell all of this copied position now?")) return;
    btn.disabled = true;
    try {
      const row = await api("/api/copytrade/close", { method: "POST", body: JSON.stringify({ leader: li.dataset.leader, mint: li.dataset.mint }) });
      msg(row.status === "sim" || row.status === "submitted" ? "Sold." : row.reason || "Not sold.", !(row.status === "sim" || row.status === "submitted"));
      load();
    } catch (e) { msg(e.message, true); btn.disabled = false; }
  });

  $("ct-limits-save").addEventListener("click", async () => {
    try {
      await api("/api/copytrade/limits", { method: "POST", body: JSON.stringify({
        max_trade_usd: Number($("ct-max-trade").value), max_day_usd: Number($("ct-max-day").value), max_open: Number($("ct-max-open").value) }) });
      msg("Limits saved.");
      load();
    } catch (e) { msg(e.message, true); }
  });

  $("ct-real-ok").addEventListener("change", async (ev) => {
    const accept = ev.target.checked;
    if (accept && !confirm("Allow Real mode on this account? Copies will spend the Solana wallet's money without asking each time.")) { ev.target.checked = false; return; }
    try { await api("/api/copytrade/real", { method: "POST", body: JSON.stringify({ accept }) }); load(); }
    catch (e) { msg(e.message, true); }
  });

  root.addEventListener("toggle", poll);
  sizingLabel();
  if (root.open) poll();
})();
