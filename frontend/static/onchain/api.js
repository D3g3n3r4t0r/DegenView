/**
 * L'unico posto che parla col backend. Ogni chiamata passa da `request`,
 * quindi il timeout e la forma dell'errore sono uguali ovunque: il resto
 * dell'app vede o un oggetto, o un ApiError con un messaggio in italiano
 * gia' pronto da mostrare.
 */

export class ApiError extends Error {}

const DEFAULT_TIMEOUT_MS = 8000;

async function request(path, { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      // AbortSignal.timeout al posto di una Promise.race con setTimeout:
      // qui la richiesta viene davvero interrotta, non solo ignorata.
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (cause) {
    throw new ApiError(cause.name === "TimeoutError" ? "rete lenta" : "rete non raggiungibile", { cause });
  }

  let payload = null;
  try { payload = await response.json(); } catch { /* 204, o una risposta non-JSON */ }

  if (!response.ok) throw new ApiError(payload?.detail || `errore ${response.status}`);
  return payload;
}

export const getSession = () => request("/api/auth/me");
export const login = (email, password) => request("/api/auth/login", { method: "POST", body: { email, password } });

export const listWallets = () => request("/api/onchain/wallets");
export const createWallet = (chain) => request("/api/onchain/wallets", { method: "POST", body: { chain } });
export const setWalletEnabled = (chain, enabled) =>
  request(`/api/onchain/wallets/${chain}`, { method: "PATCH", body: { enabled } });

export const getBalance = (chain) => request(`/api/onchain/wallets/${chain}/balance`);
export const getTransactions = (chain) => request(`/api/onchain/wallets/${chain}/transactions`, { timeoutMs: 15000 });
export const getPositions = (chain) => request(`/api/onchain/positions/${chain}`);
export const getRiskStatus = (chain) => request(`/api/onchain/risk/status/${chain}`);
export const resetCircuitBreaker = (chain) =>
  request(`/api/onchain/risk/circuit-breaker/${chain}/reset`, { method: "POST" });

export const simulateOrder = (order) => request("/api/onchain/simulate", { method: "POST", body: order });

// Lo swap in due tempi, sempre: prima il preventivo (nessuna chiave, nessun
// impegno), poi — solo se l'utente conferma e solo se il server ha
// l'esecuzione accesa — l'ordine vero. Il backend rifa' comunque il quote da
// se' prima di firmare: quello qui sotto serve a far vedere il prezzo, non e'
// il numero su cui si firma.
export const quoteSolana = (body) => request("/api/onchain/quote/solana", { method: "POST", body, timeoutMs: 15000 });
export const getTokenInfo = (chain, address) => request(`/api/onchain/token/${chain}/${address}`, { timeoutMs: 12000 });
export const quoteRobinhood = (body) => request("/api/onchain/quote/robinhood", { method: "POST", body, timeoutMs: 15000 });

export const executeSolana = (body) =>
  request("/api/onchain/execute/solana", { method: "POST", body, timeoutMs: 45000 });
export const executeRobinhood = (body) =>
  request("/api/onchain/execute/robinhood", { method: "POST", body, timeoutMs: 45000 });

export const requestReveal = (chain) =>
  request(`/api/onchain/wallets/${chain}/reveal/request`, { method: "POST" });
export const consumeReveal = (chain, token) =>
  request(`/api/onchain/wallets/${chain}/reveal`, { method: "POST", body: { token } });
