/**
 * The meme lane: tokens the serious scanner rejected for meme reasons
 * (name, website, GitHub) but that are alive, sellable and clean on
 * RugCheck/GoPlus, ranked by the meme engine (flow, ticket, momentum,
 * depth, holders) with its reasons and risks on each row, and under the
 * header the lane's own track record as simulated trades. Gambling, and the
 * section says so. Read-only: the autopilot never buys these.
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";

const POLL_MS = 60_000;
const CHAIN = { solana: "Solana", robinhood: "Robinhood", ethereum: "Ethereum", base: "Base" };

let root = null;
let timer = null;

const usd = (n) => (n == null ? "—" : n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${Math.round(n / 1e3)}k` : `$${Math.round(n)}`);
// The server sends returns as fractions (0.42 = +42%).
const pct = (f) => (f == null ? "—" : `${f > 0 ? "+" : ""}${Math.round(f * 100)}%`);
const TONE = { "60+": "hot", "40-59": "warm", "under 40": "cold" };

function chips(m) {
  const good = (m.reasons ?? []).slice(0, 2).map((r) => `<li data-tone="good">${escapeHtml(r)}</li>`);
  const bad = (m.risks ?? []).slice(0, 2).map((r) => `<li data-tone="bad">${escapeHtml(r)}</li>`);
  return good.length || bad.length ? `<ul class="mm-why">${[...bad, ...good].join("")}</ul>` : "";
}

/** The lane judged on its own picks: simulated trades opened when a token
 *  was shown, next to every meme watched (the bar to beat). */
function track(t) {
  const box = root.querySelector("[data-memes-track]");
  if (!box) return;
  const r = t?.rules ?? {};
  const shown = t?.shown ?? {};
  if (!shown.n) {
    box.innerHTML = `<p class="track-note">Track record starts now: every pick shown here is followed as a $${r.size_usd ?? 100}
      trade (${pct(r.take_profit ?? 0.5)} target, ${pct(r.stop_loss ?? -0.3)} stop, ${r.max_hold_h ?? 48}h, fees and slippage paid).</p>`;
    box.hidden = false;
    return;
  }
  const base = t.baseline ?? {};
  const stat = (label, s, hint) => `<div class="track-stat"><dt>${label}</dt>
    <dd><b data-sign="${(s.median ?? 0) >= 0 ? "up" : "down"}">${pct(s.median)}</b><small>median · ${Math.round((s.win_rate ?? 0) * 100)}% hit ${pct(r.win_ret ?? 0.2)} · ${s.n} trades</small></dd>
    ${hint ? `<p>${hint}</p>` : ""}</div>`;
  const bands = (t.bands ?? []).filter((b) => b.n).map((b) =>
    `<li data-tone="${TONE[b.band] ?? ""}"><span>score ${escapeHtml(b.band)}</span><b>${pct(b.median)}</b><small>${Math.round((b.win_rate ?? 0) * 100)}% · ${b.n}</small></li>`).join("");
  box.innerHTML = `<dl class="track-grid">${stat("Picks shown here", shown)}${stat("Every meme watched", base)}</dl>
    ${bands ? `<ul class="track-bands">${bands}</ul>` : ""}
    <p class="track-note">Simulated $${r.size_usd} trades from the moment of the pick: ${pct(r.take_profit)} target, ${pct(r.stop_loss)} stop, ${r.max_hold_h}h max, DEX fee and price impact both ways. Not a promise.</p>`;
  box.hidden = false;
}

function row(m) {
  const flow = m.buys_h1 != null ? ` · ${m.buys_h1}↑ ${m.sells_h1 ?? 0}↓ 1h` : "";
  const cap = m.market_cap != null ? ` · cap ${usd(m.market_cap)}` : "";
  const chance = m.win_chance != null ? `${Math.round(m.win_chance * 100)}% odds` : "since seen";
  const href = m.pair_url || "#";
  const sc = Math.round(m.score ?? 0);
  return `
    <li><a class="meme-row" href="${escapeHtml(href)}" target="_blank" rel="noopener" data-tone="${TONE[m.band] ?? ""}">
      <span class="mm-score" style="--v:${sc}" title="Meme engine score ${sc}/100"><b>${sc}</b></span>
      <span class="mm-name"><b>${escapeHtml(m.symbol)}</b><small>${escapeHtml(CHAIN[m.chain] ?? m.chain)} · liq ${usd(m.liquidity_usd)}${cap}${flow}</small></span>
      <span class="mm-num"><b data-sign="${(m.ret_since_seen ?? 0) >= 0 ? "up" : "down"}">${pct(m.ret_since_seen)}</b><small>${escapeHtml(chance)}</small></span>
      ${chips(m)}
    </a></li>`;
}

async function refresh() {
  clearTimeout(timer);
  try {
    const data = await api.getRadarMemes();
    const items = data.items ?? [];
    delete root.dataset.loading;
    root.querySelector("[data-memes-list]").innerHTML = items.map(row).join("");
    root.querySelector("[data-memes-empty]").hidden = items.length > 0;
    root.querySelector("[data-memes-meta]").textContent = items.length ? `${items.length} on the runway` : "";
    track(data.track);
  } catch {
    // Like the radar: if the server does not answer, keep what is on screen.
  }
  if (document.visibilityState === "visible") timer = setTimeout(refresh, POLL_MS);
}

export function mountMemes() {
  root = document.getElementById("memes");
  if (!root) return;
  refresh();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
}
