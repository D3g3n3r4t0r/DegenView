/**
 * Track record: how the Gem Finder's picks really went.
 *
 * Lorenzo, 30/09: the backtest tab "non me ne frega piu' niente [...] la
 * visualizzo nel conto simulato". In its place, the record of the choices:
 * every pick frozen with its receipt when it entered the board, checked
 * after 1/3/7/30/90 days against the chain's own coin, plus the projects
 * studied or turned down that doubled anyway. See gem_track.record().
 */
import * as api from "@onchain/api.js";
import { register } from "@onchain/detail.js";
import { withEntrance } from "@onchain/hidden.js";
import { age, escapeHtml, tokenRow } from "@onchain/format.js";

const POLL_MS = 5 * 60_000;
const DAYS = [1, 3, 7, 30, 90];

let root = null;
let data = null;
let days = null;     // the horizon shown; null = the longest one with results

const pct = (f) => (f == null ? "—" : `${f > 0 ? "+" : ""}${Math.round(f * 100)}%`);
const share = (f) => (f == null ? "—" : `${Math.round(f * 100)}%`);
const tone = (f) => (f == null ? "" : f >= 0 ? "up" : "down");

function horizon(h) { return (data?.stats?.horizons ?? []).find((x) => x.days === h); }

function row(c, sub) {
  const id = `gem:${c.chain}:${c.token_address}`;
  register(id, { kind: "gem", symbol: c.symbol, chain: c.chain, token: c.token_address,
    context: `${c.decision === "ranked" ? `Picked${c.rank ? ` at #${c.rank}` : ""}` : c.decision === "rejected" ? "Turned down" : "Studied, not picked"} ${age(c.at)[0]} ago` });
  const ret = c.now ?? c.checkpoint?.ret;
  return tokenRow({ id, symbol: c.symbol, name: c.symbol, chain: c.chain, token: c.token_address, cap: null,
    change: ret, score: c.score, sub, ageTs: c.at });
}

function paint() {
  if (!root) return;
  delete root.dataset.loading;
  const body = root.querySelector("[data-track-body]");
  if (!data) { body.innerHTML = ""; return; }
  const ready = DAYS.filter((d) => horizon(d)?.all?.n);
  const h = days && ready.includes(days) ? days : ready[ready.length - 1];
  const H = h ? horizon(h) : null;
  const seg = `<div class="seg" role="group" aria-label="Horizon">${DAYS.map((d) => `<button type="button" data-days="${d}"
    aria-pressed="${d === h}"${ready.includes(d) ? "" : " disabled"}>${d}d</button>`).join("")}</div>`;
  const hero = !H
    ? `<p class="muted pad">The first picks reach their 1-day check soon: results land here as each window closes.</p>`
    : `<dl class="trk-hero">
        <div><dt>Median pick</dt><dd data-sign="${tone(H.all.median)}">${pct(H.all.median)}</dd><small>${H.all.n} picks · ${h}d</small></div>
        <div><dt>vs market</dt><dd data-sign="${tone(H.excess?.median)}">${pct(H.excess?.median)}</dd><small>over the chain's coin</small></div>
        <div><dt>Went up</dt><dd>${share(H.all.positive)}</dd><small>doubled ${share(H.all.doubled)}</small></div>
      </dl>
      <table class="trk-cmp"><thead><tr><th></th><th>Median</th><th>Up</th><th>n</th></tr></thead><tbody>
        ${[["Top 10", H.top], ["Picked", H.all], ["Studied", H.studied], ["Turned down", H.rejected]].map(([k, s]) => `
          <tr><th>${k}</th><td data-sign="${tone(s?.median)}">${pct(s?.median)}</td><td>${share(s?.positive)}</td><td>${s?.n ?? 0}</td></tr>`).join("")}
      </tbody></table>`;
  const picks = (data.picks ?? []).map((c) => row(c, escapeHtml(c.checkpoint?.days
    ? `${c.checkpoint.days}d ${pct(c.checkpoint.ret)}${c.checkpoint.excess != null ? ` · vs market ${pct(c.checkpoint.excess)}` : ""}`
    : `picked${c.rank ? ` #${c.rank}` : ""} · first check pending`))).join("");
  const missed = (data.missed ?? []).map((c) => row(c, escapeHtml(`${c.decision === "rejected" ? "turned down" : "not picked"} · peak ${pct(c.hi)}${c.why ? ` · ${c.why}` : ""}`))).join("");
  withEntrance(body, () => {
    body.innerHTML = `<div class="trk-head"><p class="top-info">Every pick is frozen with its receipt and checked against the market. Research, not advice.</p>${seg}</div>`
      + hero
      + `<h4 class="feed-sec">Latest picks</h4>`
      + (picks ? `<ol class="memes-list">${picks}</ol>` : `<p class="muted pad">No pick recorded yet.</p>`)
      + (missed ? `<h4 class="feed-sec">Missed</h4><ol class="memes-list">${missed}</ol>` : "");
  });
}

async function load() {
  try {
    data = await api.getTrack();
    paint();
  } catch { /* keep what is on screen */ }
}

export function mountTrack() {
  root = document.getElementById("track");
  if (!root) return;
  root.addEventListener("click", (event) => {
    const b = event.target.closest("[data-days]");
    if (!b || b.disabled) return;
    days = Number(b.dataset.days);
    paint();
  });
  load();
  setInterval(() => document.visibilityState === "visible" && root.getClientRects().length && load(), POLL_MS);
}
