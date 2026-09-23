/**
 * Punto d'ingresso della schermata wallet.
 *
 * Tiene insieme tre cose e nient'altro: la sessione, il disegno della
 * schermata per la chain scelta, e il collegamento fra i quattro pulsanti e
 * le sheet. Tutto il resto (rete, formattazione, grafico, pannelli) sta nei
 * moduli accanto.
 */
import * as api from "@onchain/api.js";
import { freshness, formatToken, formatUsd, shortAddress, usdParts } from "@onchain/format.js";
import { startReveal } from "@onchain/reveal.js";
import * as sheets from "@onchain/sheets.js";
import { drawSparkline } from "@onchain/sparkline.js";
import { appendHistory, chainInfo, readCache, readHistory, state, writeCache } from "@onchain/store.js";
import { openSwap } from "@onchain/swap.js";

// Sulla pagina a se' (onchain-app.html) la radice e' il documento intero.
// Fusa dentro la tab Trading, invece, questo modulo viene importato dentro
// un contenitore con id "onchain-embed": restringere qui la ricerca evita
// che un id del wallet (nessuno oggi collide, ma un domani sì) catturi un
// elemento omonimo del resto del sito invece del suo.
const ROOT = document.getElementById("onchain-embed") ?? document;
const $ = (selector) => ROOT.querySelector(selector);
const $$ = (selector) => ROOT.querySelectorAll(selector);

const view = {
  login: $("#login-screen"),
  shell: $("#app-shell"),
  balance: $("#balance"),
  address: $("#address"),
  chainLabel: $("#chain-label"),
  fresh: $("#fresh"),
  liveDot: $("#live-dot"),
  spark: $("#spark"),
  status: $("#status"),
  statusText: $("#status-text"),
  assets: $("#assets"),
  assetList: $("#asset-list"),
  actions: $("#actions"),
  reveal: $("#reveal-row"),
  empty: $("#onchain-empty-state"),
  toast: $("#toast"),
};

/* ------------------------------------------------------------------ chain */

function paintChainStatic() {
  const { label, unit, suffix } = chainInfo();
  const cached = readCache(state.chain);
  const wallet = state.wallets[state.chain];
  const hasWallet = Boolean(wallet || cached);

  view.chainLabel.textContent = `${label}${suffix}`;
  for (const node of [view.actions, view.status, view.reveal]) node.hidden = !hasWallet;
  view.empty.hidden = hasWallet;
  view.assets.hidden = true;
  view.balance.hidden = !hasWallet;
  view.address.hidden = !hasWallet;

  if (!hasWallet) {
    view.empty.querySelector("[data-chain-name]").textContent = label;
    view.spark.hidden = true;
    return;
  }

  const address = wallet?.address ?? cached?.address ?? "";
  view.address.textContent = shortAddress(address);
  view.address.dataset.full = address;
  view.fresh.textContent = cached ? freshness(cached.at) : "in attesa del primo saldo";
  paintBalance(cached, unit);
  drawSparkline(view.spark, readHistory(state.chain), sparkFormatter());
}

function sparkFormatter() {
  const usdMode = readCache(state.chain)?.native_usd_value != null;
  return (value) => (usdMode ? formatUsd(value) : formatToken(value));
}

function paintBalance(reading, unit) {
  if (!reading) { view.balance.textContent = "—"; return; }
  if (reading.native_usd_value != null) {
    const { currency, integer, fraction } = usdParts(reading.native_usd_value);
    view.balance.innerHTML =
      `<span class="unit-mark">${currency}</span>${integer}<span class="cents">${fraction}</span>`;
    return;
  }
  view.balance.innerHTML = `${formatToken(reading.native_balance)}<span class="cents"> ${unit}</span>`;
}

async function selectChain(next) {
  if (next === state.chain) return;
  state.chain = next;
  state.balance = null;
  // Il saldo e l'indirizzo hanno un view-transition-name: il browser li
  // interpola da una chain all'altra invece di farli sparire e riapparire.
  const swap = () => paintChainStatic();
  if (document.startViewTransition) await document.startViewTransition(swap).updateCallbackDone;
  else swap();
  loadChainData();
}

/* ------------------------------------------------------------------- dati */

function loadChainData() {
  if (view.empty.hidden === false) return;  // nessun wallet: niente da chiedere
  refreshBalance();
  refreshPositions();
  refreshStatus();
}

let balanceRetry = null;

async function refreshBalance() {
  clearTimeout(balanceRetry);
  const chain = state.chain;
  try {
    const reading = await api.getBalance(chain);
    if (chain !== state.chain) return;  // l'utente ha cambiato chain nel frattempo
    state.balance = reading;
    writeCache(chain, reading);
    paintBalance(reading, chainInfo().unit);
    view.liveDot.classList.add("is-live");
    view.fresh.textContent = "aggiornato ora";
    drawSparkline(view.spark, appendHistory(chain, reading.native_usd_value ?? reading.native_balance), sparkFormatter());
    refreshPositions();
  } catch (error) {
    if (chain !== state.chain) return;
    view.fresh.textContent = `${error.message} — riprovo`;
    balanceRetry = setTimeout(refreshBalance, 5000);
  }
}

// La lista compare solo se c'e' davvero piu' del saldo nativo: con le sole
// posizioni a zero ripeterebbe, riga per riga, il numero gia' scritto sopra.
async function refreshPositions() {
  const chain = state.chain;
  let positions = [];
  try { positions = await api.getPositions(chain); } catch { return; }
  if (chain !== state.chain) return;

  if (!positions.length) { view.assets.hidden = true; return; }

  const { unit } = chainInfo();
  const reading = state.balance ?? readCache(chain);
  const nativeValue = reading?.native_usd_value != null
    ? `<b>${formatUsd(reading.native_usd_value)}</b><small>${formatToken(reading.native_balance)} ${unit}</small>`
    : `<b>${reading ? formatToken(reading.native_balance) : "—"} ${unit}</b>`;

  view.assetList.innerHTML = `
    <li class="asset">
      <span class="asset-mark">${unit.slice(0, 1)}</span>
      <span class="asset-name"><b>${unit}</b><small>nativo · paga il gas</small></span>
      <span class="asset-value">${nativeValue}</span>
    </li>
    ${positions.map(sheets.positionRow).join("")}`;
  view.assets.hidden = false;
}

// Una riga sola, e dice la cosa che puo' cambiare: se l'esecuzione reale e'
// armata. E' lo stesso interruttore che il backend legge prima di inviare
// qualunque transazione, non un'etichetta decorativa.
async function refreshStatus() {
  const chain = state.chain;
  try {
    const risk = await api.getRiskStatus(chain);
    if (chain !== state.chain) return;
    view.status.dataset.armed = String(Boolean(risk.execution_enabled));
    view.statusText.textContent = risk.execution_enabled
      ? `Esecuzione reale attiva — fino a ${formatUsd(risk.per_trade_cap_usd)} per ordine, ${formatUsd(risk.daily_cap_usd)} al giorno.`
      : "Sola lettura — nessuna firma parte da questa pagina.";
  } catch { /* resta la riga di default, che e' quella prudente */ }
}

/* ------------------------------------------------------------------ toast */

let toastTimer = null;

function toast(title, detail) {
  clearTimeout(toastTimer);
  view.toast.querySelector(".toast-title").textContent = title;
  view.toast.querySelector(".toast-detail").textContent = detail;
  view.toast.hidden = false;
  toastTimer = setTimeout(() => { view.toast.hidden = true; }, 6000);
}

/* ---------------------------------------------------------------- comandi */

$$("[data-chain]").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$("[data-chain]").forEach((other) =>
      other.setAttribute("aria-selected", String(other === tab)));
    $("#chain-switch").dataset.selected = tab.dataset.chain;
    selectChain(tab.dataset.chain);
  });
});

view.address.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  await navigator.clipboard?.writeText(button.dataset.full ?? "");
  toast("Indirizzo copiato", shortAddress(button.dataset.full ?? ""));
});

const SHEETS = {
  receive: () => sheets.openReceive(),
  history: () => sheets.openHistory(),
  risk: () => sheets.openRisk(() => { refreshStatus(); refreshPositions(); }),
  simulate: () => sheets.openSimulate({
    onAccepted: () => { refreshPositions(); refreshStatus(); toast("Simulazione accettata", "registrata nel ledger"); },
  }),
  swap: () => openSwap({
    onExecuted: () => { refreshBalance(); refreshPositions(); toast("Swap inviato", "verifica la firma nello storico"); },
  }),
};
$$("[data-sheet]").forEach((button) =>
  button.addEventListener("click", () => SHEETS[button.dataset.sheet]?.()));

view.reveal.addEventListener("click", () => sheets.openKey({ onStart: startReveal }));

view.empty.querySelector("[data-create]").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const wallet = await api.createWallet(state.chain);
    state.wallets[state.chain] = wallet;
    paintChainStatic();
    loadChainData();
    toast("Wallet creato", shortAddress(wallet.address));
  } catch (error) {
    toast("Non creato", error.message);
  } finally {
    button.disabled = false;
  }
});

view.toast.querySelector(".toast-close").addEventListener("click", () => { view.toast.hidden = true; });

/* ---------------------------------------------------------------- sessione */

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const message = $("#login-error");
  const button = form.querySelector("button");
  button.disabled = true;
  message.hidden = true;
  try {
    const fields = new FormData(form);
    await api.login(String(fields.get("email")).trim(), String(fields.get("password")));
    await boot();
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
    button.disabled = false;
  }
});

async function boot() {
  let signedIn = false;
  try { signedIn = Boolean((await api.getSession())?.user); } catch { /* offline: si tratta come non loggato */ }

  view.login.hidden = signedIn;
  view.shell.hidden = !signedIn;
  if (!signedIn) return;

  try {
    for (const wallet of await api.listWallets()) state.wallets[wallet.chain] = wallet;
  } catch { /* al primo carico senza rete resta la cache locale, se c'e' */ }

  paintChainStatic();
  loadChainData();
}

boot();
