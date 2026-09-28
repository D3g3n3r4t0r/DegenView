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

const POLL_MS = 30_000;
const SIZES = [15, 25, 50];

let root = null;
let size = 15;
let entries = [];

function read() { try { return Number(localStorage.getItem("lae:top")) || 15; } catch { return 15; } }
function write(n) { try { localStorage.setItem("lae:top", String(n)); } catch { /* private mode */ } }

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
  withEntrance(root.querySelector("[data-top-rows]"), () => {
  root.querySelector("[data-top-rows]").innerHTML = rows.length ? rows.map((e, i) => {
    const id = `gem:${e.chain}:${e.token_address}`;
    register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
      pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
      ageTs: e.launched_at, context: `Rank #${i + 1} · score ${Math.round(e.score ?? 0)}` });
    return tokenRow({ id, symbol: e.symbol, name: `${i + 1}. ${e.name || e.symbol}`, chain: e.chain, token: e.token_address,
      image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at,
      score: e.score, badge: e.early ? "early" : null });
  }).join("") : `<li class="muted pad">The board is filling up: projects appear as they pass the checks.</li>`;
  });
  root.querySelector("[data-top-note]").textContent = "";
}

async function load() {
  try {
    // The board first; the database fills the list to the size asked.
    const top = await api.getTop(50);
    entries = top?.entries ?? [];
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
  load();
  setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
}
