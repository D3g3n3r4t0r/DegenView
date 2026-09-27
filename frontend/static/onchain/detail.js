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

const registry = new Map();
const INTERVALS = ["1m", "5m", "15m", "1h", "4h"];
const WATCH_KEY = "watchlist-v1";
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

function onClick(event) {
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
      <nav class="dt-tabs">
        <button type="button" data-dtab="signal">Signal</button>
        <button type="button" data-dtab="why">Why</button>
        <button type="button" data-dtab="info">Info</button>
      </nav>
      <div class="dt-pane" data-pane-body></div>
    </div>
    <div class="dt-cta">${TRADABLE.has(e.chain)
      ? `<button type="button" data-buy><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v8M8.5 12.5 12 16l3.5-3.5"/></svg>Buy</button>`
      : `<a class="buy-out" href="${escapeHtml(e.pairUrl || `https://dexscreener.com/${e.chain}/${e.token}`)}" target="_blank" rel="noopener"><svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg>Trade on DexScreener</a>`}</div>`;
  paintChips();
  paintTabs();
  paintChart();
  if (!d.open) {
    history.pushState({ detail: id }, "");
    document.documentElement.classList.add("detail-open");
    d.showModal();
    d.querySelector(".dt-scroll").scrollTop = 0;
  }
}

function paintChips() {
  dlg.querySelector("[data-chips]").innerHTML = INTERVALS.map((iv) =>
    `<button type="button" data-iv="${iv}"${iv === interval ? ' aria-pressed="true"' : ""}>${iv}</button>`).join("")
    + `<span class="sep"></span><span class="dt-legend"><i class="mk"></i>Alert</span>`;
}

function paintTabs() {
  dlg.querySelectorAll("[data-dtab]").forEach((b) => b.toggleAttribute("aria-current", b.dataset.dtab === tab));
  const e = current.e;
  const body = dlg.querySelector("[data-pane-body]");
  if (tab === "why") { body.innerHTML = e.why || `<p class="muted">Nothing to add yet.</p>`; return; }
  if (tab === "info") { body.innerHTML = e.info || infoFallback(e); return; }
  const alerts = e.alerts ?? [];
  body.innerHTML = alerts.length ? alerts.map((al) => `
    <article class="call">
      <p><b>Telegram alert</b><small>${age(al.at)[0]} ago</small></p>
      <div class="call-card">
        <span><small>At alert</small><b>${usdShort(al.cap0)} MC</b></span>
        <span><small>Now</small>${changePill(al.now)}</span>
        <span><small>Best 48h</small><b data-sign="${sign(al.max)}">${pct(al.max)}</b></span>
        <span><small>Best strategy</small><b data-sign="${sign(al.strategy?.return_pct == null ? null : al.strategy.return_pct / 100)}">${al.strategy?.return_pct == null ? "—" : `${al.strategy.return_pct > 0 ? "+" : ""}${Math.round(al.strategy.return_pct)}%`}</b></span>
      </div>
      <ol class="hours">${[1, 2, 3, 4, 5, 6, 8, 12, 24, 48].map((h) => {
        const r = al.returns?.[String(h)];
        return `<li><small>${h}h</small><b data-sign="${sign(r)}">${pct(r)}</b></li>`;
      }).join("")}</ol>
    </article>`).join("")
    : `<p class="muted">No Telegram alert on this token yet${e.kind === "gem" ? ": gems are alerted when they enter the board." : "."}</p>`;
}

function infoFallback(e) {
  return `<dl class="kv">
    <div><dt>Chain</dt><dd>${escapeHtml(e.chain)}</dd></div>
    <div><dt>Contract</dt><dd class="mono">${escapeHtml(e.token ?? "—")}</dd></div>
    ${e.pairUrl ? `<div><dt>Chart</dt><dd><a href="${escapeHtml(e.pairUrl)}" target="_blank" rel="noopener">DexScreener</a></dd></div>` : ""}
  </dl>`;
}

// Charts already fetched, shown at once while a fresh copy loads; a tap on
// a row starts the fetch before the page is even open.
const charts = new Map();   // "chain:pair:interval" -> {at, promise | candles}
const CHART_FRESH_MS = 30_000;

function chartFor(e, iv) {
  const k = `${e.chain}:${e.pair}:${iv}`;
  const hit = charts.get(k);
  if (hit && Date.now() - hit.at < CHART_FRESH_MS) return hit.promise;
  const promise = api.getTokenChart(e.chain, e.pair, e.symbol, iv)
    .then((d) => (d?.candles ?? []).filter((c) => Number.isFinite(c.close)))
    .then((candles) => { charts.set(k, { at: Date.now(), promise: Promise.resolve(candles), candles }); return candles; },
      (err) => { if (charts.get(k)?.promise === promise) charts.delete(k); throw err; });
  charts.set(k, { at: Date.now(), promise, candles: hit?.candles });
  if (charts.size > 60) charts.delete(charts.keys().next().value);
  return promise;
}

const defaultInterval = (e) => (e.kind === "gem" ? "1h" : "5m");

export function prefetchChart(id) {
  const e = registry.get(id);
  if (e?.pair) chartFor(e, defaultInterval(e)).catch(() => {});
}

async function paintChart() {
  const e = current.e;
  const box = dlg.querySelector("[data-chart]");
  if (!e.pair) { box.innerHTML = `<div class="dt-chart-empty">No pool to chart.</div>`; return; }
  const want = `${current.id}:${interval}`;
  box.dataset.want = want;
  const stale = charts.get(`${e.chain}:${e.pair}:${interval}`)?.candles;
  if (stale?.length >= 2) box.innerHTML = svgChart(stale, e);
  let candles;
  try {
    candles = await chartFor(e, interval);
  } catch {
    if (box.dataset.want === want && !stale) box.innerHTML = `<div class="dt-chart-empty">Chart unavailable right now.</div>`;
    return;
  }
  if (box.dataset.want !== want) return;
  if (candles.length < 2) { box.innerHTML = `<div class="dt-chart-empty">Not enough trades to chart yet.</div>`; return; }
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
  const up = ys[ys.length - 1] >= ys[0];
  return `<svg viewBox="0 0 ${W} ${H}" class="line-chart" data-sign="${up ? "up" : "down"}" role="img" aria-label="Market cap chart">
    ${ticks.map((v) => `<text x="${W - 4}" y="${y(v) + 4}" text-anchor="end">${usdShort(v)}</text>`).join("")}
    <line class="now" x1="0" x2="${W - R}" y1="${y(now)}" y2="${y(now)}"/>
    <path class="ln" d="${d}"/>
    <circle class="dot" cx="${x(t1)}" cy="${y(now)}" r="4"/>
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
