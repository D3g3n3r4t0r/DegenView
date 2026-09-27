/**
 * Token detail: a full-screen page over the current view, like the
 * reference app. Every list registers its rows here (register) and any
 * element with data-open="<id>" opens the page: logo, name and market cap,
 * a line chart of the market cap with a marker where each Telegram alert
 * fired, timeframe chips, three tabs (Signal: what the alerts paid; Why:
 * score, reasons and risks; Info: contract, links, the gem dossier) and a
 * Buy button that hands the token to the swap. The back gesture closes it.
 */
import * as api from "@onchain/api.js";
import { age, changePill, escapeHtml, logo, usdShort } from "@onchain/format.js";
import { openUserSwap, walletFor } from "@onchain/userswap.js";

const registry = new Map();
const INTERVALS = ["1m", "5m", "15m", "1h", "4h"];
const WATCH_KEY = "watchlist-v1";
const loading = new Set();
let dlg = null;
let current = null;
let interval = "15m";
let tab = "signal";

// Chains the wallet can swap on; the others (BSC, Base, Ethereum) are scanned, not traded here.
const TRADABLE = new Set(["solana", "robinhood"]);

/** entry: {kind, symbol, name, chain, token, pair, pairUrl, image, cap,
 *  change, ageTs, context, why, info, alerts: [alert_track items]} */
export function register(id, entry) {
  // Several lists know the same token (gems board, trophy, alerts): what
  // one adds (the dossier, the alerts) is kept when another re-registers.
  const old = registry.get(id) ?? {};
  const merged = { ...old };
  for (const [k, v] of Object.entries(entry)) if (v != null && !(Array.isArray(v) && !v.length && old[k]?.length)) merged[k] = v;
  registry.set(id, merged);
}

const pct = (f) => (f == null ? "—" : `${f > 0 ? "+" : ""}${Math.round(f * 100)}%`);
const sign = (f) => (f == null ? "" : f >= 0 ? "up" : "down");

function watched() {
  try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]")); } catch { return new Set(); }
}
function toggleWatch(id) {
  const w = watched();
  if (w.has(id)) w.delete(id); else w.add(id);
  try { localStorage.setItem(WATCH_KEY, JSON.stringify([...w])); } catch { /* private mode */ }
  return w.has(id);
}

function ensureDialog() {
  if (dlg) return dlg;
  dlg = document.createElement("dialog");
  dlg.className = "detail";
  dlg.setAttribute("aria-label", "Token");
  document.body.append(dlg);
  dlg.addEventListener("close", () => {
    document.documentElement.classList.remove("detail-open");
    if (history.state?.detail) history.back();
  });
  dlg.addEventListener("click", onClick);
  return dlg;
}

window.addEventListener("popstate", () => { if (dlg?.open && !history.state?.detail) dlg.close(); });

// Strategy names as the main site's select spells them.
const NAMES = {
  "Trend EMA": "Lorenzo (trend-follower)",
  "Trend HF": "Lorenzo HF (minuti on-chain)",
  "RSI+BB": "Gabriele (RSI+BB reversal)",
  "RSI+BB L/S": "Gabriele 2 (RSI+BB long/short)",
};

// The main site charts DEX pools by "SYM@chain:pool" (DexScreenerProvider
// .make_symbol). The pair may not be known yet: poolOf() finds it.
function bestLabel(e) {
  const rows = (e.alerts ?? [])[0]?.backtests?.rows ?? [];
  return rows.filter((r) => r.trades > 0 || r.in_position)
    .sort((a, b) => (b.return_pct ?? -1e9) - (a.return_pct ?? -1e9))[0]?.label;
}

async function mainChartUrl(e, strategyName) {
  const pair = e.pair || await poolOf(e);
  if (!pair) return "";
  const dex = encodeURIComponent(`${e.symbol}@${e.chain}:${pair}`);
  const name = encodeURIComponent(e.name || e.symbol);
  return `/?area=analizza&dex=${dex}&interval=5m&name=${name}`
    + (strategyName ? `&strategy=${encodeURIComponent(strategyName)}` : "");
}

async function onClick(event) {
  const t = event.target;
  if (t.closest("[data-back]")) { dlg.close(); return; }
  const iv = t.closest("[data-iv]");
  if (iv) { interval = iv.dataset.iv; paintChart(); paintChips(); return; }
  const tb = t.closest("[data-dtab]");
  if (tb) { tab = tb.dataset.dtab; paintTabs(); return; }
  if (t.closest("[data-watch]")) {
    const on = toggleWatch(current.id);
    t.closest("[data-watch]").setAttribute("aria-pressed", String(on));
    return;
  }
  if (t.closest("[data-share]")) {
    const url = current.e.pairUrl || location.href;
    if (navigator.share) navigator.share({ title: current.e.symbol, url }).catch(() => {});
    else navigator.clipboard?.writeText(url);
    return;
  }
  if (t.closest("[data-copy]")) { navigator.clipboard?.writeText(current.e.token ?? ""); return; }
  if (t.closest("[data-main-chart]")) {
    let label = t.closest("[data-main-chart]").dataset.mainChart;
    // "best": the strategy with the best backtest on this token's latest
    // alert, chosen for the viewer (Lorenzo: "non voglio selezionare le
    // strategie [...] mostrami i backtest migliori").
    if (label === "best") label = bestLabel(current.e) ?? "Trend EMA";
    // Opened now, inside the tap: iOS blocks a window opened after an await.
    const win = window.open("", "_blank");
    const url = await mainChartUrl(current.e, NAMES[label]);
    if (win && url) { win.opener = null; win.location.href = url; } else win?.close();
    return;
  }
  if (t.closest("[data-user-swap]")) { openUserSwap(current.e); return; }
  if (t.closest("[data-buy]")) {
    const e = current.e;
    dlg.close();
    document.dispatchEvent(new CustomEvent("lae:buy", { detail: { chain: e.chain, address: e.token, symbol: e.symbol } }));
  }
}

export function openDetail(id) {
  const e = registry.get(id);
  if (!e) return;
  current = { id, e };
  tab = "signal";
  interval = defaultInterval(e);
  const d = ensureDialog();
  const [a] = age(e.ageTs);
  d.innerHTML = `
    <header class="dt-bar">
      <button type="button" class="dt-back" data-back aria-label="Back"><svg viewBox="0 0 24 24"><path d="m15 5-7 7 7 7"/></svg></button>
      <span class="dt-crumbs"><b>${escapeHtml(e.symbol)}</b>${e.ageTs ? `<i></i><span class="age"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 14V7M8 9c0-3 2-4.5 5-4.5 0 3-2 4.5-5 4.5ZM8 8C8 5.5 6.3 4 3.5 4c0 2.6 1.7 4 4.5 4Z"/></svg>${a}</span>` : ""}</span>
      <span class="dt-actions">
        <button type="button" class="sq" data-watch aria-pressed="${watched().has(id)}" aria-label="Watch"><svg viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8 6.8 19.6l1-5.8L3.5 9.7l5.9-.8z"/></svg></button>
        <button type="button" class="sq" data-share aria-label="Share"><svg viewBox="0 0 24 24"><path d="M12 15V3.5M8 7.5l4-4 4 4M6 11H5v9.5h14V11h-1"/></svg></button>
      </span>
    </header>
    <div class="dt-scroll">
      <section class="dt-id">
        ${logo(e.symbol, e.image, e.chain, e.token).replace('class="logo"', 'class="logo big"')}
        <span class="dt-name"><b>${escapeHtml(e.name || e.symbol)}</b>
          <small>${escapeHtml(e.symbol)}
            <button type="button" class="ic" data-copy aria-label="Copy address"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V5H5v11h3"/></svg></button>
            ${e.pairUrl ? `<a class="ic" href="${escapeHtml(e.pairUrl)}" target="_blank" rel="noopener" aria-label="Open chart"><svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg></a>` : ""}
          </small></span>
        <span class="dt-mc"><small>MC</small><b>${usdShort(e.cap)}</b>${changePill(e.change)}</span>
      </section>
      ${e.context ? `<p class="dt-context">${e.context}</p>` : ""}
      <div class="dt-chart" data-chart><div class="dt-chart-empty">Loading chart…</div></div>
      <div class="dt-chips" data-chips></div>
      <button type="button" class="dt-mainchart" data-main-chart="best">Open on the analysis chart ↗</button>
      <nav class="dt-tabs">
        <button type="button" data-dtab="signal">Signal</button>
        <button type="button" data-dtab="why">Why</button>
        <button type="button" data-dtab="info">Info</button>
      </nav>
      <div class="dt-pane" data-pane-body></div>
    </div>
    ${e.noTrade ? "" : `<div class="dt-cta" data-two="${Boolean(walletFor(e.chain) && TRADABLE.has(e.chain))}">${walletFor(e.chain) && TRADABLE.has(e.chain)
      ? `<button type="button" class="dt-mine" data-user-swap><svg viewBox="0 0 24 24"><rect x="3.5" y="6" width="17" height="13" rx="3"/><path d="M3.5 10h17M16 14.5h1.5"/></svg>My wallet</button>` : ""}${TRADABLE.has(e.chain)
      ? `<button type="button" data-buy><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v8M8.5 12.5 12 16l3.5-3.5"/></svg>Buy</button>`
      : `<a class="buy-out" href="${escapeHtml(e.pairUrl || `https://dexscreener.com/${e.chain}/${e.token}`)}" target="_blank" rel="noopener"><svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg>Trade on DexScreener</a>`}</div>`}`;
  paintChips();
  paintTabs();
  paintChart();
  if (!d.open) {
    history.pushState({ detail: id }, "");
    document.documentElement.classList.add("detail-open");
    d.showModal();
    d.querySelector(".dt-scroll").scrollTop = 0;
  }
  if (e.chain && e.token) enrich(id, e);
}

// The page fetches the full dossier itself: whichever list opened it (Top,
// Database, radar, memes) Signal, Why and Info must be complete (Lorenzo,
// 27/09). Only what is missing is filled, so a list that already knows more
// (the gem board, the alerts) is not overwritten.
async function enrich(id, e) {
  loading.add(id);
  const r = await api.getToken(e.chain, e.token).catch(() => null);
  loading.delete(id);
  if (!r) { if (current?.id === id) paintTabs(); return; }
  if (r.alerts?.length && !(e.alerts?.length)) e.alerts = r.alerts;
  if (r.entry) {
    const lb = await import("@onchain/leaderboard.js");
    e.why ||= lb.gemWhy(r.entry) + (r.entry.on_board ? "" : `<p class="muted">Not on the board${r.entry.why ? `: ${escapeHtml(r.entry.why)}` : ""}.</p>`);
    e.info ||= lb.details(r.entry) + descriptionBlock(r.entry);
    e.dossier = r.entry;
  }
  if (current?.id === id) paintTabs();
}

function descriptionBlock(p) {
  const links = [["Website", p.website], ["GitHub", p.github],
                 ...(p.socials ?? []).map((s) => [s.type, s.url])]
    .filter(([, url]) => url)
    .map(([label, url]) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`);
  if (!p.description && !links.length) return "";
  return `${p.description ? `<p class="bd-summary">${escapeHtml(p.description)}</p>` : ""}${links.length ? `<p class="dt-links">${links.join("")}</p>` : ""}`;
}

function paintChips() {
  dlg.querySelector("[data-chips]").innerHTML = INTERVALS.map((iv) =>
    `<button type="button" data-iv="${iv}"${iv === interval ? ' aria-pressed="true"' : ""}>${iv}</button>`).join("")
    + `<span class="sep"></span><span class="dt-legend"><i class="mk"></i>Alert</span>`;
}

// The system's own trades on one alert, each with why it sold. A sell
// after a crash inside one candle says so: that loss was not a late exit.
const WHY = { signal: "trend turned", crash: "crashed inside one 5-min candle: first price to sell at", "48h": "48h window over", rug: "pool vanished while in" };
function systemTrades(al) {
  const ev = al.system?.events ?? [];
  if (!ev.length) return al.system ? `<p class="sys-none">System: ${al.system.state === "in" ? "in the trade" : "no entry yet"}${al.system.label ? ` · ${escapeHtml(al.system.label)}` : ""}</p>` : "";
  const t0 = al.at;
  return `<ol class="sys-trades">${ev.map((v) => {
    const after = Math.max(0, Math.round((v.t - t0) / 60));
    const when = after < 90 ? `${after} min` : `${Math.round(after / 60)}h`;
    if (v.side === "buy") return `<li data-side="buy"><b>Bought</b><span>${when} after the alert</span></li>`;
    const why = WHY[v.why] ?? "sold";
    return `<li data-side="sell" data-why="${escapeHtml(v.why ?? "")}"><b data-sign="${sign(v.ret)}">Sold ${pct(v.ret)}</b><span>${when} after · ${why}${v.why === "crash" && v.drop != null ? ` (${pct(v.drop)} in one candle)` : ""}</span></li>`;
  }).join("")}</ol>`;
}

function paintTabs() {
  dlg.querySelectorAll("[data-dtab]").forEach((b) => b.toggleAttribute("aria-current", b.dataset.dtab === tab));
  const e = current.e;
  const body = dlg.querySelector("[data-pane-body]");
  const pending = loading.has(current.id);
  if (tab === "why") { body.innerHTML = e.why || `<p class="muted">${pending ? "Loading…" : "Nothing to add yet."}</p>`; return; }
  if (tab === "info") { body.innerHTML = e.info || infoFallback(e); return; }
  const alerts = e.alerts ?? [];
  body.innerHTML = alerts.length ? alerts.map((al) => `
    <article class="call">
      <p><b>Telegram alert</b><small>${age(al.at)[0]} ago</small></p>
      <div class="call-card">
        <span><small>At alert</small><b>${usdShort(al.cap0)} MC</b></span>
        <span><small>Held now</small>${changePill(al.now)}</span>
        <span><small>Best 48h</small><b data-sign="${sign(al.max)}">${pct(al.max)}</b></span>
        <span><small>System</small><b data-sign="${sign(al.system?.ret)}">${al.system?.ret == null ? "—" : pct(al.system.ret)}</b></span>
      </div>
      <div class="strats">${al.systems ? al.systems.map((s) => strategyTrade(s, al.at, al.system?.label)).join("") : systemTrades(al)}</div>
      ${al.systems ? systemTrades(al) : ""}
      ${backtestTable(al)}
      <p class="hours-head">Just holding, from the alert</p>
      <ol class="hours">${[1, 2, 3, 4, 5, 6, 8, 12, 24, 48].map((h) => {
        const r = al.returns?.[String(h)];
        return `<li><small>${h}h</small><b data-sign="${sign(r)}">${pct(r)}</b></li>`;
      }).join("")}</ol>
    </article>`).join("")
    : `<dl class="kv">
        ${e.dossier ? `<div><dt>Score</dt><dd>${e.dossier.score != null ? Math.round(e.dossier.score) : "—"}</dd></div>
        <div><dt>Board</dt><dd>${e.dossier.on_board ? "on the board" : `not ranked${e.dossier.why ? `: ${escapeHtml(e.dossier.why)}` : ""}`}</dd></div>` : ""}
        <div><dt>Market cap</dt><dd>${usdShort(e.cap)}</dd></div>
        ${e.dossier?.liquidity_usd != null ? `<div><dt>Liquidity</dt><dd>${usdShort(e.dossier.liquidity_usd)}</dd></div>` : ""}
        ${e.ageTs ? `<div><dt>Age</dt><dd>${age(e.ageTs)[0]}</dd></div>` : ""}
      </dl>
      <p class="muted">${pending ? "Loading…" : `No Telegram alert on this token yet${e.kind === "gem" ? ": gems are alerted when they enter the board." : "."}`}</p>`;
}

function backtestTable(al) {
  const rows = al.backtests?.rows ?? [];
  if (!rows.length) return "";
  return `<table class="bt-table">
    <caption>Backtest on this chart</caption>
    <thead><tr><th>Strategy</th><th>Return</th><th>Trades</th><th>Win</th><th>Max DD</th></tr></thead>
    <tbody>${rows.map((r) => `<tr>
      <td><button type="button" class="bt-open" data-main-chart="${escapeHtml(r.label)}">${escapeHtml(r.label)} ↗</button></td>
      <td data-sign="${r.return_pct == null ? "" : sign(r.return_pct / 100)}">${r.return_pct == null ? "—" : pct(r.return_pct / 100)}</td>
      <td>${r.trades ?? "—"}</td>
      <td>${r.win_rate == null ? "—" : `${Math.round(r.win_rate)}%`}</td>
      <td>${r.max_dd == null ? "—" : `${r.max_dd.toFixed(1)}%`}</td>
    </tr>`).join("")}
    <tr>
      <td>Just holding</td>
      <td data-sign="${al.backtests.hold_pct == null ? "" : sign(al.backtests.hold_pct / 100)}">${al.backtests.hold_pct == null ? "—" : pct(al.backtests.hold_pct / 100)}</td>
      <td>—</td><td>—</td><td>—</td>
    </tr></tbody>
  </table>`;
}

function infoFallback(e) {
  return `<dl class="kv">
    <div><dt>Chain</dt><dd>${escapeHtml(e.chain)}</dd></div>
    <div><dt>Contract</dt><dd class="mono">${escapeHtml(e.token ?? "—")}</dd></div>
    ${e.pairUrl ? `<div><dt>Chart</dt><dd><a href="${escapeHtml(e.pairUrl)}" target="_blank" rel="noopener">DexScreener</a></dd></div>` : ""}
  </dl>`;
}

// Charts. Lorenzo: "il grafico impiega almeno 10 secondi ad aprirsi" and
// "in alcuni ticker non c'e' grafico proprio". GeckoTerminal is the only free
// source of candles and allows ~30 calls a minute per IP: through our server
// every viewer and every background job shared one quota. Now three sources
// race and the first with a line wins:
//   1. the server's copy, if it already has one (peek: never calls anyone);
//   2. GeckoTerminal straight from the browser, on the viewer's own quota;
//   3. the server fetching it, only if both above came back empty.
// No pool known (some gems) -> DexScreener says which is the token's main
// pool. Still no candles -> DexScreener's own chart, embedded.
const charts = new Map();   // "chain:pair:interval" -> {at, promise, candles}
const pools = new Map();    // "chain:token" -> pair address (or "" if none)
const CHART_FRESH_MS = 30_000;
const GECKO = "https://api.geckoterminal.com/api/v2";
const GECKO_NET = { solana: "solana", robinhood: "robinhood", base: "base", bsc: "bsc", ethereum: "eth" };
const GECKO_TF = { "1m": ["minute", 1], "5m": ["minute", 5], "15m": ["minute", 15], "1h": ["hour", 1], "4h": ["hour", 4] };
const DS_EMBED = new Set(["solana", "base", "bsc", "ethereum"]);   // chains DexScreener charts

async function fetchJson(url, ms) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal, headers: { Accept: "application/json" }, referrerPolicy: "no-referrer" });
    if (!r.ok) throw new Error(String(r.status));
    return await r.json();
  } finally { clearTimeout(t); }
}

async function poolOf(e) {
  if (e.pair) return e.pair;
  const k = `${e.chain}:${e.token}`;
  if (pools.has(k)) return pools.get(k);
  let pair = "";
  try {
    const rows = await fetchJson(`https://api.dexscreener.com/tokens/v1/${e.chain}/${e.token}`, 4000);
    const best = (Array.isArray(rows) ? rows : []).sort((x, y) => (y.liquidity?.usd ?? 0) - (x.liquidity?.usd ?? 0))[0];
    pair = best?.pairAddress ?? "";
  } catch { /* no pool found: the page says so */ }
  pools.set(k, pair);
  if (pair) e.pair = pair;
  return pair;
}

async function geckoDirect(e, pair, iv) {
  const net = GECKO_NET[e.chain];
  const [tf, agg] = GECKO_TF[iv] ?? GECKO_TF["5m"];
  if (!net) throw new Error("chain");
  const q = new URLSearchParams({ aggregate: agg, limit: 300, currency: "usd", ...(e.token ? { token: e.token } : {}) });
  const d = await fetchJson(`${GECKO}/networks/${net}/pools/${pair}/ohlcv/${tf}?${q}`, 6000);
  const rows = d?.data?.attributes?.ohlcv_list ?? [];
  return rows.map((r) => ({ time: r[0], close: Number(r[4]) })).filter((c) => Number.isFinite(c.close)).sort((a, b) => a.time - b.time);
}

const clean = (d) => (d?.candles ?? []).filter((c) => Number.isFinite(c.close));
const enough = (c) => { if (c.length < 2) throw new Error("empty"); return c; };

function chartFor(e, iv) {
  const k = `${e.chain}:${e.pair || e.token}:${iv}`;
  const hit = charts.get(k);
  if (hit && Date.now() - hit.at < CHART_FRESH_MS) return hit.promise;
  const promise = (async () => {
    const pair = await poolOf(e);
    if (!pair) return [];
    const peek = api.getTokenChart(e.chain, pair, e.symbol, iv, true).then(clean).then(enough);
    const direct = geckoDirect(e, pair, iv).then(enough);
    try {
      return await Promise.any([peek, direct]);
    } catch {
      return clean(await api.getTokenChart(e.chain, pair, e.symbol, iv));
    }
  })().then((candles) => { charts.set(k, { at: Date.now(), promise: Promise.resolve(candles), candles }); return candles; },
    (err) => { if (charts.get(k)?.promise === promise) charts.delete(k); throw err; });
  charts.set(k, { at: Date.now(), promise, candles: hit?.candles });
  if (charts.size > 60) charts.delete(charts.keys().next().value);
  return promise;
}

const defaultInterval = (e) => (e.kind === "gem" ? "1h" : "5m");

export function prefetchChart(id) {
  const e = registry.get(id);
  if (e?.pair || e?.token) chartFor(e, defaultInterval(e)).catch(() => {});
}

function embed(e) {
  if (!e.pair || !DS_EMBED.has(e.chain)) return `<div class="dt-chart-empty">No trades to chart yet.</div>`;
  const iv = { "1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240" }[interval] ?? "5";
  const src = `https://dexscreener.com/${e.chain}/${e.pair}?embed=1&loadChartSettings=0&trades=0&tabs=0&info=0&chartLeftToolbar=0&chartTheme=dark&theme=dark&chartStyle=2&chartType=marketCap&interval=${iv}`;
  return `<iframe class="dt-embed" src="${escapeHtml(src)}" title="${escapeHtml(e.symbol)} chart on DexScreener" loading="lazy" referrerpolicy="no-referrer"></iframe>`;
}

async function paintChart() {
  const e = current.e;
  const box = dlg.querySelector("[data-chart]");
  if (!e.pair && !e.token) { box.innerHTML = `<div class="dt-chart-empty">No pool to chart.</div>`; return; }
  const want = `${current.id}:${interval}`;
  box.dataset.want = want;
  const stale = charts.get(`${e.chain}:${e.pair || e.token}:${interval}`)?.candles;
  if (stale?.length >= 2) box.innerHTML = svgChart(stale, e);
  let candles = [];
  try {
    candles = await chartFor(e, interval);
  } catch { /* falls through to the embedded chart */ }
  if (box.dataset.want !== want) return;
  if (candles.length < 2) { if (!stale) box.innerHTML = embed(e); return; }
  box.innerHTML = svgChart(candles, e);
}

/** A line of the market cap (price scaled by the current cap), right axis,
 *  dashed "now" line with its tag, and alert markers on the line. */
function svgChart(candles, e) {
  const W = 360, H = 260, R = 58, T = 14, B = 18;
  const last = candles[candles.length - 1].close;
  const k = e.cap && last ? e.cap / last : 1;
  const ys = candles.map((c) => c.close * k);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi === lo) { hi *= 1.05; lo *= 0.95; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const t0 = candles[0].time, t1 = candles[candles.length - 1].time;
  const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * (W - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const d = candles.map((c, i) => `${i ? "L" : "M"}${x(c.time).toFixed(1)},${y(ys[i]).toFixed(1)}`).join("");
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  const now = ys[ys.length - 1];
  const marks = (e.alerts ?? []).filter((a) => a.at >= t0 && a.at <= t1).map((a) => {
    const i = candles.findIndex((c) => c.time >= a.at);
    const v = ys[Math.max(0, i)];
    return `<g class="mk" transform="translate(${x(a.at).toFixed(1)},${y(v).toFixed(1)})"><circle r="7"/><path d="M-2.6 1.6v-2a2.6 2.6 0 0 1 5.2 0v2l.9 1H-3.5z M-.9 3.4a.9.9 0 0 0 1.8 0"/></g>`;
  }).join("");
  // The system's own trades on this token: green up for a buy, red down for a sell.
  const trades = (e.alerts ?? []).flatMap((a) => a.system?.events ?? []).filter((v) => v.t >= t0 && v.t <= t1).map((v) => {
    const i = candles.findIndex((c) => c.time >= v.t);
    const yv = y(ys[Math.max(0, i)]);
    const buy = v.side === "buy";
    return `<path class="tr ${buy ? "buy" : "sell"}" transform="translate(${x(v.t).toFixed(1)},${(yv + (buy ? 12 : -12)).toFixed(1)})" d="${buy ? "M0-5 5 3H-5z" : "M0 5 5-3H-5z"}"><title>System ${buy ? "buy" : "sell"}</title></path>`;
  }).join("");
  const up = ys[ys.length - 1] >= ys[0];
  return `<svg viewBox="0 0 ${W} ${H}" class="line-chart" data-sign="${up ? "up" : "down"}" role="img" aria-label="Market cap chart">
    ${ticks.map((v) => `<text x="${W - 4}" y="${y(v) + 4}" text-anchor="end">${usdShort(v)}</text>`).join("")}
    <line class="now" x1="0" x2="${W - R}" y1="${y(now)}" y2="${y(now)}"/>
    <path class="ln" d="${d}"/>
    <circle class="dot" cx="${x(t1)}" cy="${y(now)}" r="4"/>${trades}
    ${marks}
    <g class="tag" transform="translate(${W - R + 4},${y(now) - 10})"><path d="M0 10 6 0h50v20H6z"/><text x="31" y="14" text-anchor="middle">${usdShort(now)}</text></g>
  </svg>`;
}

// Any row anywhere with data-open="<id>" opens the page.
// The finger is on the row: start the chart now, it lands while the page opens.
document.addEventListener("pointerdown", (event) => {
  const b = event.target.closest?.("[data-open]");
  if (b && registry.has(b.dataset.open)) prefetchChart(b.dataset.open);
}, { passive: true });
document.addEventListener("click", (event) => {
  const b = event.target.closest("[data-open]");
  if (!b || !registry.has(b.dataset.open)) return;
  event.preventDefault();
  openDetail(b.dataset.open);
});
