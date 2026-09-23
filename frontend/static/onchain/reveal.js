/**
 * Rivelazione della chiave privata: QR su un secondo dispositivo, esito in
 * push via SSE, chiave mostrata solo dopo l'approvazione dal telefono.
 *
 * Anche questo e' un <dialog> nativo, ma modale "duro": non si chiude col
 * click fuori, perche' mentre il QR e' vivo c'e' un token a scadenza dall'
 * altra parte e uscire per sbaglio costa una nuova scansione.
 *
 * L'anello di countdown e' un'animazione CSS su stroke-dashoffset, non un
 * requestAnimationFrame che ricalcola a ogni frame.
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";
import { chainInfo, state } from "@onchain/store.js";

const TTL_MS = 120_000;

const dialog = document.querySelector("#reveal");
const bodyEl = dialog.querySelector(".reveal-body");

let stream = null;

function paint(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  bodyEl.replaceChildren(template.content);
  bodyEl.querySelector("[data-close]")?.addEventListener("click", close);
}

function close() {
  stream?.close();
  stream = null;
  dialog.close();
}

export async function startReveal() {
  if (!dialog.open) dialog.showModal();
  paint('<p class="reveal-status">Genero il QR…</p>');

  let session;
  try {
    session = await api.requestReveal(state.chain);
  } catch (error) {
    paint(`<p class="reveal-status is-error">${escapeHtml(error.message)}</p>
      <button type="button" class="btn-quiet" data-close>Chiudi</button>`);
    return;
  }

  paint(`
    <div class="qr" style="--ttl:${TTL_MS}ms">
      <img src="${encodeURI(session.qr_data_uri)}" alt="Codice QR di approvazione" width="200" height="200" />
      <svg viewBox="0 0 212 212" aria-hidden="true">
        <circle class="qr-track" cx="106" cy="106" r="102" />
        <circle class="qr-progress" cx="106" cy="106" r="102" />
      </svg>
    </div>
    <p class="reveal-hint">Inquadra col telefono, o
      <a href="${encodeURI(session.approve_url)}">apri il link</a> se sei gia' li'. Scade in due minuti.</p>
    <p class="reveal-status" data-status>In attesa dell'approvazione…</p>
    <button type="button" class="btn-quiet" data-close>Annulla</button>
  `);

  listen(session.token);
}

function listen(token) {
  stream?.close();
  stream = new EventSource(`/api/onchain/wallets/reveal/stream/${token}`);

  stream.addEventListener("message", async (event) => {
    const { status } = JSON.parse(event.data);
    const statusEl = bodyEl.querySelector("[data-status]");
    if (status === "approved") {
      stream.close();
      if (statusEl) statusEl.textContent = "Approvato — leggo la chiave…";
      await finish(token);
    } else if (status === "expired") {
      stream.close();
      if (statusEl) { statusEl.textContent = "QR scaduto. Chiudi e riprova."; statusEl.classList.add("is-error"); }
    }
  });

  stream.addEventListener("error", () => {
    // SSE caduto (proxy, rete): in questa alpha il ripiego e' annullare e
    // rifare, non un polling di riserva che nasconderebbe il problema.
    stream?.close();
    const statusEl = bodyEl.querySelector("[data-status]");
    if (statusEl) { statusEl.textContent = "Connessione persa. Annulla e riprova."; statusEl.classList.add("is-error"); }
  });
}

async function finish(token) {
  try {
    const revealed = await api.consumeReveal(state.chain, token);
    paint(`
      <div class="reveal-done" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20 6 9 17l-5-5" /></svg>
      </div>
      <p class="reveal-hint">${escapeHtml(revealed.import_as)}</p>
      <p class="secret">${escapeHtml(revealed.private_key)}</p>
      <p class="reveal-hint">${escapeHtml(revealed.warning)}</p>
      <button type="button" class="btn-quiet" data-close>Ho finito</button>
    `);
    // La chiave non resta sullo schermo a tempo indeterminato: chi l'ha
    // aperta ha due minuti per copiarla, poi il pannello si chiude da solo.
    setTimeout(close, TTL_MS);
  } catch (error) {
    paint(`<p class="reveal-status is-error">${escapeHtml(error.message)}</p>
      <button type="button" class="btn-quiet" data-close>Chiudi</button>`);
  }
}

export function revealTargetLabel() {
  return chainInfo().label;
}
