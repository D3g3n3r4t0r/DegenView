/**
 * Il radar: token giovani su Solana e Robinhood che una strategia
 * dell'archivio avrebbe tradato bene.
 *
 * Lorenzo: "una specie di alert costante che scansionando il mercato mi
 * propone [...] c'è questo ticker su Solana o su rete Robinhood che
 * performerebbe bene con questo tipo di strategia". Una riga per proposta,
 * toccandola il backtest per esteso. Propone e basta: nessun tasto compra.
 *
 * Tutto da GET /api/onchain/radar: il giro lo fa il server ogni 15 minuti.
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";

const ROOT = document.getElementById("onchain-embed") ?? document;
const POLL_MS = 60_000;
const CHAINS = { solana: "Solana", robinhood: "Robinhood" };
const SOURCES = { chain: "dalla catena", pumpfun: "pump.fun", gecko: "GeckoTerminal" };

let root = null;
let sheet = null;
let data = null;
let timer = null;
let known = null;  // proposte gia' viste: le nuove entrano con l'animazione

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v) >= 100 ? Math.round(Math.abs(v)) : Math.abs(v).toFixed(1)}%`);
const usd = (v) => {
  if (v == null) return "—";
  if (v >= 1e6) return `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M`;
  if (v >= 1e3) return `$${Math.round(v / 1e3)}k`;
  return `$${Math.round(v)}`;
};
const age = (h) => (h < 1 ? ageShort(h * 3600) : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} g`);
const ago = (ts) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 90 ? "ora" : s < 3600 ? `${Math.round(s / 60)} min fa` : `${Math.round(s / 3600)} h fa`;
};
const key = (p) => `${p.chain}:${p.token_address}`;
const lkey = (l) => `${l.chain}:${l.pair_address}`;
const ageShort = (s) => (s < 90 ? `${Math.max(1, Math.round(s))} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`);
const FRESH_S = 15 * 60;

let toast = null;
let stream = null;

export function mountRadar({ toast: notify } = {}) {
  toast = notify ?? null;
  root = ROOT.querySelector("#radar");
  sheet = ROOT.querySelector("#pilot-sheet");
  if (!root) return;  // la copia del wallet nella tab Trading non ha il radar
  root.addEventListener("click", (event) => {
    const row = event.target.closest("[data-radar]");
    if (row) openProposal(row.dataset.radar);
    const listing = event.target.closest("[data-listing]");
    if (listing) openListing(listing.dataset.listing);
  });
  listen();
  setInterval(() => data && paintListings(false), 30_000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
  refresh();
}

// I listing arrivano spinti dal server appena passano le soglie: il giro
// di lettura ogni minuto resta solo per il resto del radar.
function listen() {
  if (!window.EventSource || stream) return;
  stream = new EventSource("/api/onchain/radar/stream");
  stream.addEventListener("listing", (event) => {
    let item;
    try { item = JSON.parse(event.data); } catch { return; }
    if (!data) return;
    data.listings = [item, ...(data.listings ?? []).filter((x) => lkey(x) !== lkey(item))];
    paintListings(true);
    const age = item.created_at ? ` · nato ${ageShort(Date.now() / 1000 - item.created_at)} fa` : "";
    toast?.(`Nuovo: ${item.symbol}`, `${CHAINS[item.chain] ?? item.chain} · liq. ${usd(item.liquidity_usd)}${age}`);
    navigator.vibrate?.(25);
  });
}

async function refresh() {
  clearTimeout(timer);
  try {
    data = await api.getRadar();
    paint();
  } catch {
    // Il radar e' un di piu': se non risponde resta com'era, il pilota no.
  }
  if (document.visibilityState === "visible") timer = setTimeout(refresh, POLL_MS);
}

function clock() {
  if (data.running) return "scansiono…";
  if (!data.last_scan) return "primo giro a momenti";
  return ago(data.last_scan);
}

function paint() {
  const { proposals, chains } = data;
  root.hidden = false;
  root.dataset.running = String(Boolean(data.running));
  root.querySelector("[data-radar-clock]").textContent = clock();

  const isFirst = known === null;
  const seen = new Set(proposals.map(key));
  paintListings(false);
  root.querySelector("[data-radar-list]").innerHTML = proposals.length
    ? proposals.map((p) => row(p, !isFirst && !known.has(key(p)))).join("")
    : `<li class="pilot-empty">${escapeHtml(emptyText())}</li>`;
  known = seen;

  const parts = Object.entries(chains ?? {}).map(([c, info]) => `${CHAINS[c] ?? c} ${info.seen}`);
  root.querySelector("[data-radar-foot]").textContent = data.last_scan
    ? `Visti: ${parts.join(" · ")} · ${data.configs} strategie per token · solo long, costi DEX inclusi`
    : `Solana e Robinhood · età < ${data.filters.age_max_days} g · liquidità > ${usd(data.filters.liq_min_usd)} · cap < ${usd(data.filters.mcap_max_usd)}`;
}

let shownListings = null;

function paintListings(animate) {
  const box = root.querySelector("[data-radar-new]");
  const items = (data.listings ?? []).slice(0, 5);
  box.hidden = items.length === 0;
  const now = Date.now() / 1000;
  const before = shownListings;
  box.querySelector("ul").innerHTML = items.map((l) => {
    const age = l.created_at ? now - l.created_at : null;
    const meta = `${CHAINS[l.chain] ?? l.chain} · liq. ${usd(l.liquidity_usd)} · cap ${usd(l.market_cap)}`;
    const isNew = animate && before && !before.has(lkey(l));
    return `
      <li class="${isNew ? "is-new" : ""}">
        <button type="button" data-listing="${escapeHtml(lkey(l))}">
          <span class="tk" data-chain="${escapeHtml(l.chain)}" aria-hidden="true">${escapeHtml(l.symbol.slice(0, 2))}</span>
          <span class="tk-name"><b>${escapeHtml(l.symbol)}</b><small>${escapeHtml(meta)}</small></span>
          <span class="tk-state"><span class="num">${age == null ? "—" : ageShort(age)}</span><span class="chip" data-state="${age != null && age < FRESH_S ? "in" : "watch"}">${escapeHtml(SOURCES[l.source] ?? l.source)}</span></span>
        </button>
      </li>`;
  }).join("");
  shownListings = new Set(items.map(lkey));
}

function emptyText() {
  if (!data.last_scan) return "Al primo giro cerco token giovani con tanta liquidità e cap bassa, e li provo su tutte le strategie.";
  const tested = Object.values(data.chains ?? {}).reduce((n, c) => n + c.tested, 0);
  const young = Object.values(data.chains ?? {}).reduce((n, c) => n + c.too_young, 0);
  const bits = [`${tested} provati, nessuno passa il test`];
  if (young) bits.push(`${young} ancora troppo giovani per un backtest`);
  return `${bits.join(" · ")}.`;
}

function row(p, isNew) {
  const meta = `${CHAINS[p.chain] ?? p.chain} · ${age(p.age_hours)} · liq. ${usd(p.liquidity_usd)} · cap ${usd(p.market_cap)}`;
  return `
    <li class="${isNew ? "is-new" : ""}">
      <button type="button" data-radar="${escapeHtml(key(p))}">
        <span class="tk" data-chain="${escapeHtml(p.chain)}" aria-hidden="true">${escapeHtml(p.symbol.slice(0, 2))}</span>
        <span class="tk-name"><b>${escapeHtml(p.symbol)}</b><small>${escapeHtml(meta)}</small></span>
        <span class="tk-state"><span class="num" data-sign="up">${pct(p.return_pct)}</span><span class="chip" data-state="${p.in_position ? "in" : "watch"}">${escapeHtml(p.strategy.split(" · ")[0])}</span></span>
      </button>
    </li>`;
}

/* --------------------------------------------------------------- il grafico */

// Lo stile del grafico del sito principale (static/app.js, initCharts):
// candele vuote in salita, piene in discesa, mono, linea del prezzo
// tratteggiata. IN sotto la candela, OUT sopra, come li' — ma un colore
// per strategia, perche' qui se ne possono guardare piu' insieme.
const BULL = "#00d68f";
const BEAR = "#ff4560";
const PALETTE = ["#00d68f", "#f0a500", "#6ea8ff", "#ff7ad9", "#c8f169", "#9b6bff"];
const LIVE_MS = 30_000;

let view = null;  // { p, chart, series, strategies, shown:Set, active:Set, timer, fitted }

function chartLibrary() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  const tag = document.querySelector('script[src*="lightweight-charts"]');
  if (!tag) return Promise.reject(new Error("libreria del grafico mancante"));
  return new Promise((resolve, reject) => {
    tag.addEventListener("load", () => resolve(window.LightweightCharts), { once: true });
    tag.addEventListener("error", () => reject(new Error("libreria del grafico non caricata")), { once: true });
  });
}

function closeView() {
  if (!view) return;
  clearTimeout(view.timer);
  view.chart?.remove();
  view = null;
}

async function loadChart() {
  if (!view) return;
  const current = view;
  const { p } = current;
  try {
    const [payload, LightweightCharts] = await Promise.all([
      api.getRadarChart(p.chain, p.pair_address, p.symbol, p.interval),
      chartLibrary(),
    ]);
    if (view !== current) return;
    current.strategies = payload.strategies;
    // Un listing appena uscito non ha una strategia "migliore": si vedono tutte.
    if (!current.p.strategy && !current.seeded) {
      payload.strategies.filter((x) => !x.excluded).forEach((x) => current.shown.add(x.label));
      current.seeded = true;
    }
    current.active = new Set(payload.active);
    if (!current.chart) {
      const box = sheet.querySelector("[data-radar-chart]");
      box.textContent = "";
      current.chart = LightweightCharts.createChart(box, {
        autoSize: true,
        layout: { background: { color: "transparent" }, textColor: "#6e7681", fontSize: 11,
          fontFamily: "'JetBrains Mono', monospace", attributionLogo: false },
        grid: { vertLines: { color: "rgba(255,255,255,0.035)" }, horzLines: { color: "rgba(255,255,255,0.035)" } },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 4 },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        localization: { priceFormatter: (v) => (v >= 1 ? v.toFixed(2) : Number(v.toPrecision(3)).toString()) },
      });
      current.series = current.chart.addCandlestickSeries({
        upColor: "rgba(0,0,0,0)", downColor: BEAR, borderVisible: true,
        borderUpColor: BULL, borderDownColor: BEAR, wickUpColor: BULL, wickDownColor: BEAR,
        priceLineVisible: true, priceLineColor: "#f0a500", priceLineWidth: 1,
        priceLineStyle: LightweightCharts.LineStyle.Dashed, lastValueVisible: true,
        priceFormat: { type: "price", minMove: 1e-10, precision: 10 },
      });
    }
    current.series.setData(payload.candles);
    if (!current.fitted) {
      // Le ultime ~150 candele: abbastanza per leggere gli ingressi, poi zoom.
      const n = payload.candles.length;
      current.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 4 });
      current.fitted = true;
    }
    paintMarkers();
    paintStrategies();
    sheet.querySelector("[data-radar-live]").textContent = "live";
  } catch (error) {
    if (view !== current) return;
    const live = sheet.querySelector("[data-radar-live]");
    if (live) live.textContent = "non aggiornato";
    if (!current.chart) sheet.querySelector("[data-radar-chart]").textContent =
      error?.message ?? "Grafico non disponibile.";
  }
  if (view === current) current.timer = setTimeout(loadChart, LIVE_MS);
}

function colorOf(label) {
  const i = view.strategies.findIndex((s) => s.label === label);
  return PALETTE[i % PALETTE.length];
}

function paintMarkers() {
  const markers = [];
  for (const s of view.strategies) {
    if (!view.shown.has(s.label)) continue;
    const color = colorOf(s.label);
    for (const e of s.events) {
      markers.push(e.kind === "in"
        ? { time: e.time, position: "belowBar", color, shape: "arrowUp", text: "IN" }
        : { time: e.time, position: "aboveBar", color, shape: "circle", text: "OUT" });
    }
  }
  markers.sort((a, b) => a.time - b.time);
  view.series.setMarkers(markers);
}

function paintStrategies() {
  const tried = new Map(view.p.tried.map((t) => [t.label, t]));
  sheet.querySelector("[data-radar-strats]").innerHTML = view.strategies.map((s) => {
    const t = tried.get(s.label);
    const shown = view.shown.has(s.label);
    const on = view.active.has(s.strategy_name);
    const sub = s.excluded
      ? s.excluded
      : `${t ? `${pct(t.return_pct)} · ${t.trades} trade · ` : ""}${s.events.length ? (s.in_position ? "adesso dentro" : "adesso fuori") : "nessun segnale ancora"}`;
    return `
      <li data-shown="${shown}">
        <button type="button" class="rs-show" data-show="${escapeHtml(s.label)}" aria-pressed="${shown}">
          <span class="rs-swatch" style="--c:${colorOf(s.label)}"></span>
          <span class="tk-name"><b>${escapeHtml(s.label)}</b><small>${escapeHtml(sub)}</small></span>
        </button>
        ${s.excluded ? "" : `<button type="button" class="rs-switch" role="switch" aria-checked="${on}"
          aria-label="Alert ${escapeHtml(s.label)}" data-follow="${escapeHtml(s.label)}"><span></span></button>`}
      </li>`;
  }).join("");
}

async function follow(label) {
  const s = view?.strategies.find((x) => x.label === label);
  if (!s) return;
  const { p } = view;
  const next = !view.active.has(s.strategy_name);
  const el = sheet.querySelector(`[data-follow="${CSS.escape(label)}"]`);
  el?.setAttribute("aria-checked", String(next));
  try {
    const res = await api.followRadar({
      chain: p.chain, pool: p.pair_address, symbol: p.symbol, token_address: p.token_address,
      interval: p.interval, strategy_name: s.strategy_name, params: s.params, enabled: next,
    });
    if (!view) return;
    view.active = new Set(res.active);
  } catch {
    el?.setAttribute("aria-checked", String(!next));
    return;
  }
  paintStrategies();
}

function onSheetClick(event) {
  if (!view) return;
  const show = event.target.closest("[data-show]");
  if (show) {
    const label = show.dataset.show;
    view.shown.has(label) ? view.shown.delete(label) : view.shown.add(label);
    paintMarkers();
    paintStrategies();
    return;
  }
  const sw = event.target.closest("[data-follow]");
  if (sw) follow(sw.dataset.follow);
}

function openListing(id) {
  const l = data?.listings?.find((x) => lkey(x) === id);
  if (!l || !sheet) return;
  const age = l.created_at ? Date.now() / 1000 - l.created_at : null;
  // Troppo giovane per un backtest: il grafico a 1 minuto e le strategie
  // si vedono lo stesso, i numeri del test no.
  openSheet({ ...l, interval: "1m", tried: [], strategy: null, age_hours: (age ?? 0) / 3600 }, `
    <dl class="pilot-stats radar-stats">
      <div><dt>Liquidità</dt><dd>${usd(l.liquidity_usd)}</dd></div>
      <div><dt>Cap</dt><dd>${usd(l.market_cap)}</dd></div>
      <div><dt>Liq. / cap</dt><dd>${Math.round((l.liquidity_usd / l.market_cap) * 100)}%</dd></div>
      <div><dt>Nato</dt><dd>${age == null ? "—" : `${ageShort(age)}<span> fa</span>`}</dd></div>
      <div><dt>Visto dopo</dt><dd>${l.latency_s == null ? "—" : ageShort(l.latency_s)}</dd></div>
      <div><dt>Fonte</dt><dd><span>${escapeHtml(SOURCES[l.source] ?? l.source)}</span></dd></div>
    </dl>
    <p class="radar-note">Appena uscito: ancora troppa poca storia per un backtest. Il radar lo riprova da solo quando ne ha abbastanza. L'interruttore accende solo l'alert.</p>`);
}

function openProposal(id) {
  const p = data?.proposals.find((x) => key(x) === id);
  if (!p || !sheet) return;
  const ratio = p.market_cap ? p.liquidity_usd / p.market_cap : null;
  const pf = p.profit_factor == null ? "∞" : p.profit_factor.toFixed(1);
  openSheet(p, `
    <dl class="pilot-stats radar-stats">
      <div><dt>${escapeHtml(p.strategy.split(" · ")[0])}</dt><dd data-sign="up">${pct(p.return_pct)}</dd></div>
      <div><dt>Tenerlo</dt><dd>${pct(p.hold_pct)}</dd></div>
      <div><dt>Drawdown</dt><dd>${p.max_dd.toFixed(0)}%</dd></div>
      <div><dt>Liquidità</dt><dd>${usd(p.liquidity_usd)}</dd></div>
      <div><dt>Cap</dt><dd>${usd(p.market_cap)}<span> · ${ratio == null ? "—" : `${Math.round(ratio * 100)}%`}</span></dd></div>
      <div><dt>PF · trade</dt><dd>${pf}<span> · ${p.trades}</span></dd></div>
    </dl>
    <p class="radar-note">${escapeHtml(`${p.days} g di storia, la migliore di ${p.configs_tried} strategie: numero ottimistico. Solo long, ${data.costs.commission_pct}% + ${data.costs.slippage_pct}% di costi per lato. L'interruttore accende solo l'alert: il pilota non compra da solo.`)}</p>`);
}

function openSheet(p, details) {
  closeView();
  if (!sheet.dataset.radarWired) {
    sheet.dataset.radarWired = "1";
    sheet.addEventListener("click", onSheetClick);
    sheet.addEventListener("close", closeView);
  }
  sheet.querySelector(".pilot-sheet-body").innerHTML = `
    <header class="diag-head">
      <span class="tk" aria-hidden="true">${escapeHtml(p.symbol.slice(0, 2))}</span>
      <div><h2>${escapeHtml(p.symbol)}</h2><p>${escapeHtml(`${CHAINS[p.chain] ?? p.chain} · nato ${age(p.age_hours)} fa · candele ${p.interval}`)}</p></div>
      <span class="radar-live" data-radar-live>…</span>
    </header>
    <div class="radar-chart" data-radar-chart></div>
    <ul class="radar-strats" data-radar-strats></ul>
    ${details}
    <div class="radar-actions">
      <a class="btn-quiet" href="${escapeHtml(p.pair_url)}" target="_blank" rel="noopener">DexScreener ↗</a>
      <button type="button" class="btn-quiet" data-close>Chiudi</button>
    </div>`;
  view = { p, chart: null, series: null, strategies: [], shown: new Set(p.strategy ? [p.strategy] : []), active: new Set(), timer: null, fitted: false };
  if (!sheet.open) sheet.showModal();
  loadChart();
}
