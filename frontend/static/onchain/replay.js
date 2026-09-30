/**
 * The Top 50 backtest on the simulated wallet (backend: portfolio_replay.py).
 *
 * Lorenzo, 30/09: "applichi a quel portafoglio tutti gli ingressi e tutti i
 * rendimenti di tutte le gemme in top 50 per vedere come avrebbe
 * performato". Every ranked gem's trend follower trades, from the saved
 * backtests, replayed on the wallet's starting cash in time order. It is a
 * separate view: the live simulated positions stay as they are. Each trade
 * opens the token page with the strategy's arrows and the wallet's own
 * entry and exit.
 */
import * as api from "@onchain/api.js";
import { register } from "@onchain/detail.js";
import { escapeHtml, logo } from "@onchain/format.js";

const SIZES = [2, 5, 10, 25];
let size = 10;
let open = false;
let result = null;     // {key, data}
let busy = false;

const usd = (v) => `$${Number(v ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%`);
const day = (t) => (t ? new Date(t * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "now");

function line(curve) {
  if (!curve?.length || curve.length < 2) return "";
  const W = 320, H = 90;
  const ts = curve.map((p) => p[0]), vs = curve.map((p) => p[1]);
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi === lo) { hi += 1; lo -= 1; }
  const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * W;
  const y = (v) => 6 + (1 - (v - lo) / (hi - lo)) * (H - 12);
  const d = curve.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  return `<svg class="rp-line" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" data-sign="${vs[vs.length - 1] >= vs[0] ? "up" : "down"}" role="img" aria-label="Wallet value over the replay">
    <line x1="0" x2="${W}" y1="${y(vs[0])}" y2="${y(vs[0])}"/><path d="${d}"/></svg>`;
}

function row(r) {
  const id = `gem:${r.chain}:${r.token}`;
  register(id, { kind: "gem", symbol: r.symbol, chain: r.chain, token: r.token, pair: r.pair,
    own: [{ t: r.in_t, side: "buy" }, ...(r.open ? [] : [{ t: r.out_t, side: "sell", ret: r.ret }])] });
  return `<li data-open="${escapeHtml(id)}" role="button" tabindex="0">
    ${logo(r.symbol, null, r.chain, r.token)}
    <span class="pf-main"><b>${escapeHtml(r.symbol ?? "?")}</b><small>${escapeHtml(r.interval ?? "")} · ${day(r.in_t)} → ${r.open ? "open" : day(r.out_t)} · ${usd(r.stake)} in</small></span>
    <span class="pf-num"><b data-sign="${r.pnl >= 0 ? "up" : "down"}">${r.pnl >= 0 ? "+" : "−"}${usd(Math.abs(r.pnl))}</b><em data-sign="${r.ret >= 0 ? "up" : "down"}">${pct(r.ret)}</em></span>
  </li>`;
}

function body(start) {
  if (!result || result.key !== `${start}:${size}`) return `<p class="pf-none">${busy ? "Replaying the Top 50…" : ""}</p>`;
  const d = result.data;
  if (!d.closed && !d.open.length) return `<p class="pf-none">No trend follower trade on the Top 50 yet: the backtests are still running.</p>`;
  const win = d.closed ? Math.round((d.wins / d.closed) * 100) : null;
  return `<div class="rp-head">
      <p><small>From ${usd(d.start)} since ${day(d.from)}</small><b>${usd(d.final)}</b><em data-sign="${d.ret >= 0 ? "up" : "down"}">${pct(d.ret)}</em></p>
      <p class="rp-facts">${d.traded} of ${d.gems} gems traded · ${d.closed} closed${win != null ? ` · ${win}% won` : ""} · ${d.open.length} open${d.skipped ? ` · ${d.skipped} skipped, no cash left` : ""}</p>
    </div>
    ${line(d.curve)}
    <ul class="pf-list rp-list">${[...d.open, ...d.trades].map(row).join("")}</ul>`;
}

/** The section's HTML, painted inside the profile when the wallet is the simulated one. */
export function replayBox(start) {
  const cash = start && start > 0 ? start : 10_000;
  return `<details class="pf-replay" data-replay${open ? " open" : ""}>
    <summary>Top 50 backtest on ${usd(cash)}</summary>
    <p class="pf-since">Every ranked gem's trend follower trade, replayed on this wallet's start in time order, fees in. Your live positions are not touched.</p>
    <nav class="pf-seg rp-size" aria-label="Size of each entry">${SIZES.map((s) =>
      `<button type="button" data-rp-size="${s}" aria-pressed="${s === size}">${s}%</button>`).join("")}</nav>
    <div data-rp-body>${body(cash)}</div>
  </details>`;
}

async function load(root, cash) {
  const key = `${cash}:${size}`;
  if (busy || result?.key === key) return;
  busy = true;
  try {
    const data = await api.getPortfolioReplay(cash, size);
    result = { key, data };
  } catch (e) {
    const el = root.querySelector("[data-rp-body]");
    if (el) el.innerHTML = `<p class="pf-none">${escapeHtml(e?.message ?? "Couldn't replay right now.")}</p>`;
    busy = false;
    result = null;
    return;
  }
  busy = false;
  const el = root.querySelector("[data-rp-body]");
  if (el) el.innerHTML = body(cash);
}

/** Wire the section after each profile paint. */
export function bindReplay(root, start) {
  const box = root.querySelector("[data-replay]");
  if (!box) return;
  const cash = start && start > 0 ? start : 10_000;
  box.addEventListener("toggle", () => { open = box.open; if (open) load(root, cash); });
  box.addEventListener("click", (event) => {
    const b = event.target.closest("[data-rp-size]");
    if (!b) return;
    size = Number(b.dataset.rpSize);
    box.querySelectorAll("[data-rp-size]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    box.querySelector("[data-rp-body]").innerHTML = body(cash);
    load(root, cash);
  });
  if (open) load(root, cash);
}
