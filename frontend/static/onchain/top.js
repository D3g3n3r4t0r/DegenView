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
import { tokenRow } from "@onchain/format.js";

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
  const rows = entries.slice(0, size);
  root.querySelector("[data-top-rows]").innerHTML = rows.length ? rows.map((e, i) => {
    const id = `gem:${e.chain}:${e.token_address}`;
    register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
      pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
      ageTs: e.launched_at, context: `Rank #${i + 1} · score ${Math.round(e.score ?? 0)}` });
    return tokenRow({ id, symbol: e.symbol, name: `${i + 1}. ${e.name || e.symbol}`, chain: e.chain, token: e.token_address,
      image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, ageTs: e.launched_at,
      score: e.score, badge: e.early ? "early" : null });
  }).join("") : `<li class="muted pad">The board is filling up: projects appear as they pass the checks.</li>`;
}

async function load() {
  try {
    const board = await api.getLeaderboard();
    entries = [...(board?.entries ?? [])].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
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
  load();
  setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
}
