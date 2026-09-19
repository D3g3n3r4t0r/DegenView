/**
 * Stato della schermata e memoria locale.
 *
 * Due cose vivono in localStorage, per motivi diversi:
 * - l'ultimo saldo letto, perche' all'apertura successiva la cifra c'e'
 *   subito invece di uno spazio vuoto in attesa dell'RPC;
 * - la sequenza delle letture, che e' l'unica serie di dati veri che
 *   questa pagina possiede.
 *
 * Nessuna delle due e' una fonte di verita': se il browser le blocca
 * (finestra privata, storage pieno) la pagina funziona identica, solo
 * senza cifra iniziale e senza grafico.
 */

export const CHAINS = {
  solana: { label: "Solana", unit: "SOL", suffix: "" },
  robinhood: { label: "Robinhood Chain", unit: "ETH", suffix: " (id 4663)" },
};

export const state = {
  chain: "solana",
  wallets: {},
  balance: null,
};

export const chainInfo = () => CHAINS[state.chain];

const read = (key, fallback) => {
  try { return JSON.parse(localStorage.getItem(key) ?? "null") ?? fallback; } catch { return fallback; }
};
const write = (key, value) => {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage piena o bloccata */ }
};

export const readCache = (chain) => read(`onchain_balance_cache_${chain}`, null);
export const writeCache = (chain, data) => write(`onchain_balance_cache_${chain}`, { ...data, at: Date.now() });

const HISTORY_LIMIT = 60;
export const readHistory = (chain) => read(`onchain_balance_history_${chain}`, []);

export function appendHistory(chain, value) {
  const history = [...readHistory(chain), { t: Date.now(), v: value }].slice(-HISTORY_LIMIT);
  write(`onchain_balance_history_${chain}`, history);
  return history;
}
