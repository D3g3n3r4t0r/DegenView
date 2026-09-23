/**
 * Grafico ereditato dal sito principale — stesso motore (Lightweight
 * Charts + DexScreener/GeckoTerminal), non un secondo grafico scritto da
 * zero. L'endpoint delle candele (/api/onchain/chart) e' volutamente
 * leggero: niente strategia/backtest come in /api/analyze, che per un
 * grafico nel wallet sarebbero solo latenza sprecata.
 *
 * Due velocita', non una sola: le candele (storia, cambia poco) restano
 * su DexScreener/GeckoTerminal ogni 8s, ma il PREZZO CORRENTE aggiorna
 * ogni 2.5s via /api/onchain/price — lo stesso aggregatore/quoter gia'
 * usato per i preventivi di swap (Jupiter su Solana, QuoterV2 su
 * Robinhood Chain), fatto apposta per essere interrogato spesso, a
 * differenza di DexScreener che limita facilmente.
 *
 * Segnali sul grafico: ogni ordine (swap o limite eseguito) di questo
 * token diventa un marker sulla candela in cui e' avvenuto; un ordine
 * limite ancora aperto diventa una riga orizzontale al prezzo target —
 * stessa idea del diario, letta qui invece che come lista.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

const CANDLE_REFRESH_MS = 8000; // storia: DexScreener/GeckoTerminal, non fatti per un polling piu' stretto
const PRICE_REFRESH_MS = 2500;  // corrente: lo stesso quoter dello swap, pensato per un polling stretto

let chart = null;
let series = null;
let candleTimer = null;
let priceTimer = null;
let currentToken = null;

export async function openChart({ token } = {}) {
  const chain = state.chain;
  currentToken = token ?? currentToken;

  sheets.openSheet("Grafico", "Prezzo corrente ogni 2.5s, candele ogni 8s — stesso motore del sito principale.");
  sheets.setBody(`
    <button type="button" class="swap-token-pick" id="chart-pick-token">
      ${currentToken ? currentToken.symbolHint || currentToken.address.slice(0, 8) : "Scegli un token"} ↕
    </button>
    <p class="swap-detail" id="chart-live-price"></p>
    <div id="chart-container" style="inline-size:100%;block-size:320px;margin-block-start:8px"></div>
    <p class="swap-detail" id="chart-status"></p>
  `);

  sheets.sheetBody().querySelector("#chart-pick-token").addEventListener("click", () => {
    sheets.openTokenPicker(chain, {
      onPick: (token) => { currentToken = token; loadAndRender(); },
    });
  });

  if (currentToken) loadAndRender();
  else sheets.sheetBody().querySelector("#chart-status").textContent = "Scegli un token per vedere il grafico.";

  // Il dialog #sheet non notifica la chiusura ai moduli: fermare il
  // polling quando si chiude evita richieste sprecate a sheet chiusa.
  const dialog = document.querySelector("#sheet");
  const stop = () => {
    clearInterval(candleTimer); clearInterval(priceTimer);
    dialog.removeEventListener("close", stop);
  };
  dialog.addEventListener("close", stop);
}

function loadAndRender() {
  clearInterval(candleTimer);
  clearInterval(priceTimer);
  const chain = state.chain;
  const statusEl = sheets.sheetBody().querySelector("#chart-status");
  const container = sheets.sheetBody().querySelector("#chart-container");
  if (!container) return; // la sheet e' stata chiusa mentre la richiesta era in volo

  const drawCandles = async () => {
    try {
      const data = await api.getChart(chain, currentToken.address);
      if (!chart) {
        chart = LightweightCharts.createChart(container, {
          layout: { background: { color: "transparent" }, textColor: getComputedStyle(document.body).color || "#888" },
          grid: { vertLines: { visible: false }, horzLines: { visible: false } },
          timeScale: { timeVisible: true },
        });
        series = chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", borderVisible: false });
      }
      series.setData(data.candles);
      await paintMarkersAndLimits(chain, data.symbol);
      statusEl.textContent = `${data.symbol} · candele aggiornate ora`;
    } catch (error) {
      statusEl.textContent = error instanceof ApiError ? error.message : "Grafico non disponibile.";
    }
  };

  const drawLivePrice = async () => {
    const priceEl = sheets.sheetBody().querySelector("#chart-live-price");
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
        color: o.side === "buy" ? "#26a69a" : "#ef5350", shape: o.side === "buy" ? "arrowUp" : "arrowDown",
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
