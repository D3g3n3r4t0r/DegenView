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
let seen = readSeen();      // what this visit started from; replaced once shown
let shown = false;
const idOf = (e) => `gem:${e.chain}:${e.token_address}`;

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
  const prev = !filtered && !shown && seen ? seen : null;
  const before = new Map((prev ?? []).map((x, i) => [x.id, i]));
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
  const lead = prev && top3[0] && prev[0] && prev[0].id !== top3[0].id
    ? `Since your last visit: ${top3[0].symbol} took #1 from ${prev[0].symbol}. ` : "";
  if (rows.length && !filtered) {
    shown = true;
    writeSeen(entries.slice(0, 50).map((e) => ({ id: idOf(e), symbol: e.symbol })));
  }
  const bt = labStatus;
  const narrLine = filtered ? `Narratives: ${narr.get().map((k) => labels[k] ?? k).join(", ")} · ` : "";
  root.querySelector("[data-top-note]").textContent = narrLine + lead + (bt?.total
    ? `Every strategy backtested on each token's latest chart, every hour, around the clock · ${bt.ready}/${bt.total} ready`
    : "");
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
    const b = event.target.closest("[data-size]");
    if (!b) return;
    size = Number(b.dataset.size);
    write(size);
    paint();
  });
  onHiddenChange(paint);
  narr.onChange(() => load());
  narr.coverage().then((list) => {
    labels = Object.fromEntries(list.map((n) => [n.key, n.label ?? n.key]));
    if (filtered) paint();
  });
  load();
  setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
}
