/**
 * La riga "cosa hai" sotto il saldo. Lorenzo: "non e' chiaro che moneta io
 * abbia nel portafoglio [...] devo sapere subito cosa ho disponibile".
 *
 * Il nativo (paga il gas) piu' gli altri token letti dalla chain, dal piu'
 * grosso in valore. Il primo e' marcato: e' quello da cui parte lo swap.
 * Una riga sola che scorre di lato, cosi' il radar resta subito sotto.
 */
import * as api from "@onchain/api.js";
import { formatToken, formatUsd } from "@onchain/format.js";
import { chainInfo, state } from "@onchain/store.js";

const STALE_MS = 30_000;
let lastRead = { chain: null, at: 0 };

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Le monete del wallet, la piu' grande per prima. Senza prezzo finiscono in
// fondo: non si sa quanto valgono, non si puo' dire che siano le piu' grandi.
export function rankHoldings(balance, portfolio, unit) {
  const rows = [];
  if (balance && Number(balance.native_balance) > 0) {
    rows.push({ symbol: unit, amount: Number(balance.native_balance), usd: balance.native_usd_value ?? null, native: true });
  }
  for (const h of portfolio?.holdings ?? []) {
    if (!(Number(h.amount) > 0)) continue;
    rows.push({ symbol: h.symbol, amount: Number(h.amount), usd: h.value_usd ?? null, address: h.address ?? h.token_address ?? null });
  }
  return rows.sort((a, b) => (b.usd ?? -1) - (a.usd ?? -1));
}

export async function refreshHoldings(container, { force = false, onPick } = {}) {
  if (!container) return;
  const chain = state.chain;
  if (!force && lastRead.chain === chain && Date.now() - lastRead.at < STALE_MS) return;
  lastRead = { chain, at: Date.now() };
  try {
    const [balance, portfolio] = await Promise.all([
      state.balance ? Promise.resolve(state.balance) : api.getBalance(chain).catch(() => null),
      api.getPortfolio(chain).catch(() => null),
    ]);
    if (chain !== state.chain) return;
    const rows = rankHoldings(balance, portfolio, chainInfo().unit);
    container.hidden = false;
    if (!rows.length) {
      container.innerHTML = `<span class="hold-empty">Wallet vuoto · tocca l'indirizzo in alto per ricevere</span>`;
      return;
    }
    container.innerHTML = rows.map((r, i) => `
      <button type="button" class="hold${i === 0 ? " is-top" : ""}" data-i="${i}"
        title="${i === 0 ? "La moneta piu' grande: lo swap parte da qui" : "Scambia"}">
        <b>${escapeHtml(r.symbol)}</b><span>${formatToken(r.amount)}</span>${r.usd != null ? `<small>${formatUsd(r.usd)}</small>` : ""}
      </button>`).join("");
    container.onclick = (event) => {
      const chip = event.target.closest(".hold");
      if (chip) onPick?.(rows[Number(chip.dataset.i)]);
    };
  } catch {
    lastRead.at = 0;
  }
}
