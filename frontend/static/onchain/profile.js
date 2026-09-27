/**
 * Your profile (backend: profiles.py, wealth.py, GET /api/profile).
 *
 * Lorenzo, with a trading app's profile screenshot: "uno deve vedere cosa
 * detiene, l'andamento del wallet nel tempo con un grafico [...] l'account
 * deve rimanere tutto nel database, uno deve poter scegliere anche
 * l'immagine profilo [...] un controllo maggiore su tutta la piattaforma".
 * Top to bottom, like the reference: picture (tap to change), name, @handle,
 * bio; hold time, trades, joined; what the wallets are worth with the change
 * and a line over 24h / 7d / 30d / All; cash with Deposit and the wallet
 * menu; positions, open (what the wallets hold now) or closed (the
 * system's round trips).
 */
import * as api from "@onchain/api.js";
import { escapeHtml, logo, usdShort } from "@onchain/format.js";
import { loadLinked } from "@onchain/userswap.js";

const RANGES = [["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["all", "All"]];
let root = null;
let data = null;
let range = "all";
let tab = "open";
let go = () => {};

const money = (v) => {
  if (v == null) return ["—", ""];
  const [i, d] = Math.abs(v).toFixed(2).split(".");
  return [`${v < 0 ? "−" : ""}$${Number(i).toLocaleString("en-US")}`, `.${d}`];
};
const signed = (v) => (v == null ? "" : `${v >= 0 ? "+" : "−"}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "▲" : "▼"} ${Math.abs(v * 100).toFixed(2)}%`);
const qty = (v) => (v == null ? "" : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}k` : v.toLocaleString("en-US", { maximumFractionDigits: 4 }));
const hold = (s) => (s == null ? "—" : s < 3600 ? `${Math.max(1, Math.round(s / 60))}m` : s < 86_400 ? `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m` : `${Math.floor(s / 86_400)}d ${Math.round((s % 86_400) / 3600)}h`);
const since = (t) => (t ? new Date(t * 1000).toLocaleDateString("en-US", { month: "short", year: "numeric" }) : "—");

const PENCIL = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/></svg>`;

function avatar(p, cls = "") {
  return p?.avatar_url
    ? `<img class="${cls}" src="${escapeHtml(p.avatar_url)}" alt="" decoding="async" />`
    : `<span class="${cls} me-empty" aria-hidden="true">${escapeHtml((p?.display_name ?? "?").trim().slice(0, 1).toUpperCase())}</span>`;
}

/** Your picture everywhere it stands for you: header and dock. */
function paintMe(p) {
  document.querySelectorAll("[data-me-avatar]").forEach((el) => { el.innerHTML = avatar(p); });
  const head = document.querySelector("#more-btn .avatar");
  if (head) head.innerHTML = p?.avatar_url ? `<img src="${escapeHtml(p.avatar_url)}" alt="" />` : "";
}

function chart(rows) {
  const W = 360, H = 170;
  if (!rows || rows.length < 2) return `<div class="pf-chart-empty">The line starts with the next reading of your wallets (every 10 minutes).</div>`;
  const ys = rows.map((r) => r[1]);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const t0 = rows[0][0], t1 = rows[rows.length - 1][0];
  const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * (W - 12);
  const y = (v) => 12 + (1 - (v - lo) / (hi - lo)) * (H - 24);
  const d = rows.map((r, i) => `${i ? "L" : "M"}${x(r[0]).toFixed(1)},${y(r[1]).toFixed(1)}`).join("");
  const up = ys[ys.length - 1] >= ys[0];
  return `<svg class="pf-line" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" data-sign="${up ? "up" : "down"}" role="img" aria-label="Wallet value over time">
    <defs><linearGradient id="pf-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".22"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
    <path class="area" d="${d}L${x(t1).toFixed(1)},${H}L0,${H}Z"/>
    <path class="ln" d="${d}"/>
    <circle class="halo" cx="${x(t1).toFixed(1)}" cy="${y(ys[ys.length - 1]).toFixed(1)}" r="11"/>
    <circle class="dot" cx="${x(t1).toFixed(1)}" cy="${y(ys[ys.length - 1]).toFixed(1)}" r="5"/>
  </svg>`;
}

/* ------------------------------------------------ connected wallets
 * Lorenzo: "dobbiamo dare la possibilita' di far collegare il wallet a
 * qualsiasi persona". The wallet signs a plain message (free, no
 * transaction); the server checks the signature; its holdings join the
 * profile, read-only. Browser wallets only (MetaMask, Rabby, Phantom):
 * on a phone without one, the wallet's own browser opens this page. */
const hexOf = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const shortAddr = (a) => `${a.slice(0, 5)}…${a.slice(-4)}`;
const evmProvider = () => window.ethereum ?? null;
const solProvider = () => window.phantom?.solana ?? (window.solana?.isPhantom ? window.solana : null);
const here = () => `${location.host}${location.pathname}#profile`;

async function connect(kind) {
  let address, sign;
  if (kind === "evm") {
    const eth = evmProvider();
    if (!eth) { location.href = `https://metamask.app.link/dapp/${here()}`; return; }
    [address] = await eth.request({ method: "eth_requestAccounts" });
    sign = (msg) => eth.request({ method: "personal_sign", params: [`0x${hexOf(new TextEncoder().encode(msg))}`, address] });
  } else {
    const sol = solProvider();
    if (!sol) {
      location.href = `https://phantom.app/ul/browse/${encodeURIComponent(location.href)}?ref=${encodeURIComponent(location.origin)}`;
      return;
    }
    const res = await sol.connect();
    address = (res?.publicKey ?? sol.publicKey).toString();
    sign = async (msg) => hexOf((await sol.signMessage(new TextEncoder().encode(msg), "utf8")).signature);
  }
  const { message } = await api.walletChallenge({ kind, address });
  const signature = await sign(message);
  const res = await api.walletLink({ signature });
  data.profile = res.profile;
  paint();
  load();   // the new wallet's holdings
  loadLinked();   // the token pages offer "My wallet" from now on
}

function walletsBox(p) {
  const rows = (p.wallets ?? []).map((w) => `<li>
      <span class="pf-wchain" data-kind="${escapeHtml(w.kind)}" aria-hidden="true">${w.kind === "evm" ? "◆" : "◎"}</span>
      <span class="pf-main"><b>${escapeHtml(shortAddr(w.address))}</b><small>${w.kind === "evm" ? "EVM · Robinhood Chain" : "Solana"} · connected</small></span>
      <button type="button" class="pf-x" data-unlink="${escapeHtml(w.kind)}:${escapeHtml(w.address)}" aria-label="Disconnect">✕</button>
    </li>`).join("");
  return `<section class="pf-wallets">
    <h3>Wallets</h3>
    ${rows ? `<ul class="pf-wl">${rows}</ul>` : `<p class="pf-none">Connect your own wallet: you sign a message to prove it's yours (free, not a transaction). We never see its keys.</p>`}
    <div class="pf-connect">
      <button type="button" data-connect="evm"><b>MetaMask / Rabby</b><small>Robinhood Chain</small></button>
      <button type="button" data-connect="solana"><b>Phantom</b><small>Solana</small></button>
    </div>
    <p class="pf-err" data-wallet-err></p>
  </section>`;
}

function positions(d) {
  if (tab === "closed") {
    const rows = d.closed ?? [];
    if (!rows.length) return `<p class="pf-none">No closed positions yet. The system's trades land here when it sells.</p>`;
    return `<ul class="pf-list">${rows.map((c) => `<li>
      ${logo(c.symbol, null, c.chain, c.token)}
      <span class="pf-main"><b>${escapeHtml(c.symbol)}</b><small>${hold(c.closed - c.opened)} held${c.mode === "sim" ? " · simulated" : ""}${c.why ? ` · ${escapeHtml(c.why)}` : ""}</small></span>
      <span class="pf-num"><b>${c.proceeds_usdg == null ? "—" : `$${c.proceeds_usdg.toFixed(2)}`}</b><em data-sign="${(c.ret ?? 0) >= 0 ? "up" : "down"}">${pct(c.ret)}</em></span>
    </li>`).join("")}</ul>`;
  }
  const rows = d.positions ?? [];
  if (!rows.length) return `<p class="pf-none">${d.missing?.length ? `Couldn't read ${d.missing.join(" and ")} right now.` : "Nothing held yet."}</p>`;
  return `<ul class="pf-list">${rows.map((p) => `<li>
    ${logo(p.symbol, p.image, p.chain, p.address)}
    <span class="pf-main"><b>${escapeHtml(p.name || p.symbol)}</b><small>${qty(p.amount)} ${escapeHtml(p.symbol)}${p.source === "connected" ? " · your wallet" : ""}</small></span>
    <span class="pf-num"><b>${p.value_usd == null ? "—" : `$${p.value_usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}</b>${p.price_usd ? `<small>$${p.price_usd < 0.01 ? p.price_usd.toPrecision(3) : p.price_usd.toFixed(2)}</small>` : ""}</span>
  </li>`).join("")}</ul>`;
}

function paint() {
  const d = data;
  const p = d.profile;
  const [whole, cents] = money(d.value);
  const ch = d.change?.[range];
  root.innerHTML = `
    <header class="pf-head">
      <label class="pf-pic" title="Change picture">
        ${avatar(p, "pf-img")}
        <span class="pf-edit" aria-hidden="true">${PENCIL}</span>
        <input type="file" accept="image/png,image/jpeg,image/webp" data-avatar hidden />
      </label>
      <h2 class="pf-name">${escapeHtml(p.display_name)}</h2>
      <p class="pf-handle">@${escapeHtml(p.handle)}</p>
      ${p.bio ? `<p class="pf-bio">${escapeHtml(p.bio)}</p>` : ""}
      <button type="button" class="pf-add" data-edit>${p.bio ? "Edit profile" : `<span aria-hidden="true">+</span> Add a bio`}</button>
      <ul class="pf-stats">
        <li><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>${hold(d.stats?.avg_hold_s)} avg. hold</li>
        <li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9h12l-3-3M19 15H7l3 3"/></svg>${d.stats?.trades ?? 0} trades</li>
        <li><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5.5" width="16" height="14" rx="2.5"/><path d="M4 10h16M9 3.5v4M15 3.5v4"/></svg>Joined ${since(p.joined)}</li>
      </ul>
    </header>
    <section class="pf-value">
      <div class="pf-top">
        <p class="pf-total"><b>${whole}</b><span>${cents}</span></p>
        <nav class="pf-range" aria-label="Period">${RANGES.map(([k, l]) => `<button type="button" data-range="${k}" aria-pressed="${k === range}">${l}</button>`).join("")}</nav>
      </div>
      <p class="pf-change" data-sign="${(ch ?? 0) >= 0 ? "up" : "down"}">${ch == null ? "" : `${signed(ch)} <span>${RANGES.find(([k]) => k === range)[1]}</span>`}</p>
      <div class="pf-chart">${chart(d.history?.[range])}</div>
    </section>
    <section class="pf-cash">
      <span class="pf-cash-ic" aria-hidden="true">$</span>
      <p><small>Total cash</small><b>${d.cash == null ? "—" : `$${d.cash.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}</b></p>
      <button type="button" class="pf-sq" data-sheet="receive" aria-label="Deposit"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button>
      <button type="button" class="pf-sq" data-wallet-menu aria-label="Wallet"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/></svg></button>
    </section>
    ${walletsBox(p)}
    <section class="pf-pos">
      <div class="pf-pos-head">
        <h3>Positions <span>(${tab === "open" ? (d.positions ?? []).length : (d.closed ?? []).length})</span></h3>
        <nav class="pf-seg" aria-label="Positions">
          <button type="button" data-tab="open" aria-pressed="${tab === "open"}">Open${tab === "open" ? ' <i aria-hidden="true"></i>' : ""}</button>
          <button type="button" data-tab="closed" aria-pressed="${tab === "closed"}">Closed</button>
        </nav>
      </div>
      ${positions(d)}
    </section>
    <dialog class="sheet pf-sheet" data-edit-sheet aria-label="Edit profile">
      <form method="dialog" class="pf-form">
        <h3>Edit profile</h3>
        <label>Name<input name="display_name" maxlength="40" value="${escapeHtml(p.display_name)}" required /></label>
        <label>Handle<span class="pf-at"><i>@</i><input name="handle" maxlength="20" pattern="[A-Za-z0-9_]{3,20}" value="${escapeHtml(p.handle)}" required /></span></label>
        <label>Bio<textarea name="bio" maxlength="160" rows="3" placeholder="What you trade, how you trade it">${escapeHtml(p.bio)}</textarea></label>
        <p class="pf-err" data-err></p>
        <div class="pf-actions"><button type="button" data-cancel>Cancel</button><button type="submit" value="save" class="pf-save">Save</button></div>
      </form>
    </dialog>`;
  delete root.dataset.loading;
  paintMe(p);
}

async function load() {
  try {
    data = await api.getProfile();
    paint();
  } catch (err) {
    if (!data) root.innerHTML = `<p class="pf-none">Couldn't load your profile: ${escapeHtml(err?.message ?? "try again")}</p>`;
  }
}

export function refreshProfile() {
  if (root) load();
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

export function mountProfile({ go: goTo } = {}) {
  root = document.getElementById("profile");
  if (!root) return;
  go = goTo ?? go;
  root.addEventListener("click", (event) => {
    const r = event.target.closest("[data-range]");
    if (r) { range = r.dataset.range; paint(); return; }
    const t = event.target.closest("[data-tab]");
    if (t) { tab = t.dataset.tab; paint(); return; }
    const sh = event.target.closest("[data-sheet]");
    if (sh) { document.dispatchEvent(new CustomEvent("lae:sheet", { detail: sh.dataset.sheet })); return; }
    if (event.target.closest("[data-wallet-menu]")) { document.dispatchEvent(new CustomEvent("lae:wallet-menu")); return; }
    if (event.target.closest("[data-edit]")) { root.querySelector("[data-edit-sheet]")?.showModal(); return; }
    if (event.target.closest("[data-cancel]")) root.querySelector("[data-edit-sheet]")?.close();
    const c = event.target.closest("[data-connect]");
    if (c) {
      connect(c.dataset.connect).catch((e) => {
        const el = root.querySelector("[data-wallet-err]");
        if (el) el.textContent = e?.code === 4001 ? "You cancelled it in the wallet." : (e?.message ?? "Couldn't connect.");
      });
      return;
    }
    const u = event.target.closest("[data-unlink]");
    if (u) {
      const [kind, ...rest] = u.dataset.unlink.split(":");
      api.walletUnlink(kind, rest.join(":")).then((res) => { data.profile = res.profile; paint(); load(); loadLinked(); }, () => {});
    }
  });
  root.addEventListener("submit", async (event) => {
    event.preventDefault();
    const f = new FormData(event.target);
    const err = root.querySelector("[data-err]");
    try {
      const res = await api.updateProfile({ display_name: f.get("display_name"), handle: f.get("handle"), bio: f.get("bio") });
      data.profile = res.profile;
      root.querySelector("[data-edit-sheet]")?.close();
      paint();
    } catch (e) { err.textContent = e?.message ?? "Couldn't save."; }
  });
  root.addEventListener("change", async (event) => {
    const input = event.target.closest("[data-avatar]");
    const file = input?.files?.[0];
    if (!file) return;
    root.querySelector(".pf-pic")?.setAttribute("data-busy", "");
    try {
      const res = await api.uploadAvatar({ data_url: await readFile(file) });
      data.profile = res.profile;
      paint();
    } catch (e) {
      alert(e?.message ?? "Couldn't change the picture.");
      root.querySelector(".pf-pic")?.removeAttribute("data-busy");
    }
  });
  // Your picture in the header and the dock, before the profile is opened.
  api.getProfile().then((d) => { data = d; paint(); }, () => {});
}
