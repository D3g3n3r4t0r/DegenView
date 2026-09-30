/**
 * The system trading the Robinhood wallet (backend: autotrader.py).
 *
 * Lorenzo: "con un tasto io attivo la strategia e faccio operazioni sul
 * wallet disponibile [...] uno seleziona il 100% del saldo, il 50, il 25".
 * One card on top of Memes > Alerts: Off / Simulated / Real, the share of
 * the USDG balance, the open position and the last trades. Real asks once
 * before switching on: it spends real money with no limit but the share.
 */
import * as api from "@onchain/api.js";
import { age, escapeHtml, logo, usdShort } from "@onchain/format.js";
import { openSheet, sheetBody, setBody } from "@onchain/sheets.js";
import { flash, liveKey, liveValue, priceOf, roll, watch } from "@onchain/live.js";

const POLL_MS = 30_000;
const MODES = [["off", "Off"], ["sim", "Simulated"], ["real", "Real"]];
let box = null;
let data = null;
let timer = null;

const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0)}%`);
const sign = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
// Cash is USDC (Lorenzo): on Robinhood it becomes USDG only for the trade.
const usdg = (v) => (v == null ? "—" : `${v.toLocaleString("en-US", { maximumFractionDigits: 2 })} USDC`);
const cashLine = (d) => (d.usdc
  ? `Cash in USDC (${d.usdc.slice(0, 6)}…${d.usdc.slice(-4)}), turned into USDG for each trade and back after the sale.`
  : "USDC on Robinhood Chain not found yet: trading from USDG until it is.");

function line(d) {
  if (!d.has_wallet) return "Create the Robinhood Chain wallet to let the system trade it.";
  if (d.mode === "off") return `Off. When on, the system buys Robinhood alerts on its own entries and sells on its exits, one token at a time.`;
  if (d.mode === "sim") return "Simulated: follows the trend follower on the ranked gems (5m to 1d, by how much chart each has), never memes: in on its entry, out on its exit. Nothing is sent.";
  return d.server_live ? "Real: trades your cash on its own. Gas is paid in ETH." : "Real is on, but live execution is switched off on the server: nothing is sent yet.";
}

function position(d) {
  const list = d.positions?.length ? d.positions : d.position ? [d.position] : [];
  if (!list.length) return `<p class="auto-flat">${d.mode === "off" ? "" : "Waiting for the next signal."}</p>`;
  return list.map(posRow).join("");
}

// Live marking (live.js): the same shape the profile uses.
const asPos = (p) => ({ chain: p.chain ?? "robinhood", address: p.token, value_usd: p.value_usdg, price_usd: p.price, amount: p.qty });
const openList = (d) => (d?.positions?.length ? d.positions : d?.position ? [d.position] : []);

function posRow(p) {
  const k = liveKey(asPos(p));
  return `<div class="auto-pos"${k ? ` data-live="${escapeHtml(k)}"` : ""}>
    ${logo(p.symbol, p.image, p.chain ?? "robinhood", p.token)}
    <span class="trow-main"><b>${escapeHtml(p.symbol)}</b><small>in since ${age(p.at)[0]} · ${usdg(p.cost_usdg)}${p.mode === "sim" ? " · simulated" : ""}</small></span>
    <span class="trow-num"><b data-lv>${usdg(p.value_usdg)}</b><em class="chg" data-pnl data-sign="${sign(p.ret)}">${pct(p.ret)}</em></span>
  </div>`;
}

const shownPx = new Map();
function applyLive() {
  const body = sheetBody().querySelector(".auto-full");
  if (!body || !data) return;
  const byKey = new Map(openList(data).map((p) => [liveKey(asPos(p)), p]));
  body.querySelectorAll(".auto-pos[data-live]").forEach((row) => {
    const p = byKey.get(row.dataset.live), px = priceOf(row.dataset.live);
    if (!p || !px) return;
    const v = liveValue(asPos(p));
    roll(row.querySelector("[data-lv]"), usdg(v));
    const ret = p.cost_usdg ? v / p.cost_usdg - 1 : null;
    const em = row.querySelector("[data-pnl]");
    if (em && ret != null) { em.dataset.sign = sign(ret); roll(em, pct(ret)); }
    const before = shownPx.get(row.dataset.live);
    if (before != null && before !== px) flash(row, px > before ? "up" : "down");
    shownPx.set(row.dataset.live, px);
  });
}

function trades(d) {
  const rows = (d.trades ?? []).slice(0, 6);
  if (!rows.length) return "";
  return `<ol class="auto-log">${rows.map((t) => `<li data-ok="${t.ok}">
      <b>${t.side === "buy" ? "Buy" : "Sell"} ${escapeHtml(t.symbol ?? "")}</b>
      <span>${t.ok ? (t.side === "buy" ? usdg(t.usdg) : `${usdg(t.usdg)} · ${pct(t.ret)}`) : escapeHtml(t.reason ?? "skipped")}</span>
      <small>${age(t.t)[0]} ago${t.mode === "sim" ? " · sim" : ""}${t.why ? ` · ${escapeHtml(t.why)}` : ""}</small>
    </li>`).join("")}</ol>`;
}

// Lorenzo, 28/09 (screenshot of Alerts): "UI troppo affollata, riprogettala".
// On the page: one bar with the state. Everything else opens in a sheet.
const CHIP = { off: "OFF", sim: "SIM", real: "REAL" };

function summary(d) {
  if (!d.has_wallet) return "Create the Robinhood wallet to start";
  if (d.mode === "off") return "Off · tap to switch on";
  if ((d.positions?.length ?? 0) > 1 && d.sim) return `${usdg(d.sim.equity)} ${pct(d.sim.ret)} · in ${d.positions.length} trades`;
  if (d.position) return `In ${escapeHtml(d.position.symbol)} ${pct(d.position.ret)} · ${d.pct}% per trade`;
  if (d.mode === "sim" && d.sim) return `${usdg(d.sim.equity)} ${pct(d.sim.ret)} · waiting for an entry`;
  return `${d.pct}% per trade · waiting for an entry`;
}

function full(d) {
  const sim = d.sim && d.mode === "sim"
    ? `<p class="auto-sim">Simulated balance ${usdg(d.sim.equity)} <b data-sign="${sign(d.sim.ret)}">${pct(d.sim.ret)}</b> since start</p>` : "";
  return `<div class="auto auto-full">
    <div class="auto-modes" role="radiogroup" aria-label="Auto-trade mode">${MODES.map(([m, label]) =>
      `<button type="button" role="radio" data-mode="${m}" aria-checked="${d.mode === m}" ${!d.has_wallet && m !== "off" ? "disabled" : ""}>${label}</button>`).join("")}</div>
    <div class="auto-pct" role="radiogroup" aria-label="Share of the cash per trade">
      <small>Per trade</small>${(d.pcts ?? [10, 25, 50, 100]).map((p) =>
        `<button type="button" role="radio" data-pct="${p}" aria-checked="${d.pct === p}">${p}%</button>`).join("")}
    </div>
    <p class="auto-line">${line(d)}</p>
    ${d.mode !== "off" ? `<p class="auto-line">${cashLine(d)}</p>` : ""}
    ${sim}${position(d)}${trades(d)}
    ${d.note ? `<p class="auto-note">${escapeHtml(d.note)}</p>` : ""}</div>`;
}

function paint() {
  const d = data;
  box.innerHTML = `<button type="button" class="auto-bar" data-auto-open aria-label="Auto-trade settings">
    <span class="auto-dot" data-mode="${d.mode}" aria-hidden="true"></span>
    <span class="auto-bar-main"><b>Auto-trade</b><small>${summary(d)}</small></span>
    <em class="auto-chip" data-mode="${d.mode}">${CHIP[d.mode] ?? ""}</em>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button>`;
  // The sheet, if open on these controls, follows the same data.
  if (sheetBody().querySelector(".auto-full")) { setBody(full(d)); applyLive(); }
}

function openFull() {
  openSheet("Auto-trade", "The system trades your Robinhood wallet on its own entries and exits.");
  setBody(full(data));
  applyLive();
}

async function refresh() {
  clearTimeout(timer);
  try {
    data = await api.getAutotrader();
    paint();
  } catch { /* keep what is on screen */ }
  if (document.visibilityState === "visible") timer = setTimeout(refresh, POLL_MS);
}

async function update(body) {
  try {
    data = await api.setAutotrader(body);
    paint();
  } catch (err) {
    const el = sheetBody().querySelector(".auto-line");
    if (el) el.textContent = err?.message ?? "Could not change it right now.";
  }
}

export function mountAutotrade() {
  const root = document.getElementById("meme-alerts");
  if (!root) return;
  box = document.createElement("section");
  box.className = "auto";
  box.id = "autotrade";
  root.prepend(box);
  box.addEventListener("click", (event) => { if (event.target.closest("[data-auto-open]") && data) openFull(); });
  sheetBody().addEventListener("click", (event) => {
    if (!event.target.closest(".auto-full")) return;
    const m = event.target.closest("[data-mode]");
    if (m && m.tagName === "BUTTON" && m.dataset.mode !== data?.mode) {
      if (m.dataset.mode === "real" && !confirm(
        `Real money: the system will trade ${data?.pct ?? 100}% of your cash (USDC) on Robinhood Chain on its own, `
        + "with no limit other than that share. Memes can go to zero. Switch it on?")) return;
      update({ mode: m.dataset.mode });
      return;
    }
    const p = event.target.closest("[data-pct]");
    if (p) update({ pct: Number(p.dataset.pct) });
  });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
  watch({
    keys: () => openList(data).map((p) => liveKey(asPos(p))).filter(Boolean),
    active: () => Boolean(sheetBody().querySelector(".auto-full")),
    onPrices: applyLive,
  });
  refresh();
}
