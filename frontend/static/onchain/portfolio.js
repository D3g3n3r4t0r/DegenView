/**
 * Cosa detiene DAVVERO il wallet — non solo le posizioni che questo sito
 * ha tracciato, ma i saldi reali letti dalla chain. Sempre visibile nel
 * pannello inferiore a tab ("Posizioni"), non piu' dietro un tap.
 *
 * Certezza del dato, non un numero solo: un vero exchange non nasconde
 * mai l'incertezza di un totale — se l'elenco e' parziale (Robinhood
 * Chain, senza indexer pubblico affidabile) il totale e' "≥ $X", mai un
 * numero che sembra definitivo e non lo e'.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import { state } from "@onchain/store.js";

export async function mountPortfolio(container) {
  const chain = state.chain;
  container.innerHTML = "<p class='sheet-note'>Leggo il portafoglio…</p>";
  try {
    const data = await api.getPortfolio(chain);
    const priced = data.holdings.filter((h) => h.value_usd != null);
    const unpriced = data.holdings.filter((h) => h.value_usd == null);
    const totalUsd = priced.reduce((sum, h) => sum + h.value_usd, 0);
    const totalLabel = (data.partial || unpriced.length) ? `≥ ${formatUsd(totalUsd)}` : formatUsd(totalUsd);

    const rows = data.holdings.length
      ? data.holdings.map((h) => `
        <li>
          <span><b>${h.symbol}</b><small>${h.amount.toLocaleString("it-IT", { maximumFractionDigits: 6 })}</small></span>
          <span>${h.value_usd != null ? formatUsd(h.value_usd) : "prezzo n/d"}</span>
        </li>`).join("")
      : "<li>Nessun token diverso dal saldo nativo.</li>";

    container.innerHTML = `
      ${data.partial ? `<p class="sheet-note is-warn">Elenco parziale su questa chain — solo i token che questo sito conosce (nessun indexer pubblico affidabile su Robinhood Chain): un token ricevuto da fuori quest'app potrebbe non comparire.</p>` : ""}
      ${unpriced.length ? `<p class="sheet-note is-warn">${unpriced.length} token senza prezzo noto, non contati nel totale.</p>` : ""}
      <dl class="kv"><div><dt>Valore stimato${data.partial || unpriced.length ? " (parziale)" : ""}</dt><dd>${totalLabel}</dd></div></dl>
      <ul class="tx-list">${rows}</ul>
    `;
  } catch (error) {
    container.innerHTML = `<p class="sheet-note is-error">${error instanceof ApiError ? error.message : "Errore inatteso."}</p>`;
  }
}
