/**
 * Ordini limite e diario — la parte "operativa tipo DEX" del piano.
 *
 * Non un secondo motore: l'interazione eredita l'"Ordine manuale" del
 * resto del sito (tab BUY/SELL, conferma esplicita prima di firmare), ma
 * chi esegue resta lo stesso execute_order on-chain di sempre, con gli
 * stessi guardrail — vedi limit_order_loop in main.py.
 *
 * Ne' Jupiter ne' Uniswap v3 hanno un book con ordini limite resting: qui
 * un ordine e' size+prezzo+direzione persistiti, controllati a intervalli
 * (oggi ogni 45s) — un target toccato per un istante fra due controlli
 * puo' non essere colto. Lo si dice in chiaro nel form, non lo si nasconde.
 */
import * as api from "@onchain/api.js";
import { ApiError } from "@onchain/api.js";
import { formatUsd } from "@onchain/format.js";
import * as sheets from "@onchain/sheets.js";
import { state } from "@onchain/store.js";

const NATIVE = {
  solana: { address: "So11111111111111111111111111111111111111112", symbol: "SOL", decimals: 9 },
  robinhood: { address: "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73", symbol: "ETH", decimals: 18 },
};

const STATUS_LABEL = {
  open: "In attesa", filled: "Eseguito", cancelled: "Annullato", failed: "Falso",
};

let otherToken = null; // { address, symbol, decimals } — l'altra gamba, sempre risolta via prompt

export async function openLimitOrder({ onPlaced } = {}) {
  const chain = state.chain;
  const native = NATIVE[chain];
  otherToken = otherToken ?? null;

  sheets.openSheet("Ordine limite", "Controllato ogni 45 secondi, non istantaneo al tocco del prezzo. Stessi tetti di rischio di un ordine reale.");
  paintForm(chain, native);
  await refreshOpenOrders(chain);
  openLimitOrder._onPlaced = onPlaced;
}

function paintForm(chain, native) {
  sheets.setBody(`
    <div class="mo-side-tabs" id="limit-direction-tabs">
      <button type="button" class="mo-side-tab mo-buy-tab mo-tab-active" data-direction="buy_below">Compra se scende</button>
      <button type="button" class="mo-side-tab mo-sell-tab" data-direction="sell_above">Vendi se sale</button>
    </div>

    <form class="form" id="limit-form">
      <label for="limit-other-token">Contro</label>
      <button type="button" class="swap-token-pick" id="limit-pick-other">
        ${otherToken ? otherToken.symbol : "Scegli il token"} ↕
      </button>

      <div class="form-pair">
        <span><label for="limit-amount">Size (${native.symbol})</label>
          <input id="limit-amount" name="amount" type="number" min="0" step="any" required /></span>
        <span><label for="limit-target">Prezzo target (USD)</label>
          <input id="limit-target" name="target" type="number" min="0" step="any" required /></span>
      </div>

      <button type="submit" class="btn-primary" id="limit-submit">Piazza ordine limite</button>
    </form>
    <output class="outcome" id="limit-outcome" hidden></output>

    <p class="label" style="margin-block-start:18px">Ordini aperti</p>
    <ul id="limit-open-list" class="tx-list"><li>Leggo…</li></ul>
  `);

  sheets.sheetBody().querySelectorAll("#limit-direction-tabs .mo-side-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      sheets.sheetBody().querySelectorAll("#limit-direction-tabs .mo-side-tab")
        .forEach((t) => t.classList.toggle("mo-tab-active", t === tab));
    });
  });

  sheets.sheetBody().querySelector("#limit-pick-other").addEventListener("click", () => {
    sheets.openTokenPicker(chain, {
      onPick: async ({ address }) => {
        try {
          const info = await api.getTokenInfo(chain, address);
          otherToken = { address, symbol: info.symbol || `${address.slice(0, 4)}…${address.slice(-4)}`, decimals: info.decimals };
          paintForm(chain, native);
          await refreshOpenOrders(chain);
        } catch (error) {
          sheets.setMessage(error instanceof ApiError ? error.message : "Token non riconosciuto.", "is-error");
        }
      },
    });
  });

  sheets.sheetBody().querySelector("#limit-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitOrder(chain, native);
  });
}

async function submitOrder(chain, native) {
  const outcome = sheets.sheetBody().querySelector("#limit-outcome");
  const submitButton = sheets.sheetBody().querySelector("#limit-submit");
  if (!otherToken) {
    outcome.hidden = false;
    outcome.dataset.tone = "no";
    outcome.textContent = "Scegli prima il token.";
    return;
  }

  const direction = sheets.sheetBody().querySelector("#limit-direction-tabs .mo-tab-active").dataset.direction;
  const amount = Number(sheets.sheetBody().querySelector("#limit-amount").value);
  const target = Number(sheets.sheetBody().querySelector("#limit-target").value);
  if (!(amount > 0) || !(target > 0)) return;

  // "Compra se scende" vende il nativo per l'altro token (si spera che
  // valga di piu' quando il target e' toccato); "Vendi se sale" vende
  // l'altro token per il nativo — stessa gamba nativa richiesta dal
  // backend, solo il lato in vendita cambia.
  const tokenIn = direction === "buy_below" ? native : otherToken;
  const tokenOut = direction === "buy_below" ? otherToken : native;

  submitButton.disabled = true;
  outcome.hidden = false;
  outcome.dataset.tone = "";
  outcome.textContent = "Piazzo l'ordine…";

  try {
    await api.createLimitOrder({
      chain, token_in: tokenIn.address, token_out: tokenOut.address,
      token_in_symbol: tokenIn.symbol, token_out_symbol: tokenOut.symbol,
      token_in_decimals: tokenIn.decimals, token_out_decimals: tokenOut.decimals,
      amount_in: amount, direction, target_price_usd: target,
    });
    outcome.dataset.tone = "ok";
    outcome.textContent = "Ordine piazzato — resta in attesa finche' il prezzo non tocca il target.";
    sheets.sheetBody().querySelector("#limit-form").reset();
    await refreshOpenOrders(chain);
    openLimitOrder._onPlaced?.();
  } catch (error) {
    outcome.dataset.tone = "no";
    outcome.textContent = error instanceof ApiError ? error.message : "Errore inatteso.";
  } finally {
    submitButton.disabled = false;
  }
}

async function refreshOpenOrders(chain) {
  const list = sheets.sheetBody().querySelector("#limit-open-list");
  if (!list) return;
  try {
    const orders = (await api.listLimitOrders(chain)).filter((o) => o.status === "open");
    if (!orders.length) { list.innerHTML = "<li>Nessun ordine limite aperto.</li>"; return; }
    list.innerHTML = orders.map((o) => `
      <li data-id="${o.id}">
        <span><span class="status-dot" data-status="${o.status}"></span>${o.direction === "buy_below" ? "Compra se scende a" : "Vendi se sale a"} ${formatUsd(o.target_price_usd)}
          <small>${o.amount_in} ${o.token_in_symbol} → ${o.token_out_symbol}</small></span>
        <button type="button" class="btn-quiet" data-cancel="${o.id}">Annulla</button>
      </li>`).join("");
    list.querySelectorAll("[data-cancel]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await api.cancelLimitOrder(button.dataset.cancel); await refreshOpenOrders(chain); }
        catch { button.disabled = false; }
      });
    });
  } catch (error) {
    list.innerHTML = `<li>${error.message}</li>`;
  }
}

/* ------------------------------------------------------------- Diario --- */

// Un pannello solo, non tre: "Storico" (transazioni RPC grezze) e
// "Diario" (ordini di questo sito) sembravano fare la stessa cosa da due
// bottoni diversi — Lorenzo: "una copia delle transazioni per capire cosa
// e' accaduto in passato". Due viste dentro lo stesso pannello, non due
// pannelli.
export async function openOrderDiary() {
  const chain = state.chain;
  sheets.openSheet("Storico", "Ordini di questo sito e transazioni grezze del wallet.");
  sheets.setBody(`
    <div class="mo-side-tabs" id="diary-tabs">
      <button type="button" class="mo-side-tab mo-buy-tab mo-tab-active" data-view="orders">Ordini</button>
      <button type="button" class="mo-side-tab mo-sell-tab" data-view="raw">Transazioni on-chain</button>
    </div>
    <div id="diary-body"><p class="sheet-note">Leggo…</p></div>
  `);
  sheets.sheetBody().querySelectorAll("#diary-tabs .mo-side-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      sheets.sheetBody().querySelectorAll("#diary-tabs .mo-side-tab").forEach((t) => t.classList.toggle("mo-tab-active", t === tab));
      renderDiaryView(chain, tab.dataset.view);
    });
  });
  await renderDiaryView(chain, "orders");
}

async function renderDiaryView(chain, view) {
  const host = sheets.sheetBody().querySelector("#diary-body");
  if (!host) return;
  host.innerHTML = `<p class="sheet-note">Leggo…</p>`;

  if (view === "raw") {
    try {
      const data = await api.getTransactions(chain);
      if (!data.available) {
        host.innerHTML = `<p class="sheet-note">${data.reason}
          <a href="${encodeURI(data.explorer_url)}" target="_blank" rel="noopener">Apri l'explorer →</a></p>`;
        return;
      }
      if (!data.transactions.length) { host.innerHTML = "<p class='sheet-note'>Nessuna transazione ancora.</p>"; return; }
      host.innerHTML = `<ul class="tx-list">${data.transactions.map((tx) => `
        <li>
          <a href="${encodeURI(tx.explorer_url)}" target="_blank" rel="noopener">${tx.signature.slice(0, 12)}…</a>
          <span>${tx.status}${tx.block_time ? ` · ${new Date(tx.block_time * 1000).toLocaleString("it-IT")}` : ""}</span>
        </li>`).join("")}</ul>`;
    } catch (error) {
      host.innerHTML = `<p class="sheet-note is-error">${error.message}</p>`;
    }
    return;
  }

  try {
    const data = await api.getHistory(chain);
    const rows = [
      ...data.orders.map((o) => ({ ...o, at: o.updated_at })),
      ...data.limit_orders.map((o) => ({ ...o, at: o.updated_at })),
    ].sort((a, b) => b.at - a.at);

    if (!rows.length) { host.innerHTML = "<p class='sheet-note'>Nessun ordine ancora.</p>"; return; }

    host.innerHTML = `<ul class="tx-list">${rows.map((row) => row.kind === "swap" ? `
      <li>
        <span><span class="status-dot" data-status="${row.status}"></span><b>${row.side === "buy" ? "Compra" : "Vendi"} ${row.token}</b>
          <small>${formatUsd(row.size_usd)} · ${STATUS_LABEL[row.status] ?? row.status}${row.reason ? ` — ${row.reason}` : ""}</small></span>
        <span>${new Date(row.at * 1000).toLocaleString("it-IT")}</span>
      </li>` : `
      <li>
        <span><span class="status-dot" data-status="${row.status}"></span><b>Limite ${row.pair}</b>
          <small>${row.direction === "buy_below" ? "compra se scende a" : "vendi se sale a"} ${formatUsd(row.target_price_usd)}
          · ${STATUS_LABEL[row.status] ?? row.status}${row.reason ? ` — ${row.reason}` : ""}</small></span>
        <span>${new Date(row.at * 1000).toLocaleString("it-IT")}</span>
      </li>`).join("")}</ul>`;
  } catch (error) {
    host.innerHTML = `<p class="sheet-note is-error">${error.message}</p>`;
  }
}
