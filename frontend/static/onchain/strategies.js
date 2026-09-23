/**
 * Attivare le strategie dell'archivio (Lorenzo, Gabriele, Accumulo/
 * Distribuzione) sui token di questo wallet — non un secondo motore:
 * stessa Watchlist, stessa API, stesso trading automatico on-chain che
 * gia' sa comprare e vendere da questa sessione. Qui e' solo l'interfaccia,
 * filtrata ai soli token collegabili a QUESTA chain.
 *
 * Aggiungere un NUOVO token resta nella tab Watchlist del sito: la
 * ricerca per ticker li' risolve gia' simbolo DEX completo (BASE@chain:
 * pool) e indirizzo insieme — duplicarla qui con solo l'indirizzo del
 * token (che il picker di questo wallet da') vorrebbe dire ricostruire a
 * mano un pool che non conosciamo, con un rischio reale di sbagliarlo.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

function parseChainFromSymbol(symbol) {
  const m = /^.+@([a-z]+):.+$/.exec(symbol);
  return m ? m[1] : null;
}

export async function openStrategies() {
  const chain = state.chain;
  sheets.openSheet("Strategie", "Le stesse strategie dell'archivio, sui token di questo wallet — stesso motore, stessi tetti di rischio.");
  sheets.setMessage("Leggo la watchlist…");

  let strategies = [];
  let entries = [];
  try {
    [strategies, entries] = await Promise.all([api.getStrategies(), api.getWatchlist()]);
  } catch (error) {
    sheets.setMessage(error instanceof ApiError ? error.message : "Errore inatteso.", "is-error");
    return;
  }

  const onchainEntries = entries.filter((e) => e.base_token_address && parseChainFromSymbol(e.symbol) === chain);
  sheets.setBody(`
    <p class="swap-detail">Per aggiungere un nuovo token usa la ricerca nella tab Watchlist del sito — qui attivi solo quelli gia' presenti.</p>
    <ul id="strategies-list" class="tx-list"></ul>
  `);
  paintList(onchainEntries, strategies);
}

function paintList(entries, strategies) {
  const list = sheets.sheetBody().querySelector("#strategies-list");
  if (!list) return;
  if (!entries.length) {
    list.innerHTML = "<li>Nessun token di questa chain in watchlist ancora.</li>";
    return;
  }
  list.innerHTML = entries.map((entry) => `
    <li data-entry="${entry.id}" style="flex-direction:column;align-items:stretch;gap:6px">
      <b>${entry.symbol.split("@")[0]}</b>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${strategies.map((name) => `
          <label class="mo-radio-label" style="display:flex;align-items:center;gap:4px">
            <input type="checkbox" data-auto-trade="${entry.id}:${name}" ${entry.auto_trade?.[name] ? "checked" : ""} />
            ${name}
          </label>`).join("")}
      </div>
      <p class="swap-detail" data-entry-error="${entry.id}" hidden></p>
    </li>`).join("");

  list.querySelectorAll("[data-auto-trade]").forEach((box) => {
    box.addEventListener("change", async () => {
      const [entryId, strategyName] = box.dataset.autoTrade.split(":");
      const errorEl = list.querySelector(`[data-entry-error="${entryId}"]`);
      box.disabled = true;
      if (errorEl) errorEl.hidden = true;
      try {
        // Attivare il trading automatico presuppone anche l'alert acceso
        // per quella strategia: senza segnali non parte niente.
        await api.setWatchlistStrategy(entryId, strategyName, box.checked);
        await api.setWatchlistAutoTrade(entryId, strategyName, box.checked);
      } catch (error) {
        box.checked = !box.checked;
        if (errorEl) {
          errorEl.hidden = false;
          errorEl.classList.add("is-warn");
          errorEl.textContent = error instanceof ApiError ? error.message : "Errore inatteso.";
        }
      } finally {
        box.disabled = false;
      }
    });
  });
}
