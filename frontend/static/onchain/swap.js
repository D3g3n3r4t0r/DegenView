/**
 * Swap dal sito — Fase 4 vera, non simulata.
 *
 * Due tempi separati anche nell'interfaccia, non solo nel backend:
 * 1. Preventivo: nessuna chiave, nessun impegno. Si aggiorna da solo mentre
 *    l'utente digita (con un debounce, non a ogni tasto).
 * 2. Conferma: solo un tocco esplicito su "Firma e invia" chiama l'ordine
 *    vero, e solo dopo aver rimostrato il prezzo appena letto — mai una
 *    firma innescata dal preventivo stesso.
 *
 * Il backend rifiuta comunque l'invio se onchain_execution_enabled e' spento
 * (di default lo e'): qui lo si dice PRIMA di far compilare il modulo,
 * non dopo un tentativo fallito.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

// Coppie native pubblicamente note per ogni chain — non e' un elenco di
// token arbitrari (che richiederebbe un modo per l'utente di specificare
// un indirizzo, fuori scope qui): sono le uniche due gambe di swap che
// questa pagina sa quotare senza chiedere altro.
const PAIRS = {
  solana: {
    inputMint: "So11111111111111111111111111111111111111112", inputSymbol: "SOL", inputDecimals: 9,
    outputMint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", outputSymbol: "USDC", outputDecimals: 6,
  },
  robinhood: {
    inputMint: "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73", inputSymbol: "ETH", inputDecimals: 18,
    outputMint: "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168", outputSymbol: "USDG", outputDecimals: 6,
    fee: 3000,
  },
};

const toBaseUnits = (amount, decimals) => BigInt(Math.round(amount * 10 ** decimals));
const fromBaseUnits = (amount, decimals) => Number(amount) / 10 ** decimals;

let latestQuote = null;
let debounceTimer = null;

export async function openSwap({ onExecuted } = {}) {
  const pair = PAIRS[state.chain];
  sheets.openSheet("Swap", `${pair.inputSymbol} → ${pair.outputSymbol}, esecuzione reale sul wallet di questa chain.`);

  let armed = false;
  try { armed = Boolean((await api.getRiskStatus(state.chain)).execution_enabled); } catch { /* resta spento */ }

  sheets.setBody(`
    ${armed ? "" : `<p class="sheet-note is-warn">Esecuzione reale spenta su questo server: il preventivo funziona, l'invio no finché non viene accesa.</p>`}
    <form class="form" id="swap-form">
      <label for="swap-amount">Vendi</label>
      <div class="swap-row">
        <input id="swap-amount" name="amount" type="number" min="0" step="any" value="0.01" required />
        <span class="swap-unit">${pair.inputSymbol}</span>
      </div>

      <div class="swap-arrow" aria-hidden="true">↓</div>

      <label for="swap-out">Ricevi (stimato)</label>
      <div class="swap-row is-readonly">
        <output id="swap-out">—</output>
        <span class="swap-unit">${pair.outputSymbol}</span>
      </div>

      <p class="swap-detail" id="swap-detail"></p>
      <button type="submit" class="btn-primary" id="swap-submit" disabled>Leggo il preventivo…</button>
    </form>
    <output class="outcome" id="swap-outcome" hidden></output>
  `);

  const amountInput = sheets.sheetBody().querySelector("#swap-amount");
  const submitButton = sheets.sheetBody().querySelector("#swap-submit");
  const form = sheets.sheetBody().querySelector("#swap-form");

  const refreshQuote = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => requestQuote(pair, amountInput.value, submitButton, armed), 350);
  };
  amountInput.addEventListener("input", refreshQuote);
  refreshQuote();

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    confirmAndExecute(pair, armed, onExecuted);
  });
}

async function requestQuote(pair, rawAmount, submitButton, armed) {
  const amount = Number(rawAmount);
  const outEl = sheets.sheetBody().querySelector("#swap-out");
  const detailEl = sheets.sheetBody().querySelector("#swap-detail");
  if (!(amount > 0)) {
    latestQuote = null;
    outEl.textContent = "—";
    detailEl.textContent = "";
    submitButton.disabled = true;
    submitButton.textContent = "Inserisci una size";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "Aggiorno il preventivo…";
  detailEl.textContent = "";

  try {
    const amountIn = toBaseUnits(amount, pair.inputDecimals);
    const quote = state.chain === "solana"
      ? await api.quoteSolana({ input_mint: pair.inputMint, output_mint: pair.outputMint, amount_lamports: Number(amountIn) })
      : await api.quoteRobinhood({ token_in: pair.inputMint, token_out: pair.outputMint, fee: pair.fee, amount_in: Number(amountIn) });

    latestQuote = { ...quote, amountIn, sourceAmount: amount };
    const outAmount = fromBaseUnits(quote.out_amount, pair.outputDecimals);
    outEl.textContent = outAmount.toLocaleString("it-IT", { maximumFractionDigits: 6 });
    detailEl.textContent = `Price impact stimato ${quote.price_impact_pct.toFixed(2)}%`;
    detailEl.classList.toggle("is-warn", quote.price_impact_pct > 1);

    submitButton.disabled = !armed;
    submitButton.textContent = armed ? "Firma e invia" : "Esecuzione spenta sul server";
  } catch (error) {
    latestQuote = null;
    outEl.textContent = "—";
    detailEl.textContent = error.message;
    detailEl.classList.add("is-warn");
    submitButton.disabled = true;
    submitButton.textContent = "Preventivo non disponibile";
  }
}

async function confirmAndExecute(pair, armed, onExecuted) {
  if (!latestQuote || !armed) return;
  const outcome = sheets.sheetBody().querySelector("#swap-outcome");
  const submitButton = sheets.sheetBody().querySelector("#swap-submit");
  const outAmount = fromBaseUnits(latestQuote.out_amount, pair.outputDecimals);

  // L'ultima parola prima di firmare, col numero appena letto — mai un invio
  // che parte senza che l'utente abbia visto QUESTO prezzo.
  const confirmed = window.confirm(
    `Confermi lo swap di ${latestQuote.sourceAmount} ${pair.inputSymbol} `
    + `per circa ${outAmount.toFixed(6)} ${pair.outputSymbol}?\n\n`
    + `Price impact stimato: ${latestQuote.price_impact_pct.toFixed(2)}%.`,
  );
  if (!confirmed) return;

  submitButton.disabled = true;
  submitButton.textContent = "Invio…";
  outcome.hidden = false;
  outcome.dataset.tone = "";
  outcome.textContent = "Firmo e invio…";

  try {
    const result = state.chain === "solana"
      ? await api.executeSolana({
          token: pair.outputSymbol, strategy_name: "manuale", side: "buy",
          input_mint: pair.inputMint, output_mint: pair.outputMint,
          amount_lamports: Number(latestQuote.amountIn),
          notional_usd: latestQuote.sourceAmount, price_usd: 1,
        })
      : await api.executeRobinhood({
          token: pair.outputSymbol, strategy_name: "manuale", side: "buy",
          token_in: pair.inputMint, token_out: pair.outputMint, fee: pair.fee,
          amount_in: Number(latestQuote.amountIn),
          notional_usd: latestQuote.sourceAmount, price_usd: 1,
        });

    outcome.dataset.tone = result.accepted ? "ok" : "no";
    outcome.textContent = result.accepted
      ? `Inviato. Firma: ${result.tx_signature}`
      : result.reason;
    if (result.accepted) onExecuted?.();
  } catch (error) {
    outcome.dataset.tone = "no";
    outcome.textContent = error instanceof ApiError ? error.message : "Errore inatteso.";
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Firma e invia";
  }
}
