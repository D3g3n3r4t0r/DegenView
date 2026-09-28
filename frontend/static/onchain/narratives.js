/**
 * Narratives: the themes the user wants the scanner to look for (Lorenzo,
 * 28/09: "diamo la possibilita' di scegliere la narrativa [...] una certa
 * personalizzazione dei token che andremo a cercare"). The catalog and the
 * chosen keys live on the server (per account); the "mine only" toggle is
 * per device.
 */
import * as api from "@onchain/api.js";

const MINE_KEY = "lae:mine-narratives";

let catalog = null;
let selected = new Set();
let loading = null;
const listeners = new Set();

function notify() { listeners.forEach((cb) => { try { cb(); } catch { /* one bad listener */ } }); }

/** Load the catalog and the chosen keys once; later calls reuse the cache. */
export function loadNarratives() {
  if (catalog) return Promise.resolve({ catalog, selected: [...selected] });
  if (loading) return loading;
  loading = api.getNarratives().then((d) => {
    catalog = d?.catalog ?? [];
    selected = new Set(d?.selected ?? []);
    loading = null;
    return { catalog, selected: [...selected] };
  }, (err) => { loading = null; throw err; });
  return loading;
}

export function catalogList() { return catalog ?? []; }
export function chosen() { return new Set(selected); }

/** True when nothing is chosen, or when the entry carries one of the chosen keys. */
export function matchesNarrative(e) {
  if (!selected.size) return true;
  const list = e?.narratives ?? [];
  for (const n of list) if (selected.has(n.key)) return true;
  return false;
}

export function onNarrativesChange(cb) { listeners.add(cb); return () => listeners.delete(cb); }

/** Save the chosen keys; the local set flips first, the server follows. */
export function saveNarratives(keys) {
  const prev = selected;
  selected = new Set(keys);
  notify();
  return api.setNarratives(keys).then((d) => {
    selected = new Set(d?.selected ?? keys);
    notify();
    return [...selected];
  }, (err) => { selected = prev; notify(); throw err; });
}

export function mineOnly() {
  try { return localStorage.getItem(MINE_KEY) === "1"; } catch { return false; }
}
export function setMineOnly(on) {
  try { localStorage.setItem(MINE_KEY, on ? "1" : "0"); } catch { /* private mode */ }
  notify();
}
