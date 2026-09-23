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

// Il token che si vende e' sempre il gas nativo di questa chain (SOL, ETH):
// vendere l'intero saldo lascerebbe zero per pagare la transazione stessa, e
// per Robinhood Chain anche il quote successivo. Riserva fissa e prudente,
// non una percentuale — a saldi piccoli una percentuale lascia troppo poco.
const GAS_RESERVE = { solana: 0.003, robinhood: 0.0008 };

let latestQuote = null;
let debounceTimer = null;

// Il saldo disponibile per lo swap: quanto ha letto la hero (state.balance,
// aggiornato da main.js ad ogni fetch) meno la riserva di gas — mai un
// valore da digitare a memoria, e mai negativo.
function availableToSell(chain) {
  const native = state.balance?.native_balance;
  if (typeof native !== "number") return null;
  const reserve = GAS_RESERVE[chain] ?? 0;
  // Arrotondato a 8 decimali: sottrarre due float ("0.00337 - 0.0008") da'
  // artefatti come "0.0025700000000000002" che finirebbero dritti nel
  // campo — 8 decimali bastano per SOL/ETH e restano sotto la precisione
  // che questa pagina mostra comunque.
  return Math.max(0, Math.round((native - reserve) * 1e8) / 1e8);
}

export async function openSwap({ onExecuted } = {}) {
  const pair = PAIRS[state.chain];
  sheets.openSheet("Swap", `${pair.inputSymbol} → ${pair.outputSymbol}, esecuzione reale sul wallet di questa chain.`);

  let armed = false;
  try { armed = Boolean((await api.getRiskStatus(state.chain)).execution_enabled); } catch { /* resta spento */ }

  // Il saldo puo' non essere ancora arrivato (la hero lo chiede in parallelo,
  // non prima): se manca, lo chiediamo qui apposta, cosi' il campo parte
  // sempre pieno invece di uno "0.01" indovinato.
  if (state.balance?.chain !== state.chain) {
    try { state.balance = await api.getBalance(state.chain); } catch { /* resta quello che c'e', o niente */ }
  }
  const available = availableToSell(state.chain);
  const startAmount = available != null && available > 0 ? available : "";

  sheets.setBody(`
    ${armed ? "" : `<p class="sheet-note is-warn">Esecuzione reale spenta su questo server: il preventivo funziona, l'invio no finché non viene accesa.</p>`}
    <form class="form" id="swap-form">
      <label for="swap-amount">Vendi</label>
      <div class="swap-row">
        <input id="swap-amount" name="amount" type="number" min="0" step="any" value="${startAmount}" required />
        <button type="button" class="swap-max" id="swap-max">Max</button>
        <span class="swap-unit">${pair.inputSymbol}</span>
      </div>
      <p class="swap-available" id="swap-available">
        ${available != null ? `Disponibile: ${available.toLocaleString("it-IT", { maximumFractionDigits: 6 })} ${pair.inputSymbol} (riserva ${GAS_RESERVE[state.chain]} per il gas)` : "Saldo non disponibile — inserisci una size a mano."}
      </p>
      <p class="swap-usd" id="swap-in-usd"></p>

      <div class="swap-arrow" aria-hidden="true">↓</div>

      <label for="swap-out">Ricevi (stimato)</label>
      <div class="swap-row is-readonly">
        <output id="swap-out">—</output>
        <span class="swap-unit">${pair.outputSymbol}</span>
      </div>
      <p class="swap-usd" id="swap-out-usd"></p>

      <p class="swap-detail" id="swap-detail"></p>
      <button type="submit" class="btn-primary" id="swap-submit" disabled>Leggo il preventivo…</button>
    </form>
    <output class="outcome" id="swap-outcome" hidden></output>
  `);

  const amountInput = sheets.sheetBody().querySelector("#swap-amount");
  const submitButton = sheets.sheetBody().querySelector("#swap-submit");
  const form = sheets.sheetBody().querySelector("#swap-form");
  const maxButton = sheets.sheetBody().querySelector("#swap-max");

  const refreshQuote = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => requestQuote(pair, amountInput.value, submitButton, armed), 350);
  };
  amountInput.addEventListener("input", refreshQuote);
  maxButton.addEventListener("click", () => {
    const max = availableToSell(state.chain);
    if (max != null) { amountInput.value = max; refreshQuote(); }
  });
  if (startAmount !== "") refreshQuote();
  else { submitButton.disabled = true; submitButton.textContent = "Inserisci una size"; }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    confirmAndExecute(pair, armed, onExecuted);
  });
}

async function requestQuote(pair, rawAmount, submitButton, armed) {
  const amount = Number(rawAmount);
  const outEl = sheets.sheetBody().querySelector("#swap-out");
  const detailEl = sheets.sheetBody().querySelector("#swap-detail");
  const inUsdEl = sheets.sheetBody().querySelector("#swap-in-usd");
  const outUsdEl = sheets.sheetBody().querySelector("#swap-out-usd");
  if (!(amount > 0)) {
    latestQuote = null;
    outEl.textContent = "—";
    detailEl.textContent = "";
    inUsdEl.textContent = "";
    outUsdEl.textContent = "";
    submitButton.disabled = true;
    submitButton.textContent = "Inserisci una size";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "Aggiorno il preventivo…";
  detailEl.textContent = "";

  // Prezzo del lato venduto: quello gia' letto dalla hero (GeckoTerminal,
  // stesso feed della pagina) — mai una seconda fonte per lo stesso numero.
  const nativePriceUsd = state.balance?.native_price_usd;
  inUsdEl.textContent = nativePriceUsd != null ? `≈ ${formatUsd(amount * nativePriceUsd)}` : "";

  try {
    const amountIn = toBaseUnits(amount, pair.inputDecimals);
    const quote = state.chain === "solana"
      ? await api.quoteSolana({ input_mint: pair.inputMint, output_mint: pair.outputMint, amount_lamports: Number(amountIn) })
      : await api.quoteRobinhood({ token_in: pair.inputMint, token_out: pair.outputMint, fee: pair.fee, amount_in: Number(amountIn) });

    latestQuote = { ...quote, amountIn, sourceAmount: amount, nativePriceUsd };
    const outAmount = fromBaseUnits(quote.out_amount, pair.outputDecimals);
    outEl.textContent = outAmount.toLocaleString("it-IT", { maximumFractionDigits: 6 });
    // USDC/USDG sono stablecoin ancorate al dollaro: e' l'ancoraggio a fare
    // da prezzo, non un secondo feed — lo dico "stimato" perche' un
    // de-peg reale (raro ma possibile) lo renderebbe falso.
    outUsdEl.textContent = `≈ ${formatUsd(outAmount)} (stablecoin, ancorata a 1 USD)`;
    detailEl.textContent = `Price impact stimato ${quote.price_impact_pct.toFixed(2)}%`;
    detailEl.classList.toggle("is-warn", quote.price_impact_pct > 1);

    submitButton.disabled = !armed;
    submitButton.textContent = armed ? "Firma e invia" : "Esecuzione spenta sul server";
  } catch (error) {
    latestQuote = null;
    outEl.textContent = "—";
    outUsdEl.textContent = "";
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

  // I tetti di rischio sono in USD: notional_usd deve essere il controvalore
  // vero, non l'importo nel token nativo — altrimenti un ordine di 0.01 SOL
  // passerebbe il tetto per-trade come se costasse "0.01 dollari" invece del
  // suo prezzo reale. Se il prezzo non e' disponibile, l'importo nativo resta
  // un fallback dichiarato (sottostima quasi certa, non una sovrastima).
  const notionalUsd = latestQuote.nativePriceUsd != null
    ? latestQuote.sourceAmount * latestQuote.nativePriceUsd
    : latestQuote.sourceAmount;

  try {
    const result = state.chain === "solana"
      ? await api.executeSolana({
          token: pair.outputSymbol, strategy_name: "manuale", side: "buy",
          input_mint: pair.inputMint, output_mint: pair.outputMint,
          amount_lamports: Number(latestQuote.amountIn),
          notional_usd: notionalUsd, price_usd: 1,
        })
      : await api.executeRobinhood({
          token: pair.outputSymbol, strategy_name: "manuale", side: "buy",
          token_in: pair.inputMint, token_out: pair.outputMint, fee: pair.fee,
          amount_in: Number(latestQuote.amountIn),
          notional_usd: notionalUsd, price_usd: 1,
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
