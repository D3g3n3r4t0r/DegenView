/* Copy trading · Solana + EVM (Trading tab). Engines: app/trading/onchain/copytrade.py
 * and copytrade_evm.py (EVM wallets: one 0x address, six networks, simulated).
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
  const isEvm = (a) => /^0x[0-9a-fA-F]{40}$/.test(String(a || "").trim());
  const chainOf = (id) => (state && state.evm ? state.evm.chains.find((c) => c.id === id) : null) || null;
  // Where a token and a transaction can be looked at: DexScreener for tokens on
  // every network, the network's own explorer for transactions where we know it.
  const tokenUrl = (chain, token) => `https://dexscreener.com/${chain ? (chainOf(chain)?.dex || chain) : "solana"}/${encodeURIComponent(token)}`;
  const txUrl = (chain, tx) => (!chain ? `https://solscan.io/tx/${encodeURIComponent(tx)}` : chainOf(chain)?.tx ? `${chainOf(chain).tx}${encodeURIComponent(tx)}` : null);
  const walletUrl = (a) => (isEvm(a) ? `https://debank.com/profile/${encodeURIComponent(a)}` : `https://solscan.io/account/${encodeURIComponent(a)}`);
  const chainChips = (ids) => (ids || []).map((id) => `<span class="ct-chip">${esc(chainOf(id)?.label || id)}</span>`).join("");

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
      w.address && !w.enabled && state.follows.some((f) => f.mode === "real") ? `<b class="ct-down">Wallet switched off: Real copies are skipped. Turn on "Wallet active" in On-chain wallet → Limits</b>` : "",
      `<span class="ct-dim">Spent today</span> <b>${usd(state.spent_today)} / ${usd(state.limits.max_day_usd)}</b>`,
    ];
    $("ct-status").innerHTML = parts.filter(Boolean).join(" ");
  }

  function renderEvm() {
    const e = state.evm, box = $("ct-evm");
    if (!e) { box.innerHTML = ""; return; }
    const rows = e.chains.map((c) => `
      <li class="ct-evm-row">
        <span class="ct-grow"><b>${esc(c.label)}</b></span>
        <span class="ct-mono">${c.balance == null ? "—" : `${Number(c.balance).toFixed(c.balance >= 1 ? 3 : 5)} ${esc(c.native)}`}</span>
        <span class="ct-badge ${c.copy ? "is-sim" : "is-off"}" title="${c.copy ? "Its trades are copied" : "No trusted quote source on this network yet: trades are seen and logged, not copied"}">${c.copy ? "Copied" : "Seen only"}</span>
        ${c.state === "error" ? `<span class="ct-down" title="${esc(c.error || "")}">network not answering</span>` : ""}
      </li>`).join("");
    box.innerHTML = `
      <div class="section-title-row"><span class="section-eyebrow">EVM wallet</span></div>
      ${e.address
        ? `<p class="ct-evm-addr"><span class="ct-mono" title="${esc(e.address)}">${esc(e.address)}</span>
             <button type="button" class="section-action-btn" id="ct-evm-copy">Copy</button></p>
           <p class="panel-hint">One address on every network below, like MetaMask: it is your Robinhood Chain wallet. Each network pays its fees in its own coin, so a network needs some of that coin before copies can run there. To open it in MetaMask: On-chain wallet below → Robinhood Chain → reveal the key; the same key opens all these networks.</p>`
        : `<p class="panel-hint ct-down">No EVM wallet yet: create the Robinhood Chain wallet in On-chain wallet below. It becomes your address on all these networks.</p>`}
      <ul class="ct-list ct-evm-list">${rows}</ul>`;
    $("ct-evm-copy")?.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(e.address); msg("EVM address copied."); } catch { msg(e.address); }
    });
  }
  function renderChainPicker() {
    const box = $("ct-chain-boxes");
    if (!state.evm || box.dataset.ready) return;
    box.innerHTML = state.evm.chains.map((c) => `<label><input type="checkbox" name="ct-chain" value="${esc(c.id)}" checked /> ${esc(c.label)}${c.copy ? "" : ` <span class="ct-dim">(seen only)</span>`}</label>`).join("");
    box.dataset.ready = "1";
  }
  function addressKind() {
    const evm = isEvm($("ct-address").value);
    $("ct-chains").hidden = !evm;
    const real = $("ct-mode").querySelector('option[value="real"]');
    real.disabled = evm || !(state && state.real_ok);
    real.textContent = evm ? "Real (not on EVM yet)" : "Real";
    if (evm && $("ct-mode").value === "real") $("ct-mode").value = "sim";
    return evm;
  }
  function renderFollows() {
    const ul = $("ct-follows");
    if (!state.follows.length) { ul.innerHTML = `<li class="ct-empty">No wallet followed yet.</li>`; return; }
    ul.innerHTML = state.follows.map((f) => `
      <li class="ct-row" data-address="${esc(f.address)}">
        <span class="ct-badge is-${f.mode}">${MODE[f.mode]}</span>
        <span class="ct-grow"><b>${esc(f.label || short(f.address))}</b> <a class="ct-mono ct-dim" href="${walletUrl(f.address)}" target="_blank" rel="noopener">${short(f.address)}</a>${isEvm(f.address) ? ` ${chainChips(f.chains)}` : ""}</span>
        <span class="ct-dim">${f.copy === "both" ? "Entries and exits" : "Entries only"}</span>
        <span>${f.sizing === "pct" ? `${f.pct}%` : `${usd(f.fixed_usd)} / position`}</span>
        <button type="button" class="section-action-btn" data-act="analyze">Analyze</button>
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
        <span class="ct-grow"><a class="ct-mono" href="${tokenUrl(p.chain, p.token || p.mint)}" target="_blank" rel="noopener">${short(p.token || p.mint)}</a>${p.chain ? ` ${chainChips([p.chain])}` : ""} <span class="ct-dim">·</span> ${esc(names[p.leader] || short(p.leader))}</span>
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
      const txHref = t.tx ? txUrl(t.chain, t.tx) : null;
      const tx = txHref ? ` <a class="ct-dim" href="${txHref}" target="_blank" rel="noopener">tx</a>` : "";
      return `
      <li class="ct-row ${ok ? "" : "is-muted"}">
        <span class="ct-dim ct-time">${ago(t.t)}</span>
        <span class="ct-side is-${t.side}">${t.side === "buy" ? "BUY" : "SELL"}</span>
        <span class="ct-grow"><a class="ct-mono" href="${tokenUrl(t.chain, t.mint)}" target="_blank" rel="noopener">${short(t.mint)}</a>${t.chain ? ` ${chainChips([t.chain])}` : ""}
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
    renderEvm();
    renderChainPicker();
    renderFollows();
    renderPositions();
    renderLog();
    const lim = state.limits;
    for (const [id, k] of [["ct-max-trade", "max_trade_usd"], ["ct-max-day", "max_day_usd"], ["ct-max-open", "max_open"]]) {
      if (document.activeElement !== $(id)) $(id).value = lim[k];
    }
    $("ct-real-ok").checked = state.real_ok;
    addressKind();
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
    if (isEvm(f.address)) {
      const on = new Set(f.chains || []);
      document.querySelectorAll('input[name="ct-chain"]').forEach((b) => { b.checked = on.has(b.value); });
    }
    addressKind();
    $("ct-save").textContent = "Save";
    $("ct-address").scrollIntoView({ block: "center", behavior: "smooth" });
  }

  $("ct-address").addEventListener("input", addressKind);

  function reset() {
    editing = null;
    $("ct-form").reset();
    $("ct-address").readOnly = false;
    $("ct-save").textContent = "Follow";
    sizingLabel();
    addressKind();
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
    if (isEvm(body.address)) {
      body.chains = [...document.querySelectorAll('input[name="ct-chain"]:checked')].map((b) => b.value);
      if (!body.chains.length) { msg("Pick at least one network.", true); return; }
    }
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
      if (btn.dataset.act === "analyze") return analyze(address, false, isEvm(address) ? (f.chains || [])[0] : null);
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

  // ── Wallet profitability (wallet_pnl.py): 24 h / 7 d / 30 d ──────────
  const WINDOWS = [["24h", "Last 24 hours"], ["7d", "Last 7 days"], ["30d", "Last 30 days"]];
  const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);
  const cls = (v) => (v == null || v === 0 ? "" : v > 0 ? "ct-up" : "ct-down");
  let pnlRun = 0;

  const hold = (sec) => (sec == null ? "—" : sec < 3600 ? `${Math.max(1, Math.round(sec / 60))} min` : sec < 86400 ? `${(sec / 3600).toFixed(1)} h` : `${(sec / 86400).toFixed(1)} d`);
  let pnlChain = null;            // network of the result being drawn (null: Solana)
  const tokenLink = (t, c) => `<a class="ct-mono" href="${tokenUrl(pnlChain, t.mint)}" target="_blank" rel="noopener">${short(t.mint)}</a> <span class="${c}">${signed(t.pnl_usd)}</span>`;

  function pnlCard(key, label, w) {
    const rows = [
      ["Profit on closed trades", `<b class="${cls(w.pnl_usd)}">${signed(w.pnl_usd) || "$0"}</b>`],
      ["Return", `<b class="${cls(w.roi_pct)}">${pct(w.roi_pct)}</b>`],
      ["Closed trades", `${w.trades}`],
      ["Win rate", w.win_rate_pct == null ? "—" : `${w.win_rate_pct}% <span class="ct-dim">(${w.wins}/${w.trades})</span>`],
      ["Average win", w.avg_win_usd == null ? "—" : `<span class="ct-up">${signed(w.avg_win_usd)}</span>`],
      ["Average loss", w.avg_loss_usd == null ? "—" : `<span class="ct-down">${signed(w.avg_loss_usd)}</span>`],
      ["Put in", usd(w.invested_usd)],
      ["Got back", usd(w.returned_usd)],
      ["Median holding time", hold(w.median_hold_s)],
      ["Best trade", w.best ? tokenLink(w.best, "ct-up") : "—"],
      ["Worst trade", w.worst ? tokenLink(w.worst, "ct-down") : "—"],
    ];
    const out = [];
    if (w.excluded_open) out.push(`${w.excluded_open} still open`);
    if (w.excluded_opened_before) out.push(`${w.excluded_opened_before} opened before the period`);
    if (w.sells_without_cost) out.push(`${w.sells_without_cost} sells with no buy in the history`);
    return `<section class="ct-pnl-card" data-window="${key}"><h4>${label}</h4><dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      ${out.length ? `<p class="ct-reason"><span>Not counted:</span> ${out.map((x) => `<span>${x}</span>`).join(" · ")}</p>` : ""}</section>`;
  }

  function renderPnl(r) {
    const c = r.coverage;
    pnlChain = r.chain || null;
    const notes = [];
    if (r.bot_like) notes.push(`<p class="ct-warn">Looks like a bot: ${r.swaps_per_day} swaps a day. Copying it mostly pays fees.</p>`);
    if (c.partial) notes.push(`<p class="ct-warn">Too many transactions: only the latest ${c.transactions} were read.</p>`);
    if (c.unread) notes.push(`<p class="ct-reason">${c.unread} transactions could not be read and are missing.</p>`);
    if (r.chain ? !c.price_history : !c.sol_history) notes.push(`<p class="ct-reason">No ${r.chain ? esc(c.native) : "SOL"} price history: today's price was used.</p>`);
    if (r.chain && c.partial && c.from) notes.push(`<p class="ct-warn">Read back to ${new Date(c.from * 1000).toLocaleDateString("en-GB")} only: the rest of the 30 days took too long.</p>`);
    const open = r.still_open.length ? `<ul class="ct-list">${r.still_open.map((o) => `
      <li class="ct-row is-muted"><span class="ct-grow"><a class="ct-mono" href="${tokenUrl(r.chain, o.mint)}" target="_blank" rel="noopener">${short(o.mint)}</a> <span class="ct-dim">${ago(o.opened_at)}</span></span>
        <span class="ct-dim">put in</span> ${usd(o.invested_usd)}</li>`).join("")}</ul>` : "";
    const toks = r.tokens.length ? `<ul class="ct-list">${r.tokens.slice(0, 12).map((t) => `
      <li class="ct-row"><span class="ct-grow"><a class="ct-mono" href="${tokenUrl(r.chain, t.mint)}" target="_blank" rel="noopener">${short(t.mint)}</a></span>
        <span class="ct-dim">${t.trades} closed · ${t.wins} won</span> <b class="${cls(t.pnl_usd)}">${signed(t.pnl_usd) || "$0"}</b></li>`).join("")}</ul>` : "";
    const followed = state?.follows?.some((f) => f.address === r.address);
    $("ct-pnl-out").innerHTML = `
      <p class="ct-dim ct-pnl-head"><a class="ct-mono" href="${walletUrl(r.address)}" target="_blank" rel="noopener">${short(r.address)}</a>${r.chain ? ` ${chainChips([r.chain])}` : ""}
        · ${c.swaps} swaps in ${c.transactions} transactions · ${ago(r.generated_at)} ago
        ${followed ? "" : `<button type="button" class="section-action-btn" id="ct-pnl-follow">Copy this wallet</button>`}</p>
      <p class="ct-reason">Only trades opened and closed inside each period count: from the first buy to the last sell. Positions still open are left out.</p>
      ${notes.join("")}
      <div class="ct-pnl-grid">${WINDOWS.map(([k, l]) => pnlCard(k, l, r.windows[k])).join("")}</div>
      ${toks ? `<div class="section-title-row"><span class="section-eyebrow">Closed trades by token, 30 days</span></div>${toks}` : ""}
      ${open ? `<div class="section-title-row"><span class="section-eyebrow">Still open, not counted</span><span class="section-count">${r.still_open_count}</span></div>${open}` : ""}`;
    $("ct-pnl-follow")?.addEventListener("click", () => {
      reset();
      $("ct-address").value = r.address;
      $("ct-address").scrollIntoView({ block: "center", behavior: "smooth" });
      $("ct-address").focus();
    });
  }

  // EVM wallets are read one network at a time: the picker shows for 0x addresses only.
  function pnlChainPicker() {
    const sel = $("ct-pnl-chain");
    if (state?.evm && !sel.options.length) {
      sel.innerHTML = state.evm.chains.map((c) => `<option value="${esc(c.id)}">${esc(c.label)}</option>`).join("");
    }
    sel.hidden = !isEvm($("ct-pnl-address").value) || !sel.options.length;
    return sel.hidden ? null : sel.value;
  }
  $("ct-pnl-address").addEventListener("input", pnlChainPicker);

  async function analyze(address, fresh = false, chain = null) {
    const run = ++pnlRun;
    $("ct-pnl-address").value = address;
    if (chain) { pnlChainPicker(); $("ct-pnl-chain").value = chain; }
    chain = isEvm(address) ? (pnlChainPicker() || chain || "base") : null;
    $("ct-pnl").scrollIntoView({ block: "start", behavior: "smooth" });
    $("ct-pnl-go").disabled = true;
    $("ct-pnl-out").innerHTML = "";
    $("ct-pnl-progress").classList.remove("is-error");
    $("ct-pnl-progress").textContent = "Starting";
    try {
      const start = await api("/api/copytrade/analyze", { method: "POST", body: JSON.stringify({ address, fresh, chain }) });
      if (start.result) { renderPnl(start.result); $("ct-pnl-progress").textContent = ""; return; }
      let since = 0;
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1500));
        if (run !== pnlRun) return;
        const job = await api(`/api/jobs/${start.job}?since=${since}&visible=1`);
        since = job.log_total;
        if (job.log.length) $("ct-pnl-progress").textContent = job.log[job.log.length - 1].m;
        if (job.state === "finito") { renderPnl(job.result); $("ct-pnl-progress").textContent = ""; return; }
        // jobs.py prefixes the exception type ("RuntimeError: ..."): the sentence is what matters here.
        if (job.state !== "in corso") throw new Error((job.error || "Analysis failed").replace(/^[A-Za-z]+Error: /, ""));
      }
    } catch (e) {
      $("ct-pnl-progress").textContent = e.message;
      $("ct-pnl-progress").classList.add("is-error");
    } finally {
      if (run === pnlRun) $("ct-pnl-go").disabled = false;
    }
  }

  $("ct-pnl-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    analyze($("ct-pnl-address").value.trim(), true);
  });

  root.addEventListener("toggle", poll);
  sizingLabel();
  if (root.open) poll();
})();
