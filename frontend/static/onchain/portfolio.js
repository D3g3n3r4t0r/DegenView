/**
 * Cosa detiene DAVVERO il wallet — non solo le posizioni che questo sito
 * ha tracciato (quelle sono in "Diario"/Storico), ma i saldi reali letti
 * dalla chain. Su Solana e' completo; su Robinhood Chain e' uno scan dei
 * soli token noti a questo sito (vedi backend, balances.py) — il banner
 * "parziale" lo dice, non lo nasconde.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

export async function openPortfolio() {
  const chain = state.chain;
  sheets.openSheet("Portafoglio", "Saldi letti ora dalla chain, non dal ledger di questo sito.");
  sheets.setMessage("Leggo il portafoglio…");
  try {
    const data = await api.getPortfolio(chain);
    const totalUsd = data.holdings.reduce((sum, h) => sum + (h.value_usd ?? 0), 0);

    const rows = data.holdings.length
      ? data.holdings.map((h) => `
        <li>
          <span><b>${h.symbol}</b><small>${h.amount.toLocaleString("it-IT", { maximumFractionDigits: 6 })}</small></span>
          <span>${h.value_usd != null ? formatUsd(h.value_usd) : "prezzo non disponibile"}</span>
        </li>`).join("")
      : "<li>Nessun token diverso dal saldo nativo.</li>";

    sheets.setBody(`
      ${data.partial ? `<p class="sheet-note is-warn">Elenco parziale su questa chain: solo i token che questo sito conosce (nessun indexer pubblico affidabile su Robinhood Chain) — un token ricevuto da fuori quest'app potrebbe non comparire.</p>` : ""}
      <dl class="kv"><div><dt>Valore stimato</dt><dd>${formatUsd(totalUsd)}</dd></div></dl>
      <ul class="tx-list">${rows}</ul>
    `);
  } catch (error) {
    sheets.setMessage(error instanceof ApiError ? error.message : "Errore inatteso.", "is-error");
  }
}
