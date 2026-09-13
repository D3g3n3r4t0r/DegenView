// Diagnosi — sezione isolata apposta, come chiesto esplicitamente: test di
// collegamento a un exchange (spot o futures), saldo/margine mostrato prima
// di fidarsi delle chiavi, e un ordine di prova minimo. Nessuna dipendenza
// da app.js oltre a leggere lo stato di login gia' esposto sul DOM — se
// qualcosa qui dentro si rompe, la riparazione resta in questo file solo.
// Endpoint backend: POST /api/diagnostics/test-connection (backend/app/
// diagnostics.py, isolato per lo stesso motivo) + gli endpoint di ordine
// manuale gia' esistenti e in uso altrove (/api/trading/order).
(function () {
  "use strict";

  const root = document.getElementById("diagnosi-root");
  const navBtn = document.getElementById("sidenav-diagnosi");
  if (!root || !navBtn) return;

  const SPOT_EXCHANGES = [
    { id: "mexc", name: "MEXC" },
    { id: "binance", name: "Binance" },
    { id: "kucoin", name: "KuCoin", needsPassphrase: true },
    { id: "kraken", name: "Kraken" },
    { id: "coinbase", name: "Coinbase" },
    { id: "bitstamp", name: "Bitstamp" },
  ];

  const state = {
    open: false,
    market: "spot", // "spot" | "futures"
    exchange: "mexc",
    futuresExchanges: null, // caricato da /api/auth/futures al primo uso
  };

  async function api(path, opts) {
    const resp = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
    if (resp.status === 401) {
      const err = new Error("Devi accedere per usare la Diagnosi.");
      err.needsAuth = true;
      throw err;
    }
    let body = null;
    try { body = await resp.json(); } catch (_e) { /* nessun corpo */ }
    if (!resp.ok) throw new Error((body && body.detail) ? body.detail : `Errore ${resp.status}`);
    return body;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function ensureFuturesExchanges() {
    if (state.futuresExchanges) return state.futuresExchanges;
    try {
      state.futuresExchanges = await api("/api/auth/futures");
    } catch (_e) {
      state.futuresExchanges = [];
    }
    return state.futuresExchanges;
  }

  function open() {
    state.open = true;
    root.classList.remove("hidden");
    render();
  }

  function close() {
    state.open = false;
    root.classList.add("hidden");
  }

  navBtn.addEventListener("click", () => { state.open ? close() : open(); });

  async function render() {
    const isFutures = state.market === "futures";
    const futuresList = isFutures ? await ensureFuturesExchanges() : [];
    const exchangeOptions = isFutures
      ? futuresList.map((f) => `<option value="${esc(f.exchange)}" ${f.exchange === state.exchange ? "selected" : ""}>${esc(f.name)}</option>`).join("")
      : SPOT_EXCHANGES.map((e) => `<option value="${esc(e.id)}" ${e.id === state.exchange ? "selected" : ""}>${esc(e.name)}</option>`).join("");
    const currentSpot = SPOT_EXCHANGES.find((e) => e.id === state.exchange);
    const currentFutures = futuresList.find((f) => f.exchange === state.exchange);
    const needsPass = isFutures ? !!(currentFutures && currentFutures.needs_passphrase) : !!(currentSpot && currentSpot.needsPassphrase);

    root.innerHTML = `
      <div class="diag-overlay">
        <div class="diag-panel">
          <div class="diag-head">
            <h2>Diagnosi <span class="risk-badge">denaro reale</span></h2>
            <button type="button" class="diag-close" id="diag-close-btn" title="Chiudi">✕</button>
          </div>
          <p class="panel-hint">Prova una chiave prima di fidartene: qui si legge solo il saldo, non si piazza mai un ordine senza che tu prema apposta "Esegui" qui sotto. Le chiavi salvate restano quelle di Trading — questa sezione non ne crea di nuove.</p>

          <div class="diag-mode-row">
            <button type="button" class="wl-mode-btn ${!isFutures ? "active" : ""}" id="diag-mode-spot">Spot</button>
            <button type="button" class="wl-mode-btn wl-mode-danger ${isFutures ? "active" : ""}" id="diag-mode-futures">Futures</button>
          </div>

          <div class="diag-section">
            <div class="section-title-row"><span class="section-eyebrow">1 · Test di connessione</span></div>
            <div class="mo-row">
              <div class="mo-field">
                <label class="mo-label" for="diag-exchange">Exchange</label>
                <select id="diag-exchange" class="mo-select">${exchangeOptions}</select>
              </div>
            </div>
            <p class="panel-hint">Lascia i campi vuoti per provare la chiave gia' salvata, oppure incollane una nuova qui sotto solo per il test — non viene salvata.</p>
            <div class="mo-row">
              <input type="text" id="diag-api-key" class="mo-input" placeholder="API Key (opzionale)" autocomplete="off" />
              <input type="password" id="diag-api-secret" class="mo-input" placeholder="API Secret (opzionale)" autocomplete="off" />
            </div>
            ${needsPass ? `<div class="mo-row"><input type="password" id="diag-passphrase" class="mo-input" placeholder="Passphrase" autocomplete="off" /></div>` : ""}
            <button type="button" class="wl-activate-btn" id="diag-test-btn">Testa connessione</button>
            <div id="diag-test-result"></div>
          </div>

          <div class="diag-section" id="diag-order-section">
            <div class="section-title-row"><span class="section-eyebrow">2 · Ordine di prova (solo spot)</span></div>
            <p class="panel-hint">${isFutures
              ? "Per i futures usa il form completo in Trading — leva e margine hanno bisogno dell'anteprima di liquidazione, non riprodotta qui apposta."
              : "Richiede una chiave gia' salvata e abilitata in Trading (non basta la chiave provata sopra al volo)."}</p>
            ${isFutures ? "" : `
            <div class="mo-row">
              <div class="mo-field mo-field-grow">
                <label class="mo-label" for="diag-order-symbol">Pair</label>
                <input type="text" id="diag-order-symbol" class="mo-input" placeholder="es. BTCUSDT" autocomplete="off" />
              </div>
            </div>
            <div class="mo-side-tabs">
              <button type="button" class="mo-side-tab mo-buy-tab mo-tab-active" data-diag-side="BUY">BUY</button>
              <button type="button" class="mo-side-tab mo-sell-tab" data-diag-side="SELL">SELL</button>
            </div>
            <div class="mo-row">
              <div class="mo-field">
                <label class="mo-label" for="diag-order-usdt">USDT (fisso)</label>
                <input type="number" id="diag-order-usdt" class="mo-input" value="10" min="1" step="1" />
              </div>
            </div>
            <label class="futures-confirm">
              <input type="checkbox" id="diag-order-confirm" />
              <span>Confermo: denaro reale, ordine di prova su <b id="diag-order-confirm-text">${esc(state.exchange)}</b></span>
            </label>
            <button type="button" class="mo-execute-btn mo-execute-buy" id="diag-order-btn" disabled>ESEGUI ORDINE DI PROVA</button>
            <div id="diag-order-result"></div>
            `}
          </div>
        </div>
      </div>
    `;
    bind();
  }

  let orderSide = "BUY";

  function bind() {
    document.getElementById("diag-close-btn").addEventListener("click", close);
    document.getElementById("diag-mode-spot").addEventListener("click", () => { state.market = "spot"; render(); });
    document.getElementById("diag-mode-futures").addEventListener("click", () => { state.market = "futures"; render(); });
    document.getElementById("diag-exchange").addEventListener("change", (e) => { state.exchange = e.target.value; render(); });

    document.getElementById("diag-test-btn").addEventListener("click", async () => {
      const btn = document.getElementById("diag-test-btn");
      const out = document.getElementById("diag-test-result");
      btn.disabled = true;
      out.innerHTML = `<p class="panel-hint">Verifico…</p>`;
      try {
        const res = await api("/api/diagnostics/test-connection", {
          method: "POST",
          body: JSON.stringify({
            exchange: state.exchange,
            market: state.market,
            api_key: document.getElementById("diag-api-key").value.trim(),
            api_secret: document.getElementById("diag-api-secret").value.trim(),
            passphrase: document.getElementById("diag-passphrase")?.value.trim() || "",
          }),
        });
        if (!res.ok) {
          out.innerHTML = `<p class="diag-error">✕ ${esc(res.error)}</p>`;
        } else if (res.market === "futures") {
          out.innerHTML = `<p class="diag-ok">✓ Collegato — margine disponibile: <b>${res.margin_usdt.toFixed(2)} USDT</b></p>`;
        } else {
          const rows = (res.balances || []);
          out.innerHTML = rows.length
            ? `<p class="diag-ok">✓ Collegato — saldo:</p><ul class="diag-balances">${rows.map((b) => `<li><span>${esc(b.asset)}</span><span>${b.free.toLocaleString("it-IT", { maximumFractionDigits: 8 })}</span></li>`).join("")}</ul>`
            : `<p class="diag-ok">✓ Collegato — nessun saldo positivo su questo account.</p>`;
        }
      } catch (err) {
        if (err.needsAuth) { document.getElementById("auth-toggle-btn")?.click(); return; }
        out.innerHTML = `<p class="diag-error">✕ ${esc(err.message)}</p>`;
      } finally {
        btn.disabled = false;
      }
    });

    const symbolInput = document.getElementById("diag-order-symbol");
    if (!symbolInput) return; // futures: sezione ordine non renderizzata

    document.querySelectorAll("[data-diag-side]").forEach((tab) => {
      tab.addEventListener("click", () => {
        orderSide = tab.dataset.diagSide;
        document.querySelectorAll("[data-diag-side]").forEach((t) => t.classList.toggle("mo-tab-active", t === tab));
        const execBtn = document.getElementById("diag-order-btn");
        execBtn.textContent = `ESEGUI ORDINE DI PROVA (${orderSide})`;
        execBtn.classList.toggle("mo-execute-buy", orderSide === "BUY");
        execBtn.classList.toggle("mo-execute-sell", orderSide === "SELL");
      });
    });

    const confirmBox = document.getElementById("diag-order-confirm");
    const execBtn = document.getElementById("diag-order-btn");
    confirmBox.addEventListener("change", () => { execBtn.disabled = !confirmBox.checked; });

    execBtn.addEventListener("click", async () => {
      const out = document.getElementById("diag-order-result");
      const symbol = symbolInput.value.trim().toUpperCase();
      if (!symbol) { out.innerHTML = `<p class="diag-error">Pair mancante</p>`; return; }
      execBtn.disabled = true;
      out.innerHTML = `<p class="panel-hint">Invio…</p>`;
      try {
        const res = await api("/api/trading/order", {
          method: "POST",
          body: JSON.stringify({
            exchange: state.exchange, symbol, side: orderSide,
            size_mode: "fixed_usdt",
            size_value: parseFloat(document.getElementById("diag-order-usdt").value) || 0,
          }),
        });
        out.innerHTML = `<p class="diag-ok">✓ Ordine inviato — vedi il diario ordini in Trading per il dettaglio.</p>`;
        confirmBox.checked = false;
      } catch (err) {
        if (err.needsAuth) { document.getElementById("auth-toggle-btn")?.click(); return; }
        out.innerHTML = `<p class="diag-error">✕ ${esc(err.message)}</p>`;
      } finally {
        execBtn.disabled = !confirmBox.checked;
      }
    });
  }
})();
