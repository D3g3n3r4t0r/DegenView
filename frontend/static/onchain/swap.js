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
 *
 * Lorenzo: "lo swap deve essere possibile in ogni valuta o crypto possibile"
 * — non piu' solo nativo→stablecoin: entrambe le gambe sono un indirizzo
 * qualsiasi sulla chain scelta, con la coppia nativa come scorciatoia di
 * default (e' l'unica per cui il saldo e' gia' noto senza chiederlo).
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

// Il token nativo di ogni chain: e' l'unica gamba per cui questa pagina
// conosce gia' saldo e prezzo senza una chiamata in piu' — usato come
// default e come sentinella "vendo/ricevo il gas", non come limite.
const NATIVE = {
  solana: { address: "So11111111111111111111111111111111111111112", symbol: "SOL", decimals: 9 },
  robinhood: { address: "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73", symbol: "ETH", decimals: 18 },
};

// Stablecoin di destinazione predefinita — solo per compilare il campo
// "Ricevi" al primo apertura: un tocco su "Cambia token" la sostituisce
// con qualunque altro indirizzo.
const DEFAULT_OUTPUT = {
  solana: { address: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", symbol: "USDC", decimals: 6 },
  robinhood: { address: "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168", symbol: "USDG", decimals: 6, fee: 3000 },
};

const toBaseUnits = (amount, decimals) => BigInt(Math.round(amount * 10 ** decimals));
const fromBaseUnits = (amount, decimals) => Number(amount) / 10 ** decimals;

// Vendere l'intero saldo nativo lascerebbe zero per pagare la transazione
// stessa (e per Robinhood Chain anche il quote successivo). Riserva fissa e
// prudente, non una percentuale — a saldi piccoli una percentuale lascia
// troppo poco. Si applica solo quando si vende il nativo: un token qualsiasi
// non paga il gas, quindi non ha bisogno di riserva.
const GAS_RESERVE = { solana: 0.003, robinhood: 0.0008 };

let leg = { in: null, out: null };
let latestQuote = null;
let debounceTimer = null;
let tokenCache = new Map();

function availableToSell(chain) {
  const native = state.balance?.native_balance;
  if (typeof native !== "number") return null;
  const reserve = GAS_RESERVE[chain] ?? 0;
  // Arrotondato a 8 decimali: sottrarre due float da' artefatti come
  // "0.0025700000000000002" che finirebbero dritti nel campo.
  return Math.max(0, Math.round((native - reserve) * 1e8) / 1e8);
}

// Metadati di un token qualsiasi: cache per indirizzo, mai indovinati
// (i decimali arrivano da lookup on-chain reale, lato backend).
async function resolveToken(chain, address) {
  const key = `${chain}:${address.toLowerCase()}`;
  if (tokenCache.has(key)) return tokenCache.get(key);
  const info = await api.getTokenInfo(chain, address);
  const resolved = {
    address, decimals: info.decimals,
    symbol: info.symbol || `${address.slice(0, 4)}…${address.slice(-4)}`,
    priceUsd: info.price_usd,
  };
  tokenCache.set(key, resolved);
  return resolved;
}

export async function openSwap({ onExecuted } = {}) {
  const chain = state.chain;
  const native = NATIVE[chain];
  const defaultOut = DEFAULT_OUTPUT[chain];
  leg = {
    in: { ...native, priceUsd: state.balance?.native_price_usd ?? null, isNative: true },
    out: { ...defaultOut, priceUsd: null, isNative: false },
  };
  tokenCache = new Map();

  sheets.openSheet("Swap", "Scambia qualunque token su questa chain — esecuzione reale sul wallet.");

  let armed = false;
  try { armed = Boolean((await api.getRiskStatus(chain)).execution_enabled); } catch { /* resta spento */ }

  if (state.balance?.chain !== chain) {
    try { state.balance = await api.getBalance(chain); } catch { /* resta quello che c'e', o niente */ }
  }
  leg.in.priceUsd = state.balance?.native_price_usd ?? null;

  paintForm(armed);
  onExecuted && (openSwap._onExecuted = onExecuted);
  const available = availableToSell(chain);
  const amountInput = sheets.sheetBody().querySelector("#swap-amount");
  if (available != null && available > 0) { amountInput.value = available; scheduleQuote(armed); }
}

function paintForm(armed) {
  const chain = state.chain;
  sheets.setBody(`
    ${armed ? "" : `<p class="sheet-note is-warn">Esecuzione reale spenta su questo server: il preventivo funziona, l'invio no finché non viene accesa.</p>`}
    <form class="form" id="swap-form">
      <label for="swap-amount">Vendi</label>
      <div class="swap-row">
        <input id="swap-amount" name="amount" type="number" min="0" step="any" value="" required />
        <button type="button" class="swap-max" id="swap-max" ${leg.in.isNative ? "" : "hidden"}>Max</button>
        <span class="swap-unit" id="swap-in-symbol">${leg.in.symbol}</span>
      </div>
      ${leg.in.isNative && availableToSell(chain) ? `
      <div class="mo-slider-row">
        <input type="range" id="swap-pct-slider" class="mo-slider" min="0" max="100" value="0" step="1" />
        <div class="mo-slider-val-wrap">
          <input type="number" id="swap-pct-val" class="mo-slider-val-input" value="0" min="0" max="100" step="1" />
          <span class="mo-slider-unit">%</span>
        </div>
      </div>` : ""}
      <button type="button" class="swap-token-pick" id="swap-pick-in">Cambia token in vendita ↕</button>
      <p class="swap-available" id="swap-available">
        ${leg.in.isNative
          ? (availableToSell(chain) != null
              ? `Disponibile: ${availableToSell(chain).toLocaleString("it-IT", { maximumFractionDigits: 6 })} ${leg.in.symbol} (riserva ${GAS_RESERVE[chain]} per il gas)`
              : "Saldo non disponibile — inserisci una size a mano.")
          : "Token diverso dal nativo: inserisci la size a mano."}
      </p>
      <p class="swap-usd" id="swap-in-usd"></p>

      <div class="swap-arrow" aria-hidden="true">↓</div>

      <label for="swap-out">Ricevi (stimato)</label>
      <div class="swap-row is-readonly">
        <output id="swap-out">—</output>
        <span class="swap-unit" id="swap-out-symbol">${leg.out.symbol}</span>
      </div>
      <button type="button" class="swap-token-pick" id="swap-pick-out">Cambia token da ricevere ↕</button>
      <p class="swap-usd" id="swap-out-usd"></p>

      <p class="swap-detail" id="swap-detail"></p>

      <label class="swap-confirm">
        <input type="checkbox" id="swap-confirm-box" />
        <span>Confermo: denaro reale, <b id="swap-confirm-summary">—</b></span>
      </label>

      <button type="submit" class="btn-primary" id="swap-submit" disabled>Inserisci una size</button>
    </form>
    <output class="outcome" id="swap-outcome" hidden></output>
  `);

  const amountInput = sheets.sheetBody().querySelector("#swap-amount");
  const submitButton = sheets.sheetBody().querySelector("#swap-submit");
  const form = sheets.sheetBody().querySelector("#swap-form");
  const maxButton = sheets.sheetBody().querySelector("#swap-max");
  const confirmBox = sheets.sheetBody().querySelector("#swap-confirm-box");
  const pctSlider = sheets.sheetBody().querySelector("#swap-pct-slider");
  const pctVal = sheets.sheetBody().querySelector("#swap-pct-val");

  amountInput.addEventListener("input", () => { confirmBox.checked = false; scheduleQuote(armed); });
  confirmBox.addEventListener("change", () => scheduleQuote(armed));
  maxButton.addEventListener("click", () => {
    const max = availableToSell(chain);
    if (max != null) { amountInput.value = max; confirmBox.checked = false; scheduleQuote(armed); }
  });
  if (pctSlider) {
    const applyPct = (pct) => {
      const max = availableToSell(chain) ?? 0;
      amountInput.value = Math.round(max * (pct / 100) * 1e8) / 1e8;
      confirmBox.checked = false;
      scheduleQuote(armed);
    };
    pctSlider.addEventListener("input", () => { pctVal.value = pctSlider.value; applyPct(Number(pctSlider.value)); });
    pctVal.addEventListener("input", () => { pctSlider.value = pctVal.value; applyPct(Number(pctVal.value)); });
  }
  sheets.sheetBody().querySelector("#swap-pick-in").addEventListener("click", () => pickToken("in", armed));
  sheets.sheetBody().querySelector("#swap-pick-out").addEventListener("click", () => pickToken("out", armed));
  form.addEventListener("submit", (event) => { event.preventDefault(); if (confirmBox.checked) confirmAndExecute(armed); });
}

// Il picker vive in sheets.js (dialog dedicato): mai un prompt() del
// browser dentro l'app.
function pickToken(side, armed) {
  const chain = state.chain;
  sheets.openTokenPicker(chain, {
    onPick: async ({ address }) => {
      const submitButton = sheets.sheetBody().querySelector("#swap-submit");
      if (submitButton) { submitButton.disabled = true; submitButton.textContent = "Verifico il token…"; }
      try {
        const resolved = await resolveToken(chain, address);
        leg[side] = { ...resolved, isNative: false };
        paintForm(armed);
      } catch (error) {
        if (submitButton) submitButton.textContent = "Riprova";
        const detailEl = sheets.sheetBody().querySelector("#swap-detail");
        if (detailEl) {
          detailEl.textContent = error instanceof ApiError ? error.message : "Token non riconosciuto.";
          detailEl.classList.add("is-warn");
        }
      }
    },
  });
}

function scheduleQuote(armed) {
  clearTimeout(debounceTimer);
  const amountInput = sheets.sheetBody().querySelector("#swap-amount");
  debounceTimer = setTimeout(() => requestQuote(amountInput.value, armed), 350);
}

async function requestQuote(rawAmount, armed) {
  const chain = state.chain;
  const amount = Number(rawAmount);
  const outEl = sheets.sheetBody().querySelector("#swap-out");
  const detailEl = sheets.sheetBody().querySelector("#swap-detail");
  const inUsdEl = sheets.sheetBody().querySelector("#swap-in-usd");
  const outUsdEl = sheets.sheetBody().querySelector("#swap-out-usd");
  const submitButton = sheets.sheetBody().querySelector("#swap-submit");
  const confirmBox = sheets.sheetBody().querySelector("#swap-confirm-box");
  const confirmSummary = sheets.sheetBody().querySelector("#swap-confirm-summary");
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
  inUsdEl.textContent = leg.in.priceUsd != null ? `≈ ${formatUsd(amount * leg.in.priceUsd)}` : "";

  try {
    const amountIn = toBaseUnits(amount, leg.in.decimals);
    const quote = chain === "solana"
      ? await api.quoteSolana({ input_mint: leg.in.address, output_mint: leg.out.address, amount_lamports: Number(amountIn) })
      : await api.quoteRobinhood({ token_in: leg.in.address, token_out: leg.out.address, fee: leg.out.fee ?? leg.in.fee ?? 3000, amount_in: Number(amountIn) });

    latestQuote = { ...quote, amountIn, sourceAmount: amount };
    const outAmount = fromBaseUnits(quote.out_amount, leg.out.decimals);
    outEl.textContent = outAmount.toLocaleString("it-IT", { maximumFractionDigits: 6 });
    outUsdEl.textContent = leg.out.priceUsd != null
      ? `≈ ${formatUsd(outAmount * leg.out.priceUsd)}`
      : (isStable(leg.out) ? `≈ ${formatUsd(outAmount)} (stablecoin, ancorata a 1 USD)` : "");
    detailEl.textContent = `Price impact stimato ${quote.price_impact_pct.toFixed(2)}%`;
    detailEl.classList.toggle("is-warn", quote.price_impact_pct > 1);

    if (confirmSummary) {
      confirmSummary.textContent =
        `${amount} ${leg.in.symbol} → circa ${outAmount.toFixed(6)} ${leg.out.symbol}, `
        + `price impact ${quote.price_impact_pct.toFixed(2)}%`;
    }
    submitButton.disabled = !armed || !confirmBox?.checked;
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

function isStable(token) {
  return ["USDC", "USDG", "USDT"].includes(token.symbol);
}

async function confirmAndExecute(armed) {
  // La conferma e' la checkbox spuntata prima del submit (vedi paintForm):
  // mai un window.confirm() del browser dentro l'app.
  if (!latestQuote || !armed) return;
  const chain = state.chain;
  const outcome = sheets.sheetBody().querySelector("#swap-outcome");
  const submitButton = sheets.sheetBody().querySelector("#swap-submit");

  submitButton.disabled = true;
  submitButton.textContent = "Invio…";
  outcome.hidden = false;
  outcome.dataset.tone = "";
  outcome.textContent = "Firmo e invio…";

  // I tetti di rischio sono in USD: notional_usd deve essere il controvalore
  // vero, non l'importo nel token venduto — se non conosciamo il prezzo
  // (token non nativo e non tracciato da DexScreener), l'importo nel token
  // resta un fallback dichiarato (quasi certamente una sottostima, non una
  // sovrastima: mai un modo per aggirare i tetti verso l'alto).
  const notionalUsd = leg.in.priceUsd != null
    ? latestQuote.sourceAmount * leg.in.priceUsd
    : latestQuote.sourceAmount;

  try {
    const result = chain === "solana"
      ? await api.executeSolana({
          token: leg.out.symbol, strategy_name: "manuale", side: "buy",
          input_mint: leg.in.address, output_mint: leg.out.address,
          amount_lamports: Number(latestQuote.amountIn),
          notional_usd: notionalUsd, price_usd: 1,
        })
      : await api.executeRobinhood({
          token: leg.out.symbol, strategy_name: "manuale", side: "buy",
          token_in: leg.in.address, token_out: leg.out.address, fee: leg.out.fee ?? leg.in.fee ?? 3000,
          amount_in: Number(latestQuote.amountIn),
          notional_usd: notionalUsd, price_usd: 1,
        });

    outcome.dataset.tone = result.accepted ? "ok" : "no";
    outcome.textContent = result.accepted
      ? `Inviato. Firma: ${result.tx_signature}`
      : result.reason;
    if (result.accepted) openSwap._onExecuted?.();
  } catch (error) {
    outcome.dataset.tone = "no";
    outcome.textContent = error instanceof ApiError ? error.message : "Errore inatteso.";
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Firma e invia";
  }
}
