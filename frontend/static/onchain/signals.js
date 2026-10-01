/**
 * Signals: what the trend follower is doing right now on the Top 50 gems.
 *
 * Lorenzo, 30/09: the meme screens ("fired last 48h", "about to fire") are
 * gone, "non mi serve piu' [...] e' tutta roba legata alle meme coin". This
 * tab keeps the idea on the gems: the 8h/1d trend follower's latest buy or
 * sell on each Top 50 project, what it holds now, what waits for an entry.
 * How it went lives in the simulated account, not here. Same data as the
 * Top list (/api/onchain/top, strategy_lab's `daily`), so a row here and
 * the arrows on its chart are the same trades.
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
let loaded = false;
let waitAll = false;

const pct = (v) => { const r = Math.round(v ?? 0); return `${r > 0 ? "+" : ""}${r}%`; };
const tf = (d) => (d?.interval ?? "1d").toUpperCase();

function row(e, sub, pill, sign) {
  const id = `gem:${e.chain}:${e.token_address}`;
  register(id, { kind: "gem", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, pair: e.pair_address,
    pairUrl: e.pair_url, image: e.image, cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null,
    ageTs: e.launched_at, context: `Score ${Math.round(e.score ?? 0)} · trend follower ${tf(e.backtests?.daily)}` });
  return tokenRow({ id, symbol: e.symbol, name: e.name || e.symbol, chain: e.chain, token: e.token_address, image: e.image,
    cap: e.market_cap, change: e.change_24h != null ? e.change_24h / 100 : null, score: e.score, sub, pill, sign });
}

function paint() {
  if (!root) return;
  const now = Date.now() / 1000;
  const live = entries.filter((e) => e.backtests?.daily && !isHidden(e.chain, e.token_address));
  const sig = (e) => e.backtests.daily.signal;
  const recent = live.filter((e) => sig(e)?.t && now - sig(e).t <= RECENT_S).sort((a, b) => sig(b).t - sig(a).t);
  const shown = new Set(recent);
  const holding = live.filter((e) => e.backtests.daily.in_position && !shown.has(e));
  const waiting = live.filter((e) => !e.backtests.daily.in_position && !shown.has(e));
  const nIn = live.filter((e) => e.backtests.daily.in_position).length;
  const n48 = recent.filter((e) => now - sig(e).t <= FRESH_S).length;

  const recentRows = recent.map((e) => {
    const s = sig(e);
    const buy = s.side === "buy";
    const [ago, fresh] = age(s.t);
    const pill = `<em class="sig-pill" data-side="${buy ? "buy" : "sell"}"${fresh ? " data-fresh" : ""}>${buy ? "BUY" : "SELL"}</em>`;
    const sub = `${tf(e.backtests.daily)} · ${ago} ago${!buy && s.ret != null ? ` · trade ${pct(s.ret * 100)}` : ""}`;
    return row(e, escapeHtml(sub), pill, buy ? "up" : "down");
  }).join("");
  const holdRows = holding.map((e) => {
    const s = sig(e);
    return row(e, escapeHtml(`${tf(e.backtests.daily)}${s?.t ? ` · since ${age(s.t)[0]}` : ""}`),
      `<em class="sig-pill" data-side="hold">HOLD</em>`);
  }).join("");
  const waitList = waitAll ? waiting : waiting.slice(0, WAIT_SHOWN);
  const waitRows = waitList.map((e) => row(e, escapeHtml(`${tf(e.backtests.daily)} · waiting for the trend`),
    `<em class="sig-pill" data-side="flat">FLAT</em>`)).join("");

  delete root.dataset.loading;
  withEntrance(root.querySelector("[data-signals-body]"), () => {
    root.querySelector("[data-signals-body]").innerHTML = !loaded ? ""
      : !live.length ? `<p class="muted pad">Backtests are running on the Top 50: signals show up here as they come.</p>`
      : `<dl class="sig-stats">
          <div><dt>Signals</dt><dd>${n48}</dd><small>last 48h</small></div>
          <div data-v="in"><dt>In position</dt><dd>${nIn}</dd><small>of ${live.length}</small></div>
          <div><dt>Flat</dt><dd>${live.length - nIn}</dd><small>waiting</small></div>
        </dl>`
        + `<h4 class="feed-sec">Latest signals</h4>`
        + (recentRows ? `<ol class="memes-list">${recentRows}</ol>` : `<p class="muted pad">No buy or sell in the last 7 days.</p>`)
        + (holdRows ? `<h4 class="feed-sec">In position</h4><ol class="memes-list">${holdRows}</ol>` : "")
        + (waitRows ? `<h4 class="feed-sec">Waiting for an entry</h4><ol class="memes-list">${waitRows}</ol>`
          + (waiting.length > WAIT_SHOWN ? `<button type="button" class="more-row" data-wait-more>${waitAll ? "Show less" : `+${waiting.length - WAIT_SHOWN} more`}</button>` : "") : "");
  });
}

async function load() {
  try {
    const top = await api.getTop(50);
    entries = top?.entries ?? [];
    loaded = true;
    paint();
  } catch { /* keep what is on screen */ }
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
