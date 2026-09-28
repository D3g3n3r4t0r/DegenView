/**
 * Hidden tokens: the ones this account asked not to see in its lists.
 *
 * Lorenzo: "aggiungi opzione manuale di eliminare i token da ogni lista o
 * classifica (ognuno nel proprio account), dando spazio (animandolo) ad un
 * suo successore che ne prende il posto". The set is per account, kept on the
 * server; here it is only mirrored, so every list can ask isHidden() and
 * repaint when it changes.
 */
import * as api from "@onchain/api.js";

const set = new Set();
const listeners = new Set();

export const isHidden = (chain, token) => set.has(`${chain}:${token}`);

export function onHiddenChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) {
    try { fn(); } catch { /* one list failing must not stop the others */ }
  }
}

async function load() {
  try {
    const r = await api.getHidden();
    set.clear();
    for (const k of r?.hidden ?? []) set.add(k);
    notify();
  } catch { /* not signed in, or offline: nothing is hidden */ }
}

load();

function rowsOf(chain, token) {
  const suffix = `:${chain}:${token}`;
  const out = [];
  for (const el of document.querySelectorAll("[data-open]")) {
    if (!el.dataset.open.endsWith(suffix)) continue;
    out.push(el.closest("li") || el);
  }
  return out;
}

function collapse(rows) {
  const anims = [];
  for (const row of rows) {
    const h = row.getBoundingClientRect().height;
    row.style.overflow = "hidden";
    anims.push(row.animate([{ height: `${h}px`, opacity: 1 }, { height: "0px", opacity: 0 }],
      { duration: 280, easing: "ease-in", fill: "forwards" }));
  }
  return Promise.all(anims.map((a) => a.finished.catch(() => {})));
}

function toast(chain, token) {
  const el = document.createElement("div");
  el.className = "hide-toast";
  el.innerHTML = `Hidden from your lists <button type="button">Undo</button>`;
  el.querySelector("button").addEventListener("click", async () => {
    set.delete(`${chain}:${token}`);
    notify();
    el.remove();
    try { await api.setHidden({ chain, token, hide: false }); } catch { /* stays hidden on the server */ }
  });
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

export async function hideToken(chain, token) {
  await collapse(rowsOf(chain, token));
  const key = `${chain}:${token}`;
  set.add(key);
  notify();
  try {
    await api.setHidden({ chain, token, hide: true });
  } catch {
    set.delete(key);
    notify();
    return;
  }
  toast(chain, token);
}

export function withEntrance(container, paint) {
  if (!container) { paint(); return; }
  const before = new Set([...container.querySelectorAll("[data-open]")].map((el) => el.dataset.open));
  paint();
  if (!before.size) return;
  for (const el of container.querySelectorAll("[data-open]")) {
    if (before.has(el.dataset.open)) continue;
    (el.closest("li") || el).classList.add("is-new");
  }
}
