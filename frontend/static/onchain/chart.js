/**
 * Grafico ereditato dal sito principale — stesso motore (Lightweight
 * Charts + DexScreener/GeckoTerminal), non un secondo grafico scritto da
 * zero. L'endpoint delle candele (/api/onchain/chart) e' volutamente
 * leggero: niente strategia/backtest come in /api/analyze, che per un
 * grafico nel wallet sarebbero solo latenza sprecata.
 *
 * SEMPRE VISIBILE, non piu' dentro una sheet: la revisione "deve essere
 * come un exchange" (Lorenzo) e' arrivata anche a un team di esperti
 * consultato in questa sessione — nessun exchange nasconde il grafico
 * dietro un tap, e' la prima cosa che si vede.
 *
 * Due velocita', non una sola: le candele (storia, cambia poco) restano
 * su DexScreener/GeckoTerminal ogni 8s, ma il PREZZO CORRENTE aggiorna
 * ogni 2.5s via /api/onchain/price — lo stesso aggregatore/quoter gia'
 * usato per i preventivi di swap (Jupiter su Solana, QuoterV2 su
 * Robinhood Chain), fatto apposta per essere interrogato spesso.
 *
 * Segnali sul grafico: ogni ordine (swap o limite eseguito) di questo
 * token diventa un marker sulla candela in cui e' avvenuto; un ordine
 * limite ancora aperto diventa una riga orizzontale al prezzo target.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

const CANDLE_REFRESH_MS = 8000; // storia: DexScreener/GeckoTerminal, non fatti per un polling piu' stretto
const PRICE_REFRESH_MS = 2500;  // corrente: lo stesso quoter dello swap, pensato per un polling stretto

let root = null;
let chart = null;
let series = null;
let candleTimer = null;
let priceTimer = null;
let currentToken = null;

// Chi altro deve sapere quale token sta guardando il grafico — il
// pannello ordine (swap/limite), per compilarsi da solo con la stessa
// coppia invece di farla scegliere due volte.
const listeners = new Set();
export const onTokenChanged = (fn) => listeners.add(fn);

export function getCurrentToken() {
  return currentToken;
}

export function mountChart(container) {
  root = container;
  paintShell();
  if (currentToken) loadAndRender();
  else setStatus("Scegli un token per vedere il grafico e fare uno swap.");
}

function paintShell() {
  root.innerHTML = `
    <button type="button" class="swap-token-pick" id="market-pick-token">
      ${currentToken ? currentToken.symbolHint || shortAddr(currentToken.address) : "Scegli un token"} ↕
    </button>
    <p class="swap-detail" id="market-live-price"></p>
    <div id="market-chart-container" class="market-chart"></div>
    <p class="swap-detail" id="market-status"></p>
  `;
  root.querySelector("#market-pick-token").addEventListener("click", () => {
    sheets.openTokenPicker(state.chain, {
      onPick: (token) => {
        currentToken = token;
        listeners.forEach((fn) => fn(token));
        paintShell();
        loadAndRender();
      },
    });
  });
}

function shortAddr(address) {
  return `${address.slice(0, 4)}…${address.slice(-4)}`;
}

function setStatus(text) {
  const el = root?.querySelector("#market-status");
  if (el) el.textContent = text;
}

// Cambiare chain (Solana/Robinhood) invalida il token in vista: il
// grafico non deve mostrare una candela che non appartiene piu' alla
// chain selezionata.
export function resetForChainSwitch() {
  clearInterval(candleTimer);
  clearInterval(priceTimer);
  chart = null;
  series = null;
  currentToken = null;
  if (root) { paintShell(); setStatus("Scegli un token per vedere il grafico e fare uno swap."); }
}

function loadAndRender() {
  clearInterval(candleTimer);
  clearInterval(priceTimer);
  if (!root) return;
  const chain = state.chain;
  const container = root.querySelector("#market-chart-container");
  if (!container) return;

  const drawCandles = async () => {
    try {
      const data = await api.getChart(chain, currentToken.address);
      if (!chart) {
        chart = LightweightCharts.createChart(container, {
          layout: { background: { color: "transparent" }, textColor: getComputedStyle(document.body).color || "#888" },
          grid: { vertLines: { visible: false }, horzLines: { visible: false } },
          timeScale: { timeVisible: true },
        });
        series = chart.addCandlestickSeries({ upColor: "var(--up)", downColor: "var(--down)", borderVisible: false });
      }
      series.setData(data.candles);
      await paintMarkersAndLimits(chain, data.symbol);
      setStatus(`${data.symbol} · candele aggiornate ora`);
    } catch (error) {
      setStatus(error instanceof ApiError ? error.message : "Grafico non disponibile.");
    }
  };

  const drawLivePrice = async () => {
    const priceEl = root.querySelector("#market-live-price");
    if (!priceEl) return;
    try {
      const { price_usd } = await api.getLivePrice(chain, currentToken.address);
      priceEl.textContent = `Prezzo corrente: ${formatUsd(price_usd)}`;
      priceEl.classList.remove("is-warn");
    } catch (error) {
      priceEl.textContent = error instanceof ApiError ? error.message : "Prezzo corrente non disponibile.";
      priceEl.classList.add("is-warn");
    }
  };

  drawCandles();
  drawLivePrice();
  candleTimer = setInterval(drawCandles, CANDLE_REFRESH_MS);
  priceTimer = setInterval(drawLivePrice, PRICE_REFRESH_MS);
}

async function paintMarkersAndLimits(chain, symbol) {
  if (!series) return;
  try {
    const [history, openOrders] = await Promise.all([
      api.getHistory(chain),
      api.listLimitOrders(chain),
    ]);
    const tokenSymbol = symbol.split("@")[0];

    const markers = history.orders
      .filter((o) => o.status === "confirmed" && o.token === tokenSymbol)
      .map((o) => ({
        time: o.updated_at, position: o.side === "buy" ? "belowBar" : "aboveBar",
        color: o.side === "buy" ? "var(--up)" : "var(--down)", shape: o.side === "buy" ? "arrowUp" : "arrowDown",
        text: o.side === "buy" ? "Compra" : "Vendi",
      }))
      .sort((a, b) => a.time - b.time);
    series.setMarkers(markers);

    series.createPriceLine && openOrders
      .filter((o) => o.status === "open" && (o.pair.startsWith(`${tokenSymbol}→`) || o.pair.endsWith(`→${tokenSymbol}`)))
      .forEach((o) => {
        series.createPriceLine({
          price: o.target_price_usd, color: "#f0b90b", lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: o.direction === "buy_below" ? "limite compra" : "limite vendi",
        });
      });
  } catch { /* i marker/target sono un di piu': un grafico senza di loro resta comunque utile */ }
}
