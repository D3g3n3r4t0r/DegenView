/**
 * I pannelli che salgono dal basso, su <dialog> nativo.
 *
 * Il browser porta gia' quello che una sheet fatta a mano deve reimplementare
 * male: top-layer (niente z-index da rincorrere), ::backdrop, trappola del
 * focus, chiusura con Escape, e il resto della pagina reso inerte. L'entrata
 * e l'uscita sono CSS (@starting-style + transition-behavior: allow-discrete),
 * non timer JS.
 *
 * Il contenuto si carica all'apertura, mai prima: tetti, transazioni e
 * posizioni cambiano, e una sheet riempita al caricamento della pagina
 * mostrerebbe lo stato di quando la pagina e' stata aperta.
 */
import * as api from "@onchain/api.js";
import { escapeHtml, formatToken, formatUsd, shortAddress } from "@onchain/format.js";
import { chainInfo, readCache, state } from "@onchain/store.js";

// Stesso indirizzo nativo duplicato in swap.js/limitOrders.js: qui serve
// solo per proporre il nativo come "token che hai" nel picker, non per
// firmare niente.
const NATIVE_ADDRESS = {
  solana: "So11111111111111111111111111111111111111112",
  robinhood: "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73",
};

const dialog = document.querySelector("#sheet");
const titleEl = dialog.querySelector(".sheet-title");
const descEl = dialog.querySelector(".sheet-desc");
const bodyEl = dialog.querySelector(".sheet-body");

// Sul backdrop di un <dialog> il click ha come target il dialog stesso:
// e' il modo standard di distinguerlo da un click sul contenuto.
dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
dialog.querySelector(".sheet-close").addEventListener("click", () => dialog.close());

export function openSheet(title, description) {
  titleEl.textContent = title;
  descEl.textContent = description;
  bodyEl.replaceChildren();
  if (!dialog.open) dialog.showModal();
}
const open = openSheet;

export const closeSheet = () => dialog.close();
export const sheetBody = () => bodyEl;

const html = (markup) => {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content;
};

export const setBody = (markup) => bodyEl.replaceChildren(html(markup));
export const setMessage = (text, tone = "") =>
  setBody(`<p class="sheet-note ${tone}">${escapeHtml(text)}</p>`);

/* ---------------------------------------------------------------- Ricevi */

export function openReceive() {
  const { label, unit, suffix } = chainInfo();
  const address = state.wallets[state.chain]?.address ?? readCache(state.chain)?.address ?? "";
  open("Ricevi", `Indirizzo ${label}${suffix}. Manda solo asset di questa chain: un invio da un'altra rete e' perso.`);
  setBody(`
    <p class="address-block">${escapeHtml(address)}</p>
    <dl class="kv">
      <div><dt>Chain</dt><dd>${escapeHtml(label)}${escapeHtml(suffix)}</dd></div>
      <div><dt>Asset nativo</dt><dd>${escapeHtml(unit)}</dd></div>
    </dl>
    <button type="button" class="btn-quiet" data-copy>Copia indirizzo</button>
  `);
  bodyEl.querySelector("[data-copy]").addEventListener("click", async (event) => {
    await navigator.clipboard?.writeText(address);
    event.currentTarget.textContent = "Copiato";
  });
}

/* ---------------------------------------------------------------- Limiti */

export async function openRisk(onChange) {
  open("Limiti & sicurezza", "I tetti valgono su ogni ordine, simulato o reale. Il circuit breaker si riarma solo a mano.");
  setMessage("Leggo lo stato…");
  await renderRisk(onChange);
}

async function renderRisk(onChange) {
  try {
    const data = await api.getRiskStatus(state.chain);
    const breaker = data.circuit_breaker;
    const spentRatio = data.daily_cap_usd ? Math.min(1, data.daily_spent_usd / data.daily_cap_usd) : 0;

    setBody(`
      <dl class="kv">
        <div><dt>Per ordine</dt><dd>${formatUsd(data.per_trade_cap_usd)}</dd></div>
        <div><dt>Concentrazione max</dt><dd>${data.concentration_cap_pct}%</dd></div>
        <div><dt>Esecuzione reale</dt><dd>${data.execution_enabled ? "attiva" : "spenta"}</dd></div>
      </dl>

      <div class="meter" style="--fill:${(spentRatio * 100).toFixed(1)}%">
        <div class="meter-head"><span>Speso oggi</span>
          <b>${formatUsd(data.daily_spent_usd)} di ${formatUsd(data.daily_cap_usd)}</b></div>
        <div class="meter-track"><div class="meter-bar"></div></div>
      </div>

      <p class="breaker" data-tripped="${breaker.tripped}">
        <span class="breaker-dot"></span>
        ${breaker.tripped
          ? `Circuit breaker scattato — ${breaker.consecutive_losses} perdite di fila`
          : "Circuit breaker a riposo"}
      </p>
      ${breaker.tripped ? '<button type="button" class="btn-quiet" data-reset>Riattiva manualmente</button>' : ""}

      <div class="switch-row">
        <span><b>Wallet attivo</b><small>spento resta visibile, ma nessuna operazione lo tocca</small></span>
        <button type="button" class="switch" role="switch" data-toggle></button>
      </div>
    `);

    bodyEl.querySelector("[data-reset]")?.addEventListener("click", async () => {
      try {
        await api.resetCircuitBreaker(state.chain);
        await renderRisk(onChange);
        onChange?.();
      } catch (error) { setMessage(error.message, "is-error"); }
    });
    wireWalletSwitch(bodyEl.querySelector("[data-toggle]"));
  } catch (error) {
    setMessage(error.message, "is-error");
  }
}

// L'interruttore del wallet sta qui, fra i limiti, non in una schermata
// "impostazioni" a se': spegnerlo e' una misura di sicurezza, non una
// preferenza.
function wireWalletSwitch(button) {
  const wallet = state.wallets[state.chain];
  if (!button || !wallet) { button?.closest(".switch-row")?.remove(); return; }

  const paint = (enabled) => button.setAttribute("aria-checked", String(enabled));
  paint(wallet.enabled !== false);

  button.addEventListener("click", async () => {
    const next = button.getAttribute("aria-checked") !== "true";
    button.disabled = true;
    try {
      const updated = await api.setWalletEnabled(state.chain, next);
      state.wallets[state.chain] = { ...wallet, enabled: updated.enabled };
      paint(updated.enabled);
    } catch (error) {
      setMessage(error.message, "is-error");
    } finally {
      button.disabled = false;
    }
  });
}

/* ------------------------------------------------------------- Simulazione */

export function openSimulate({ onAccepted } = {}) {
  open("Simulazione", "Gli stessi guardrail dell'ordine reale, senza chiave e senza transazione: serve a vedere se passerebbe.");
  setBody(`
    <form class="form" id="simulate-form">
      <label for="sim-token">Token</label>
      <input id="sim-token" name="token" type="text" placeholder="simbolo o indirizzo" required autocomplete="off" />

      <label for="sim-side">Lato</label>
      <select id="sim-side" name="side">
        <option value="buy">Compra</option>
        <option value="sell">Vendi</option>
      </select>

      <div class="form-pair">
        <span><label for="sim-notional">Size (USD)</label>
          <input id="sim-notional" name="notional" type="number" min="0" step="0.01" value="10" required /></span>
        <span><label for="sim-price">Prezzo (USD)</label>
          <input id="sim-price" name="price" type="number" min="0" step="0.000001" value="1" required /></span>
      </div>

      <label for="sim-impact">Price impact stimato (%)</label>
      <input id="sim-impact" name="impact" type="number" min="0" step="0.01" value="0.5" required />

      <button type="submit" class="btn-primary">Simula</button>
    </form>
    <output class="outcome" id="simulate-outcome" hidden></output>
  `);

  const form = bodyEl.querySelector("#simulate-form");
  const outcome = bodyEl.querySelector("#simulate-outcome");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = new FormData(form);
    const button = form.querySelector("button");
    button.disabled = true;
    outcome.hidden = false;
    outcome.dataset.tone = "";
    outcome.textContent = "Simulo…";
    try {
      const result = await api.simulateOrder({
        chain: state.chain,
        token: String(fields.get("token")).trim(),
        strategy_name: "manuale",
        side: fields.get("side"),
        notional_usd: Number(fields.get("notional")),
        price_impact_pct: Number(fields.get("impact")),
        price_usd: Number(fields.get("price")),
      });
      outcome.dataset.tone = result.accepted ? "ok" : "no";
      outcome.textContent = result.accepted ? "Passa tutti i guardrail." : result.reason;
      if (result.accepted) onAccepted?.();
    } catch (error) {
      outcome.dataset.tone = "no";
      outcome.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
}

/* ------------------------------------------------------------ Chiave privata */

export function openKey({ onStart }) {
  open("Rivela chiave privata", "Serve il riconoscimento sul tuo telefono — Face ID, Touch ID o password. La sola sessione del browser non basta.");
  setBody(`
    <dl class="kv">
      <div><dt>Verifica</dt><dd>QR + WebAuthn o password</dd></div>
      <div><dt>Validita' del QR</dt><dd>2 minuti</dd></div>
    </dl>
    <button type="button" class="btn-danger" data-start>Rivela ora</button>
  `);
  bodyEl.querySelector("[data-start]").addEventListener("click", () => { dialog.close(); onStart(); });
}

/* ------------------------------------------------------- Righe delle posizioni */

export function positionRow(position) {
  return `
    <li class="asset">
      <span class="asset-mark is-token">${escapeHtml(position.token.slice(0, 1).toUpperCase())}</span>
      <span class="asset-name"><b>${escapeHtml(position.token)}</b>
        <small>${formatToken(position.quantity)} ${escapeHtml(position.token)}</small></span>
      <span class="asset-value"><b>${formatUsd(position.cost_usd)}</b><small>costo</small></span>
    </li>`;
}

/* --------------------------------------------------------- Ricerca token */
// Sostituisce il prompt() del browser: mai un dialog nativo dentro l'app
// (Lorenzo: "sta cosa va fatta all'interno della web app"). Cerca per
// ticker sulla stessa fonte del resto del sito — DexScreener, gia' usata
// per i grafici — non un indirizzo digitato a mano come unica via.
const pickerDialog = document.querySelector("#picker");
const pickerBody = pickerDialog.querySelector(".sheet-body");
pickerDialog.addEventListener("click", (event) => { if (event.target === pickerDialog) pickerDialog.close(); });
pickerDialog.querySelector(".sheet-close").addEventListener("click", () => pickerDialog.close());
pickerBody.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.matches?.("li[data-address]")) event.target.click();
});

let pickerDebounce = null;

export const isNativeAddress = (chain, address) =>
  Boolean(address) && address.toLowerCase() === NATIVE_ADDRESS[chain]?.toLowerCase();

// Un solo foglio per scegliere un token, pensato per il pollice: ricerca in
// cima, sotto i token che hai; scrivere sostituisce la lista invece di
// allungarla. Su touch niente focus automatico — la tastiera coprirebbe
// proprio i token che hai, che sono la scelta piu' frequente.
export function openTokenPicker(chain, { onPick, title = "Scegli token" } = {}) {
  pickerDialog.querySelector(".sheet-title").textContent = title;
  pickerBody.innerHTML = `
    <div class="picker-search">
      <input type="search" id="picker-query" class="mo-input" placeholder="Cerca ticker o incolla indirizzo" autocomplete="off" autocapitalize="characters" spellcheck="false" enterkeyhint="search" />
    </div>
    <p class="label picker-label" id="picker-label">I tuoi token</p>
    <ul id="picker-held" class="tx-list picker-list"><li>Leggo il portafoglio…</li></ul>
    <ul id="picker-results" class="tx-list picker-list" hidden></ul>
  `;
  if (!pickerDialog.open) pickerDialog.showModal();

  const input = pickerBody.querySelector("#picker-query");
  const results = pickerBody.querySelector("#picker-results");
  const held = pickerBody.querySelector("#picker-held");
  const label = pickerBody.querySelector("#picker-label");
  // showModal() mette da solo il focus sul primo campo: su touch va tolto.
  if (matchMedia("(pointer: coarse)").matches) input.blur();
  else input.focus();

  const pick = (token) => { pickerDialog.close(); onPick?.(token); };
  const wirePicks = (list) => list.querySelectorAll("[data-address]").forEach((li) => {
    li.addEventListener("click", () => pick({ address: li.dataset.address, symbolHint: li.dataset.symbol || null }));
  });

  // I token che il wallet ha DAVVERO (saldo nativo + portafoglio reale via
  // RPC), non solo la ricerca per ticker — Lorenzo: "quando seleziono cosa
  // vendere mi devi far selezionare dalle crypto disponibili nel wallet,
  // qualunque esse siano".
  (async () => {
    try {
      const { unit } = chainInfo();
      const [balance, portfolio] = await Promise.all([
        api.getBalance(chain).catch(() => null),
        api.getPortfolio(chain).catch(() => ({ holdings: [] })),
      ]);
      const rows = [];
      if (balance) {
        rows.push({ address: NATIVE_ADDRESS[chain], symbol: unit, amount: balance.native_balance, isNative: true });
      }
      for (const h of portfolio.holdings) {
        if (h.amount > 0) rows.push({ address: h.address, symbol: h.symbol, amount: h.amount, isNative: false });
      }
      if (!rows.length) { held.innerHTML = "<li>Nessun token con saldo trovato.</li>"; return; }
      held.innerHTML = rows.map((r) => `
        <li data-address="${escapeHtml(r.address)}" data-symbol="${escapeHtml(r.symbol)}" role="button" tabindex="0">
          <span><b>${escapeHtml(r.symbol)}</b>${r.isNative ? " <small>nativo</small>" : ""}</span>
          <span>${formatToken(r.amount)}</span>
        </li>`).join("");
      wirePicks(held);
    } catch (error) {
      held.innerHTML = `<li>${escapeHtml(error.message)}</li>`;
    }
  })();

  const showHeld = (yes) => {
    held.hidden = !yes;
    results.hidden = yes;
    label.textContent = yes ? "I tuoi token" : "Risultati";
  };

  input.addEventListener("input", () => {
    clearTimeout(pickerDebounce);
    const q = input.value.trim();
    if (q.length < 2) { showHeld(true); return; }
    showHeld(false);
    // Un indirizzo incollato si usa cosi' com'e': niente ricerca per
    // ticker, niente secondo campo nascosto in un "non lo trovi?".
    if (looksLikeAddress(q)) {
      results.innerHTML = `
        <li data-address="${escapeHtml(q)}" role="button" tabindex="0">
          <span><b>Usa questo indirizzo</b> <small>${escapeHtml(shortAddress(q))}</small></span>
        </li>`;
      wirePicks(results);
      return;
    }
    results.innerHTML = "<li>Cerco…</li>";
    pickerDebounce = setTimeout(async () => {
      try {
        const found = await api.searchTokens(chain, q);
        if (input.value.trim() !== q) return;
        if (!found.length) { results.innerHTML = "<li>Nessun risultato su questa chain.</li>"; return; }
        results.innerHTML = found.map((t) => `
          <li data-address="${escapeHtml(t.address)}" data-symbol="${escapeHtml(t.symbol)}" role="button" tabindex="0">
            <span><b>${escapeHtml(t.symbol)}</b> <small>${escapeHtml(t.name)}</small></span>
            <span class="picker-meta">${t.verified ? "<i class=\"is-verified\">verificato</i>" : "<i>non verificato</i>"}${
              t.liquidity_usd ? ` · liq. ${compactUsd.format(t.liquidity_usd)}` : ""}</span>
          </li>`).join("");
        wirePicks(results);
      } catch (error) {
        results.innerHTML = `<li>${escapeHtml(error.message)}</li>`;
      }
    }, 350);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    results.querySelector("[data-address]")?.click();
  });
}

const compactUsd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1,
});

// Mint Solana (base58, 32-44 caratteri) o contratto EVM (0x + 40 hex).
const looksLikeAddress = (text) =>
  /^0x[0-9a-fA-F]{40}$/.test(text) || /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(text);

export { shortAddress };
