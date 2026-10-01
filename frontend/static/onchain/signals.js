/**
 * Signals: what the trend follower is doing right now on the Top 50 gems.
 *
 * Lorenzo, 30/09: the meme screens ("fired last 48h", "about to fire") are
 * gone, "non mi serve piu' [...] e' tutta roba legata alle meme coin". This
 * tab keeps the idea on the gems: the simulated Top 50 wallet's latest buys
 * and sells, what it holds now, and the Top 50 projects waiting for an
 * entry. Same trades as the wallet (/api/onchain/top/backtest), so the two
 * screens always agree; how it went lives in the wallet, not here.
 */
import * as api from "@onchain/api.js";
import { register } from "@onchain/detail.js";
import { isHidden, onHiddenChange, withEntrance } from "@onchain/hidden.js";
import { age, escapeHtml, tokenRow } from "@onchain/format.js";
import { openScan } from "@onchain/sheets.js";

const POLL_MS = 60_000;
const RECENT_S = 7 * 86400;      // a signal older than this is not news
const FRESH_S = 48 * 3600;
const WAIT_SHOWN = 5;

let root = null;
let entries = [];
let wallet = null;     // the simulated Top 50 wallet: its open and closed trades
let loaded = false;
let waitAll = false;

const pct = (v) => { const r = Math.round(v ?? 0); return `${r > 0 ? "+" : ""}${r}%`; };

// The Top row of a token, when it is still in the Top 50: logo, cap, score.
const topOf = (chain, token) => entries.find((e) => e.chain === chain && e.token_address === token);

function row(chain, token, symbol, sub, pill, sign) {
  const e = topOf(chain, token) ?? { chain, token_address: token, symbol };
  const id = `gem:${chain}:${token}`;
  register(id, { kind: "gem", symbol: e.symbol ?? symbol, name: e.name, chain, token, pair: e.pair_address,
    pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
    ageTs: e.launched_at });
  return tokenRow({ id, symbol: e.symbol ?? symbol, name: e.name || e.symbol || symbol, chain, token, image: e.image,
    cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, score: e.score, sub, pill, sign });
}

const iv = (p) => String(p.interval ?? "").toUpperCase();

function paint() {
  if (!root) return;
  const now = Date.now() / 1000;
  const vis = (p) => !isHidden(p.chain, p.token);
  // Lorenzo, 01/10: "abbiamo 14 posizioni aperte nel simulato ma qui e'
  // indicato HOLD su due". The tab reads the simulated wallet's own trades
  // (/api/onchain/top/backtest), so its positions are the wallet's: every
  // timeframe and strategy, and positions kept after a token left the Top.
  const open = (wallet?.open ?? []).filter(vis);
  const closed = (wallet?.closed ?? []).filter(vis);
  const events = [
    ...open.map((p) => ({ p, side: "buy", t: p.at })),
    ...closed.map((p) => ({ p, side: "buy", t: p.at })),
    ...closed.map((p) => ({ p, side: "sell", t: p.exit_at })),
  ].filter((x) => x.t && now - x.t <= RECENT_S).sort((x, y) => y.t - x.t);
  const held = new Set(open.map((p) => `${p.chain}:${p.token}`));
  const waiting = entries.filter((e) => !held.has(`${e.chain}:${e.token_address}`) && !isHidden(e.chain, e.token_address));
  const n48 = events.filter((x) => now - x.t <= FRESH_S).length;

  const recentRows = events.map(({ p, side, t }) => {
    const buy = side === "buy";
    const [ago, fresh] = age(t);
    const pill = `<em class="sig-pill" data-side="${buy ? "buy" : "sell"}"${fresh ? " data-fresh" : ""}>${buy ? "BUY" : "SELL"}</em>`;
    return row(p.chain, p.token, p.symbol, escapeHtml(`${iv(p)} · ${ago} ago${!buy && p.ret != null ? ` · trade ${pct(p.ret * 100)}` : ""}`),
      pill, buy ? "up" : "down");
  }).join("");
  const holdRows = [...open].sort((x, y) => (y.at ?? 0) - (x.at ?? 0)).map((p) => row(p.chain, p.token, p.symbol,
    escapeHtml(`${iv(p)} · since ${age(p.at)[0]}${p.ret != null ? ` · ${pct(p.ret * 100)}` : ""}`),
    `<em class="sig-pill" data-side="hold">HOLD</em>`, p.ret == null ? null : p.ret >= 0 ? "up" : "down")).join("");
  const waitList = waitAll ? waiting : waiting.slice(0, WAIT_SHOWN);
  const waitRows = waitList.map((e) => row(e.chain, e.token_address, e.symbol, "waiting for an entry",
    `<em class="sig-pill" data-side="flat">FLAT</em>`)).join("");

  delete root.dataset.loading;
  withEntrance(root.querySelector("[data-signals-body]"), () => {
    root.querySelector("[data-signals-body]").innerHTML = !loaded ? ""
      : !wallet ? `<p class="muted pad">Replaying the simulated wallet: signals show up here in a moment.</p>`
      : `<dl class="sig-stats">
          <div><dt>Signals</dt><dd>${n48}</dd><small>last 48h</small></div>
          <div data-v="in"><dt>In position</dt><dd>${open.length}</dd><small>in the wallet</small></div>
          <div><dt>Flat</dt><dd>${waiting.length}</dd><small>in the Top 50</small></div>
        </dl>`
        + `<h4 class="feed-sec">Latest signals</h4>`
        + (recentRows ? `<ol class="memes-list">${recentRows}</ol>` : `<p class="muted pad">No buy or sell in the last 7 days.</p>`)
        + (holdRows ? `<h4 class="feed-sec">In position</h4><ol class="memes-list">${holdRows}</ol>` : "")
        + (waitRows ? `<h4 class="feed-sec">Waiting for an entry</h4><ol class="memes-list">${waitRows}</ol>`
          + (waiting.length > WAIT_SHOWN ? `<button type="button" class="more-row" data-wait-more>${waitAll ? "Show less" : `+${waiting.length - WAIT_SHOWN} more`}</button>` : "") : "");
  });
}

async function load() {
  const [top, w] = await Promise.all([api.getTop(50).catch(() => null), api.getTopBacktest().catch(() => null)]);
  if (top) entries = top.entries ?? [];
  if (w) wallet = w;
  loaded = true;
  paint();
}

export function mountSignals() {
  root = document.getElementById("signals");
  if (!root) return;
  root.addEventListener("click", (event) => {
    if (!event.target.closest("[data-wait-more]")) return;
    waitAll = !waitAll;
    paint();
  });
  // The manual scanner lived in the meme alerts; it stays at the top here.
  root.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-scan-form]");
    if (!form) return;
    event.preventDefault();
    const q = form.q.value.trim();
    if (q) openScan(q);
  });
  onHiddenChange(paint);
  load();
  setInterval(() => document.visibilityState === "visible" && root.getClientRects().length && load(), POLL_MS);
}
