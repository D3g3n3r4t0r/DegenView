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

const POLL_MS = 30_000;
const MODES = [["off", "Off"], ["sim", "Simulated"], ["real", "Real"]];
let box = null;
let data = null;
let timer = null;

const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0)}%`);
const sign = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
const usdg = (v) => (v == null ? "—" : `${v.toLocaleString("en-US", { maximumFractionDigits: 2 })} USDG`);

function line(d) {
  if (!d.has_wallet) return "Create the Robinhood Chain wallet to let the system trade it.";
  if (d.mode === "off") return `Off. When on, the system (${escapeHtml(d.system)}) buys Robinhood alerts on its own entries and sells on its exits, one token at a time.`;
  if (d.mode === "sim") return "Simulated: real quotes, nothing sent. Your wallet is not touched.";
  return d.server_live ? "Real: trades your USDG on its own. Gas is paid in ETH." : "Real is on, but live execution is switched off on the server: nothing is sent yet.";
}

function position(d) {
  const p = d.position;
  if (!p) return `<p class="auto-flat">${d.mode === "off" ? "" : "Waiting for the next entry."}</p>`;
  return `<div class="auto-pos">
    ${logo(p.symbol, p.image, "robinhood", p.token)}
    <span class="trow-main"><b>${escapeHtml(p.symbol)}</b><small>in since ${age(p.at)[0]} · ${usdg(p.cost_usdg)}${p.mode === "sim" ? " · simulated" : ""}</small></span>
    <span class="trow-num"><b>${usdg(p.value_usdg)}</b><em class="chg" data-sign="${sign(p.ret)}">${pct(p.ret)}</em></span>
  </div>`;
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

function paint() {
  const d = data;
  const sim = d.sim && d.mode === "sim"
    ? `<p class="auto-sim">Simulated balance ${usdg(d.sim.equity)} <b data-sign="${sign(d.sim.ret)}">${pct(d.sim.ret)}</b> since start</p>` : "";
  box.innerHTML = `
    <header class="auto-head">
      <b>Auto-trade the system</b>
      <span class="auto-dot" data-mode="${d.mode}" aria-hidden="true"></span>
    </header>
    <div class="auto-modes" role="radiogroup" aria-label="Auto-trade mode">${MODES.map(([m, label]) =>
      `<button type="button" role="radio" data-mode="${m}" aria-checked="${d.mode === m}" ${!d.has_wallet && m !== "off" ? "disabled" : ""}>${label}</button>`).join("")}</div>
    <div class="auto-pct" role="radiogroup" aria-label="Share of the USDG balance per trade">
      <small>Per trade</small>${(d.pcts ?? [10, 25, 50, 100]).map((p) =>
        `<button type="button" role="radio" data-pct="${p}" aria-checked="${d.pct === p}">${p}%</button>`).join("")}
    </div>
    <p class="auto-line">${line(d)}</p>
    ${sim}${position(d)}${trades(d)}
    ${d.note ? `<p class="auto-note">${escapeHtml(d.note)}</p>` : ""}`;
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
    box.querySelector(".auto-line").textContent = err?.message ?? "Could not change it right now.";
  }
}

export function mountAutotrade() {
  const root = document.getElementById("meme-alerts");
  if (!root) return;
  box = document.createElement("section");
  box.className = "auto";
  box.id = "autotrade";
  root.prepend(box);
  box.addEventListener("click", (event) => {
    const m = event.target.closest("[data-mode]");
    if (m && m.tagName === "BUTTON" && m.dataset.mode !== data?.mode) {
      if (m.dataset.mode === "real" && !confirm(
        `Real money: the system will trade ${data?.pct ?? 100}% of your USDG on Robinhood Chain on its own, `
        + "with no limit other than that share. Memes can go to zero. Switch it on?")) return;
      update({ mode: m.dataset.mode });
      return;
    }
    const p = event.target.closest("[data-pct]");
    if (p) update({ pct: Number(p.dataset.pct) });
  });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
  refresh();
}
