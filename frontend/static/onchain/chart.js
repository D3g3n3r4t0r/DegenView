/**
 * Grafico ereditato dal sito principale — stesso motore (Lightweight
 * Charts + DexScreener/GeckoTerminal), non un secondo grafico scritto da
 * zero. L'endpoint dietro (/api/onchain/chart) e' volutamente leggero:
 * niente strategia/backtest come in /api/analyze, che per aprire un
 * grafico nel wallet sarebbero solo latenza sprecata.
 *
 * Segnali sul grafico: ogni ordine (swap o limite eseguito) di questo
 * token diventa un marker sulla candela in cui e' avvenuto; un ordine
 * limite ancora aperto diventa una riga orizzontale al prezzo target —
 * stessa idea del diario, letta qui invece che come lista.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

const REFRESH_MS = 8000; // "minor delay possibile" senza un feed websocket DEX, che non esiste gratis e affidabile multi-chain

let chart = null;
let series = null;
let refreshTimer = null;
let currentToken = null;

export async function openChart({ token } = {}) {
  const chain = state.chain;
  currentToken = token ?? currentToken;

  sheets.openSheet("Grafico", "Stesso motore del sito principale — aggiorna ogni 8 secondi mentre resta aperto.");
  sheets.setBody(`
    <button type="button" class="swap-token-pick" id="chart-pick-token">
      ${currentToken ? currentToken.symbolHint || currentToken.address.slice(0, 8) : "Scegli un token"} ↕
    </button>
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
  const stop = () => { clearInterval(refreshTimer); dialog.removeEventListener("close", stop); };
  dialog.addEventListener("close", stop);
}

async function loadAndRender() {
  clearInterval(refreshTimer);
  const chain = state.chain;
  const statusEl = sheets.sheetBody().querySelector("#chart-status");
  const container = sheets.sheetBody().querySelector("#chart-container");
  if (!container) return; // la sheet e' stata chiusa mentre la richiesta era in volo

  const draw = async () => {
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
      statusEl.textContent = `${data.symbol} · aggiornato ora`;
    } catch (error) {
      statusEl.textContent = error instanceof ApiError ? error.message : "Grafico non disponibile.";
    }
  };

  await draw();
  refreshTimer = setInterval(draw, REFRESH_MS);
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
