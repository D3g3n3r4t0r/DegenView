/**
 * Top: the best quality low caps, 15 / 25 / 50, live.
 *
 * Lorenzo, 27/09: "sostituirei la scheda Picks con la top 15, top 25, top
 * 50 [...] la Picks e' tutta merda meme coin, io non voglio assolutamente
 * sponsorizzare merda, voglio semmai sniperare progetti di qualita' con
 * capitalizzazioni basse". The list is the Gem Finder's board (code,
 * research with DeepSeek's voice, tokenomics; small caps), by score,
 * refreshed every POLL_MS. A tap opens the token page.
 */
import * as api from "@onchain/api.js";
import { register } from "@onchain/detail.js";
import { isHidden, onHiddenChange, withEntrance } from "@onchain/hidden.js";
import { escapeHtml, tile, tokenRow } from "@onchain/format.js";
import { renderPodium } from "@onchain/podium.js";
import * as narr from "@onchain/narrative_pick.js";
import { disintegrate } from "@onchain/particles.js";

const POLL_MS = 30_000;
const SIZES = [15, 25, 50];

let root = null;
let size = 15;
let entries = [];
let labStatus = null;
let filtered = false;   // the last load was narrowed by narrative
let labels = {};        // narrative key -> label, from the coverage

function read() { try { return Number(localStorage.getItem("lae:top")) || 15; } catch { return 15; } }
function write(n) { try { localStorage.setItem("lae:top", String(n)); } catch { /* private mode */ } }

// The order seen on the last visit (Lorenzo, 28/09: "se rientro dopo un po' e
// c'e' stato un capovolgimento [...] fai una bella animazione"): ids and symbols.
const SEEN_KEY = "lae:top-seen";
function readSeen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY)) || null; } catch { return null; } }
function writeSeen(list) { try { localStorage.setItem(SEEN_KEY, JSON.stringify(list)); } catch { /* private mode */ } }
let seen = readSeen();      // the order last shown on screen, this visit or the one before
let shown = false;
let stale = false;          // new data arrived while the Top was off screen
const idOf = (e) => `gem:${e.chain}:${e.token_address}`;
// The Top sits in a tab: painted while another tab is open, the "since your
// last visit" animation would play unseen and the new order be saved as seen
// (Lorenzo, 29/09: HATCHER first, no animation). It waits until it shows.
const onScreen = () => document.visibilityState === "visible" && root.getClientRects().length > 0;

function paint() {
  if (!root) return;
  delete root.dataset.loading;
  root.querySelector("[data-top-size]").innerHTML = SIZES.map((n) =>
    `<button type="button" data-size="${n}" aria-pressed="${n === size}">Top ${n}</button>`).join("");
  const rows = entries.filter((e) => !isHidden(e.chain, e.token_address)).slice(0, size);
  // The podium is the first three of the same ranking (Lorenzo, 27/09: "il
  // podio ha senso soltanto per le gemme"): no separate board order.
  let podium = root.querySelector("[data-top-podium]");
  if (!podium) {
    podium = document.createElement("div");
    podium.className = "top-hero";
    podium.dataset.topPodium = "";
    root.insertBefore(podium, root.firstChild);
  }
  const top3 = rows.slice(0, 3).map((e) => ({ id: `gem:${e.chain}:${e.token_address}`, symbol: e.symbol,
    value: `${Math.round(e.score ?? 0)} pts`, logoHtml: tile(e.symbol, e.image, e.chain, e.token_address) }));
  const sig = top3.map((x) => x.id).join("|");
  if (top3.length) renderPodium(podium, top3, { still: podium.dataset.sig === sig });
  else podium.innerHTML = "";
  podium.dataset.sig = sig;
  // A narrowed list is not the ranking the last visit saw: no comparison.
  // Not only on return: a change while the Top is open plays too (Lorenzo,
  // 29/09: the Telegram alert said PFWA 4th, the Top still showed Covenant).
  const visible = onScreen();
  if (!visible) stale = true;
  const prev = !filtered && seen && visible ? seen : null;
  const before = new Map((prev ?? []).map((x, i) => [x.id, i]));
  const nowIds = new Set(rows.map(idOf));
  // A newcomer takes a place: whoever held it turns to dust there, and a row
  // pushed out of the list does too (Lorenzo, 29/09: "distruzione
  // particellare del ticker che occupava quella posizione").
  const entrants = prev ? rows.map((e, i) => (before.has(idOf(e)) ? -1 : i)).filter((i) => i >= 0) : [];
  const burst = new Set();
  if (prev) {
    const old = [...root.querySelectorAll("[data-top-rows] > li.trow")];
    entrants.forEach((i) => { if (old[i]) { disintegrate(old[i]); burst.add(i); } });
    old.forEach((li, i) => {
      const id = li.querySelector("[data-open]")?.dataset.open;
      if (!burst.has(i) && id && !nowIds.has(id) && before.has(id)) disintegrate(li);
    });
  }
  if (prev) {
    // A podium place taken since the last visit: the old token leaves, the new one lands.
    top3.forEach((x, i) => {
      const was = prev[i];
      if (!was || was.id === x.id) return;
      const slot = podium.querySelectorAll(".pc-slot")[i];
      if (!slot) return;
      slot.classList.add("pc-taken");
      const out = document.createElement("span");
      out.className = "pc-prev";
      out.setAttribute("aria-hidden", "true");
      out.textContent = was.symbol ?? "";
      slot.append(out);
    });
  }
  withEntrance(root.querySelector("[data-top-rows]"), () => {
  root.querySelector("[data-top-rows]").innerHTML = rows.length ? rows.map((e, i) => {
    const id = `gem:${e.chain}:${e.token_address}`;
    register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
      pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
      ageTs: e.launched_at, context: `Rank #${i + 1} · score ${Math.round(e.score ?? 0)}` });
    return tokenRow({ id, symbol: e.symbol, name: `${i + 1}. ${e.name || e.symbol}`, chain: e.chain, token: e.token_address,
      image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at,
      score: e.score, badge: e.early ? "early" : null, sub: btSub(e.backtests) });
  }).join("") : `<li class="muted pad">The board is filling up: projects appear as they pass the checks.</li>`;
  });
  if (prev) {
    // Rows that moved since the last visit glide from their old place.
    root.querySelectorAll("[data-top-rows] > li.trow").forEach((li, i) => {
      const id = li.querySelector("[data-open]")?.dataset.open;
      if (!id) return;
      if (!before.has(id)) { li.classList.add("rank-new"); return; }
      const d = before.get(id) - i;
      if (!d) return;
      li.style.setProperty("--d", String(Math.max(-6, Math.min(6, d))));
      li.classList.add("rank-moved");
      li.dataset.move = d > 0 ? "up" : "down";
    });
  }
  if (prev) {
    // Back after a change: the old rows are gone from the page, so the one
    // that lost its place is drawn once more where it stood, then broken up.
    const list = root.querySelector("[data-top-rows]");
    const lis = list.querySelectorAll(":scope > li.trow");
    entrants.forEach((i) => {
      const was = prev[i];
      if (burst.has(i) || !was || !lis[i] || nowIds.has(was.id)) return;
      const ghost = lis[i].cloneNode(true);
      ghost.classList.remove("rank-new", "rank-moved");
      ghost.setAttribute("aria-hidden", "true");
      const r = lis[i].getBoundingClientRect();
      Object.assign(ghost.style, { position: "fixed", visibility: "hidden", top: `${r.top}px`, left: `${r.left}px`,
        width: `${r.width}px`, margin: "0" });
      const name = ghost.querySelector(".trow-main b");
      if (name) name.textContent = `${i + 1}. ${was.symbol ?? ""}`;
      ghost.querySelectorAll(".trow-main small, .trow-num b, img").forEach((x) => x.remove());
      list.append(ghost);
      disintegrate(ghost);
      ghost.remove();
    });
  }
  const lead = prev && top3[0] && prev[0] && prev[0].id !== top3[0].id
    ? `${shown ? "" : "Since your last visit: "}${top3[0].symbol} took #1 from ${prev[0].symbol}. ` : "";
  if (rows.length && !filtered && visible) {
    shown = true;
    stale = false;
    seen = entries.slice(0, 50).map((e) => ({ id: idOf(e), symbol: e.symbol }));
    writeSeen(seen);
  }
  const bt = labStatus;
  // A narrowed Top says so, with a way out right here (Lorenzo, 29/09: two
  // tokens left and no sign of the filter chosen in the Database tab).
  const narrLine = filtered
    ? `<button type="button" class="top-narr-clear" data-top-narr-clear>${escapeHtml(narr.get().map((k) => labels[k] ?? k).join(", "))} ✕</button> `
    : "";
  root.querySelector("[data-top-note]").innerHTML = narrLine + escapeHtml(lead + (bt?.total
    ? `Every strategy backtested on each token's latest chart, every hour, around the clock · ${bt.ready}/${bt.total} ready`
    : ""));
}

// The H24 lab's best backtest (strategy_lab.py), in the row: what the
// Strategies tab is for (Lorenzo, 28/09).
function btSub(b) {
  if (!b) return '<span class="bt-live" role="img" aria-label="Backtest on its way"><i></i><i></i><i></i></span>';
  if (!b.best) return "bt: no entry";
  const r = Math.round(b.best.return_pct);
  return `bt ${r > 0 ? "+" : ""}${r}%`;
}

async function load() {
  try {
    // The board first; the database fills the list to the size asked.
    const keys = narr.get();
    const top = await api.getTop(50, keys);
    filtered = keys.length > 0;
    entries = top?.entries ?? [];
    labStatus = top?.backtests ?? null;
    paint();
  } catch { /* keep the last list */ }
}

export function mountTop() {
  root = document.getElementById("top-picks");
  if (!root) return;
  size = SIZES.includes(read()) ? read() : 15;
  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-top-narr-clear]")) { narr.set([]); return; }
    const b = event.target.closest("[data-size]");
    if (!b) return;
    size = Number(b.dataset.size);
    write(size);
    paint();
  });
  onHiddenChange(paint);
  // First time the Top is on screen in this visit: now the comparison can play.
  new IntersectionObserver((seenNow) => {
    if (seenNow.some((x) => x.isIntersecting) && (!shown || stale) && entries.length) paint();
  }).observe(root);
  document.addEventListener("visibilitychange", () => { if ((!shown || stale) && entries.length && onScreen()) paint(); });
  narr.onChange(() => load());
  narr.coverage().then((list) => {
    labels = Object.fromEntries(list.map((n) => [n.key, n.label ?? n.key]));
    if (filtered) paint();
  });
  load();
  setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
}
