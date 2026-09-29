/**
 * The narratives picked as a filter, shared by the Database and the Top:
 * kept in this browser only (localStorage "lae:narr"), announced with a
 * "lae:narr" event so every list follows the same choice.
 */
import * as api from "@onchain/api.js";

const KEY = "lae:narr";
const EVENT = "lae:narr";

export function get() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY));
    return Array.isArray(v) ? v.filter((k) => typeof k === "string" && k) : [];
  } catch { return []; }
}

export function set(keys) {
  const list = [...new Set(keys ?? [])];
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { /* private mode */ }
  document.dispatchEvent(new CustomEvent(EVENT, { detail: list }));
}

export function onChange(fn) {
  document.addEventListener(EVENT, (event) => fn(event.detail ?? get()));
}

// How many projects each narrative has (GET /api/onchain/narratives/coverage),
// fetched once per page and shared; a failure is retried on the next call.
let coverageP = null;
export function coverage() {
  coverageP ??= api.getNarrativeCoverage().then((d) => d?.items ?? []).catch(() => { coverageP = null; return []; });
  return coverageP;
}
