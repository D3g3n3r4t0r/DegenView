/**
 * Arenas: the best quality low caps, each ranked against its own narrative.
 *
 * Lorenzo, 27/09, replaced Picks with a Top 15/25/50 ("voglio semmai
 * sniperare progetti di qualita' con capitalizzazioni basse"); 07/10: "la
 * top50 come concetto e' limitante, serve un sistema meritocratico [...]
 * data la complessita' dei progetti e le diverse narrative". Now the list is
 * arenas.py: one arena per narrative (and one for layer chains), no fixed
 * size, the projects at or above the arena's median "in" and the rest on its
 * bench. The podium is pound for pound: the projects that lead their own
 * arena by the most. Refreshed every POLL_MS; a tap opens the token page.
 *
 * Lorenzo, 16/10: the podium's three sit fixed in the top bar, and every
 * arena is listed open (tokens and scores) instead of the mosaic of tiles.
 * The podium is now the Top 25's first three, by score, not pound for pound.
 */
import * as api from "@onchain/api.js";
import { register } from "@onchain/detail.js";
import { isHidden, onHiddenChange, withEntrance } from "@onchain/hidden.js";
import { escapeHtml, tile, tokenRow, usdShort } from "@onchain/format.js";
import { shownSummary } from "@onchain/lab-shown.js";
import * as narr from "@onchain/narrative_pick.js";
import { disintegrate } from "@onchain/particles.js";
import "@onchain/motion.js";

const POLL_MS = 30_000;
// Trading off (Lorenzo, 07/10): rows show the market, not a backtest.
const TRADING = document.documentElement.dataset.trading === "on";

let root = null;
let arenas = [];
let entries = [];   // the Top by score: Top 25 and the podium
let labStatus = null;
let filtered = false;   // the last load was narrowed by narrative
let labels = {};        // narrative key -> label, from the coverage
// The single-arena view went with the mosaic (16/10): forget a remembered one.
try { localStorage.removeItem("lae:arena"); } catch { /* private mode */ }

// Each arena's champion on the last visit (Lorenzo, 28/09: "se rientro dopo
// un po' e c'e' stato un capovolgimento [...] fai una bella animazione"):
// arena key -> {id, symbol}.
const SEEN_KEY = "lae:arena-crowns";
function readSeen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY)) || null; } catch { return null; } }
function writeSeen(map) { try { localStorage.setItem(SEEN_KEY, JSON.stringify(map)); } catch { /* private mode */ } }
let seen = readSeen();
let shown = false;
let stale = false;          // new data arrived while the arenas were off screen
const idOf = (e) => `gem:${e.chain}:${e.token_address}`;
// The arenas sit in a tab: painted while another tab is open, the "since your
// last visit" animation would play unseen (Lorenzo, 29/09). It waits until it shows.
const onScreen = () => document.visibilityState === "visible" && root.getClientRects().length > 0;

let playing = false;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Each dethroned champion turns to dust over the row of the one that took
 *  its place, one arena after the other. Leaving the tab stops it and keeps
 *  the crowns unseen, so it plays again next time. */
async function sequence(changes, crowns) {
  playing = true;
  let aborted = false;
  for (const { li, was } of changes) {
    if (!onScreen()) { aborted = true; break; }
    const ghost = li.cloneNode(true);
    ghost.classList.remove("rank-new", "rank-wait");
    ghost.setAttribute("aria-hidden", "true");
    const r = li.getBoundingClientRect();
    Object.assign(ghost.style, { position: "fixed", visibility: "hidden", top: `${r.top}px`, left: `${r.left}px`,
      width: `${r.width}px`, margin: "0", animation: "none" });
    const name = ghost.querySelector(".trow-main b");
    if (name) name.textContent = `1. ${was.symbol ?? ""}`;
    ghost.querySelectorAll(".trow-main small, .trow-num b, img, svg").forEach((x) => x.remove());
    document.body.append(ghost);
    await disintegrate(ghost, 900);
    ghost.remove();
    li.classList.remove("rank-wait");
    li.classList.add("rank-new");
    await wait(300);
  }
  root.querySelectorAll("[data-top-arenas] li.rank-wait").forEach((li) => li.classList.remove("rank-wait"));
  playing = false;
  if (aborted) { stale = true; return; }
  seen = crowns;
  writeSeen(seen);
}

const heatBar = (h) => `<span class="ar-heat" aria-label="Narrative heat ${h} of 3">${"█".repeat(h)}${"░".repeat(Math.max(0, 3 - h))}</span>`;
// What the tile counts is what the list shows: tokens hidden by the user left out.
const unhidden = (a) => a.entries.filter((e) => !isHidden(e.chain, e.token_address));
const shownCount = (a) => unhidden(a).length;
// Every arena open, biggest first (Lorenzo, 16/10: "le sezioni [...] non
// siano chiuse ma elencate in modo da poter vedere i token presenti in ogni
// lista"): the ranking and the score of each token, no chart beside them.
function listHtml() {
  const list = arenas.filter((a) => shownCount(a)).sort((a, b) => shownCount(b) - shownCount(a));
  return list.length ? `<div class="ar-grid">${list.map((a) => arenaHtml(a, true)).join("")}</div>` : "";
}

function row(e, a) {
  const id = idOf(e);
  const rank = e.arena_rank;
  register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
    pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
    ageTs: e.launched_at, rank, context: `${a.label} · #${rank} of ${a.size} · score ${Math.round(e.score ?? 0)}` });
  const html = tokenRow({ id, symbol: e.symbol, name: `${rank}. ${e.name || e.symbol}`, chain: e.chain, token: e.token_address,
    image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at,
    score: e.score, badge: e.early ? "early" : e.hidden ? "hidden" : null, sub: TRADING ? btSub(e.backtests) : marketSub(e) });
  return html.replace('<li class="trow"', `<li class="trow${rank === 1 ? " ar-champ" : ""}" style="--v:${Math.max(0, Math.min(100, Math.round(e.score ?? 0)))}%"`);
}

function arenaHtml(a, open = false) {
  const rows = a.entries.filter((e) => !isHidden(e.chain, e.token_address));
  if (!rows.length) {
    return open && !a.entries.length ? `<section class="arena" data-arena="${escapeHtml(a.key)}"><header class="ar-head"><h4>${escapeHtml(a.label)}</h4></header>
      <p class="muted pad">No ${escapeHtml(a.label)} project has passed the checks yet: they appear here as the research finds them.</p></section>` : "";
  }
  const inn = open ? rows : rows.filter((e) => e.in);
  const bench = open ? [] : rows.filter((e) => !e.in);
  return `<section class="arena" data-arena="${escapeHtml(a.key)}">
    <header class="ar-head"><h4>${escapeHtml(a.label)}</h4>${a.heat ? heatBar(a.heat) : ""}<span class="ar-count">${open ? `${rows.length} projects` : `${inn.length} in`} · median ${Math.round(a.median)}</span></header>
    <ol class="memes-list" data-top-rows>${inn.map((e) => row(e, a)).join("")}</ol>
    ${bench.length ? `<details class="ar-bench"><summary>${bench.length} below the arena median</summary>
      <ol class="memes-list" data-top-rows>${bench.map((e) => row(e, a)).join("")}</ol></details>` : ""}
  </section>`;
}

function paint() {
  if (!root || playing) return;
  delete root.dataset.loading;
  const firstPaint = !shown;
  root.querySelector(".top-wait")?.remove();
  // The podium in the top bar is the Top 25's first three, same order
  // (Lorenzo, 16/10: it was pound for pound — the lead over the arena's
  // median — and disagreed with the Top 25, which ranks by score).
  const top3 = bestByScore(entries).slice(0, 3).map((e, i) => {
    register(idOf(e), { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address,
      pair: e.pair_address, pairUrl: e.pair_url, image: e.image, cap: e.market_cap,
      change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at, rank: i + 1,
      context: `Top 25 · #${i + 1} · score ${Math.round(e.score ?? 0)}` });
    return { ...e, arena_label: arenaOf(e) };
  });
  paintTop3(top3);

  const box = root.querySelector("[data-top-arenas]");
  withEntrance(box, () => {
    box.innerHTML = listHtml() || `<p class="muted pad">The arenas are filling up: projects appear as they pass the checks.</p>`;
  });

  // A narrowed view is not what the last visit saw: no comparison.
  const visible = onScreen();
  if (!visible) stale = true;
  const prev = !filtered && seen && visible ? seen : null;
  const crowns = Object.fromEntries(arenas.filter((a) => a.entries.length)
    .map((a) => [a.key, { id: idOf(a.entries[0]), symbol: a.entries[0].symbol }]));
  const changes = [];
  const lead = [];
  if (prev) {
    for (const a of arenas) {
      const was = prev[a.key];
      const now = crowns[a.key];
      if (!was || !now || was.id === now.id) continue;
      const li = box.querySelector(`[data-arena="${CSS.escape(a.key)}"] li.ar-champ`);
      if (li) { li.classList.add("rank-wait"); changes.push({ li, was }); }
      lead.push(`${now.symbol} took ${a.label} from ${was.symbol}`);
    }
  }
  if (arenas.length && !filtered && visible) {
    shown = true;
    stale = false;
    if (changes.length) sequence(changes, crowns);
    else { seen = crowns; writeSeen(seen); }
  }
  // A project shows in each of its narratives (also: true) but counts once.
  const total = new Set(arenas.flatMap((a) => a.entries.map(idOf))).size;
  const narrLine = filtered
    ? `<button type="button" class="top-narr-clear" data-top-narr-clear>${escapeHtml(narr.get().map((k) => labels[k] ?? k).join(", "))} ✕</button> `
    : "";
  const head = lead.length ? `${firstPaint ? "Since your last visit: " : ""}${lead.slice(0, 3).join(", ")}. ` : "";
  const bt = labStatus;
  root.querySelector("[data-top-note]").innerHTML = narrLine + escapeHtml(head
    + (total ? `${arenas.length} arenas · ${total} projects` : "")
    + (TRADING && bt?.total ? ` · backtests ${bt.ready}/${bt.total} ready` : ""))
    + (TRADING ? ' <button type="button" class="top-narr-clear" data-top-wallet>$10k wallet on these trades →</button>' : "");
}

// The three of the podium, fixed in the top bar on every view.
function paintTop3(list) {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  let el = bar.querySelector("[data-top3]");
  if (!el) {
    el = document.createElement("nav");
    el.className = "tb-top3";
    el.dataset.top3 = "";
    el.setAttribute("aria-label", "Top three gems");
    bar.querySelector(".tb-me")?.after(el);
  }
  el.hidden = !list.length;
  el.innerHTML = list.map((e, i) => `<button type="button" class="t3" data-open="${escapeHtml(idOf(e))}"
      title="${escapeHtml(`${e.name || e.symbol} · #${i + 1} of the Top 25 · score ${Math.round(e.score ?? 0)}${e.arena_label ? ` · ${e.arena_label}` : ""}`)}">
      <i class="t3-place">${i + 1}</i>${tile(e.symbol, e.image, e.chain, e.token_address)}
      <span class="t3-main"><b>${escapeHtml(e.symbol ?? "")}</b><small>score ${Math.round(e.score ?? 0)}${e.arena_label ? ` · ${escapeHtml(SHORT[e.arena_label] || e.arena_label)}` : ""}</small></span>
    </button>`).join("");
}
const SHORT = {
  "Perps & Derivatives": "Perps", "Chains L0/L1/L2": "Chains", "Stablecoin Payments": "Payments",
  "Wallets & Account Abstraction": "Wallets", "NFT & Collectibles": "NFT", "Lending & Credit": "Lending",
  "Music & Media": "Music", "Dev Tools & RPC": "Dev tools", "Yield & Vaults": "Yield",
  "Robotics / Physical AI": "Robotics", "Identity / Personhood": "Identity", "AI Data / Oracles": "AI Data",
  "Prediction Markets": "Predictions", "Chain Abstraction": "Chain Abstr.", "AI-Managed Money": "AI Money",
};

// Without trading: measured usage (usage.py), what put the project here.
const compact = (n) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);

function marketSub(e) {
  const u = e.usage ?? {};
  const vol = u.vol_7d_avg ?? u.vol_24h;
  // Short enough for a phone row: "$812k/day · 15.2k holders".
  const parts = [vol != null ? `${usdShort(vol)}/day` : null,
    u.holders != null ? `${compact(u.holders)} holders` : null];
  const line = parts.filter(Boolean).join(" · ");
  return line || (e.liquidity_usd != null ? `Liquidity ${usdShort(e.liquidity_usd)}` : "");
}

// Pearl (Lorenzo, 16/10): "le gemme selezionate su Early che pero' hanno
// ottenuto un punteggio pari o superiore a 70".
const PEARL_MIN = 70;
function earlyRow(e, context) {
  const id = `gem:${e.chain}:${e.token_address}`;
  register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
    pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
    ageTs: e.launched_at, context: `${context} · score ${Math.round(e.score ?? 0)}` });
  return tokenRow({ id, symbol: e.symbol, name: e.name || e.symbol, chain: e.chain, token: e.token_address,
    image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at,
    score: e.score, badge: "early", sub: marketSub(e) });
}
function paintPearl(list) {
  const box = document.querySelector("[data-pearl-view]");
  if (!box) return;
  // the score as shown (rounded): a "70" on screen is always a pearl
  const pearls = list.filter((e) => Math.round(e.score ?? 0) >= PEARL_MIN).sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  box.querySelector("[data-pearl-empty]").hidden = pearls.length > 0;
  box.querySelector("[data-pearl-rows]").innerHTML = pearls.map((e) => earlyRow(e, "Pearl")).join("");
}

// Top (Lorenzo, 16/10): "classificare le migliori 25 gemme per punteggio
// rank" — the Top's entries (board and database rows, gated), by score.
const RANK_N = 25;
// One order for the Top 25 and the podium: score, then the server's order.
const bestByScore = (list) => list.filter((e) => !isHidden(e.chain, e.token_address))
  .map((e, i) => [e, i]).sort(([a, i], [b, j]) => (b.score ?? 0) - (a.score ?? 0) || i - j).map(([e]) => e);
// The arena a token leads in, else the first that lists it (the podium's label).
function arenaOf(e) {
  const id = idOf(e);
  const has = arenas.filter((a) => a.entries.some((x) => idOf(x) === id));
  return (has.find((a) => idOf(a.entries[0]) === id) ?? has[0])?.label ?? "";
}
function paintRank(list) {
  const box = document.querySelector("[data-rank-view]");
  if (!box) return;
  const best = bestByScore(list).slice(0, RANK_N);
  box.querySelector("[data-rank-empty]").hidden = best.length > 0;
  box.querySelector("[data-rank-rows]").innerHTML = best.map((e, i) => {
    const id = idOf(e);
    register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
      pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
      ageTs: e.launched_at, rank: i + 1, context: `Top 25 · #${i + 1} · score ${Math.round(e.score ?? 0)}` });
    return tokenRow({ id, symbol: e.symbol, name: `${i + 1}. ${e.name || e.symbol}`, chain: e.chain, token: e.token_address,
      image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at,
      score: e.score, badge: e.early ? "early" : e.hidden ? "hidden" : null, sub: marketSub(e) });
  }).join("");
}

// Its own view in the dock (Lorenzo, 07/10: "la sezione EARLY non la trovo").
function paintEarly(list) {
  const box = document.querySelector("[data-early-view]");
  if (!box) return;
  box.querySelector("[data-early-empty]").hidden = list.length > 0;
  box.querySelector("[data-early-rows]").innerHTML = list.map((e) => earlyRow(e, "Early")).join("");
}

// The H24 lab's best backtest (strategy_lab.py), in the row: what the
// Strategies tab is for (Lorenzo, 28/09).
function btSub(b) {
  if (!b) return '<span class="bt-live" role="img" aria-label="Backtest on its way"><i></i><i></i><i></i></span>';
  const pct = (v) => { const r = Math.round(v ?? 0); return `${r > 0 ? "+" : ""}${r}%`; };
  const s = shownSummary(b);
  if (!s) return "bt: no entry";
  const win = s.win_rate != null ? ` · ${Math.round(s.win_rate)}% win` : "";
  return `${s.interval} ${pct(s.return_pct)} · ${s.trades} trades${win}${s.in_position ? " · long" : ""}`;
}

async function load() {
  try {
    const keys = narr.get();
    const top = await api.getTop(50, keys);
    filtered = keys.length > 0;
    // A page served before the arenas: one arena holding the old list.
    arenas = top?.arenas ?? [{ key: "all", label: "All projects", heat: 0, size: (top?.entries ?? []).length, median: 0,
      entries: (top?.entries ?? []).map((e, i) => ({ ...e, arena_rank: i + 1, in: true })) }];
    entries = top?.entries ?? [];
    labStatus = top?.backtests ?? null;
    paint();
    paintEarly(top?.early ?? []);   // the board's own early list, never narrowed by narrative
    paintPearl(top?.early ?? []);
    paintRank(entries);
  } catch {
    // Keep the last view; with none yet, the cube says the next poll retries.
    const w = root.querySelector(".top-wait");
    if (!w) return;
    w.querySelector("engn-motion").setAttribute("state", "reconnect");
    w.querySelector("p").textContent = "Reconnecting…";
  }
}

/** Until the first arenas land, the podium's place holds the ENGN cube
 * working (the motion kit's loading state), not an empty gap. */
function waiting() {
  if (root.querySelector("[data-top-podium]")) return;
  const el = document.createElement("div");
  el.className = "top-hero top-wait";
  el.dataset.topPodium = "";
  el.setAttribute("role", "status");
  el.innerHTML = '<engn-motion state="loading" decorative></engn-motion><p>Loading the arenas…</p>';
  root.insertBefore(el, root.firstChild);
}

export function mountTop() {
  root = document.getElementById("top-picks");
  if (!root) return;
  waiting();
  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-top-narr-clear]")) { narr.set([]); return; }
    if (event.target.closest("[data-top-wallet]")) { import("@onchain/sim-backtest.js").then((m) => m.openSimBacktest()); }
  });
  onHiddenChange(paint);
  // First time the arenas are on screen in this visit: now the comparison can play.
  new IntersectionObserver((seenNow) => {
    if (seenNow.some((x) => x.isIntersecting) && (!shown || stale) && arenas.length) paint();
  }).observe(root);
  document.addEventListener("visibilitychange", () => { if ((!shown || stale) && arenas.length && onScreen()) paint(); });
  narr.onChange(() => load());
  narr.coverage().then((list) => {
    labels = Object.fromEntries(list.map((n) => [n.key, n.label ?? n.key]));
    if (filtered) paint();
  });
  load();
  setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
}
