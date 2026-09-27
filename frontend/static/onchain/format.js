/**
 * Formattazione, tutta da Intl: valuta, quantita' e "quanto fa" non si
 * costruiscono a mano con toFixed e concatenazioni. Intl conosce gia' il
 * separatore delle migliaia italiano, i minimi/massimi decimali e i tempi
 * relativi — riscriverli a mano significa solo sbagliarli in un caso.
 */

// Locale en-US per i soli importi in dollari, non per distrazione: in it-IT
// Intl scrive "8,87 USD", con la sigla in coda, mentre tutto il resto di
// questa app (i tetti, il ledger, il price feed) parla di "$20" col simbolo
// davanti. Due forme per la stessa valuta nella stessa schermata sono un
// inciampo.
const usd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
});

// I saldi nativi vivono su scale incompatibili fra loro: 0.00337 ETH e
// 142.6 SOL vogliono un numero di decimali diverso, e arrotondare il primo
// a due cifre lo azzererebbe.
const token = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 6 });

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export const formatUsd = (value) => usd.format(value);
export const formatToken = (value) => token.format(value);

/** "$8.87" spezzato in parti: il simbolo e i centesimi si compongono piu'
 *  piccoli del numero, e per farlo servono i pezzi separati. */
export function usdParts(value) {
  const parts = usd.formatToParts(value);
  const pick = (...types) => parts.filter((p) => types.includes(p.type)).map((p) => p.value).join("");
  return {
    currency: pick("currency"),
    integer: pick("integer", "group"),
    fraction: pick("decimal", "fraction"),
  };
}

export function freshness(atMs) {
  const seconds = Math.round((Date.now() - atMs) / 1000);
  if (seconds < 8) return "updated just now";
  if (seconds < 60) return relative.format(-seconds, "second");
  if (seconds < 3600) return relative.format(-Math.round(seconds / 60), "minute");
  return relative.format(-Math.round(seconds / 3600), "hour");
}

export const shortAddress = (address) =>
  address.length > 18 ? `${address.slice(0, 10)}…${address.slice(-6)}` : address;

export const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

// Strategy names are storage keys on the backend (watchlist, auto-trade);
// only what the page shows is renamed to neutral, professional labels.
const STRATEGY_LABELS = [
  [/^Lorenzo HF\b[^·]*/i, "Trend HF"],
  [/^Lorenzo\b[^·]*/i, "Trend EMA"],
  [/^Gabriele 2\b[^·]*/i, "RSI+BB Long/Short"],
  [/^Gabriele\b[^·]*/i, "RSI+BB Reversal"],
];
export function strategyLabel(name) {
  const text = String(name ?? "");
  for (const [re, label] of STRATEGY_LABELS) if (re.test(text)) return text.replace(re, `${label} `).replace(/\s+$/, "").replace(/\s+·/, " ·");
  return text;
}

/* ------------------------------------------------------------ token rows */

// Compact dollars for lists: $510k, $3.5M, $420M.
export const usdShort = (v) => (v == null || !Number.isFinite(Number(v)) ? "—"
  : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M`
    : v >= 1e3 ? `$${(v / 1e3).toFixed(v >= 1e5 ? 0 : 1)}k` : `$${Math.round(v)}`);

// Age like the reference: 16m, 13h, 11d. Returns [text, fresh?].
export function age(ts) {
  if (!ts) return ["—", false];
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return [`${Math.max(1, Math.round(s / 60))}m`, s < 1800];
  if (s < 86400) return [`${Math.round(s / 3600)}h`, false];
  return [`${Math.round(s / 86400)}d`, false];
}

const DS_CHAIN = { solana: "solana", robinhood: "robinhood" };
const CHAIN_MARK = {
  solana: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16.5h12.5l2-2H7zM5 7.5h12.5l2 2H7zM5 12h12.5l2-2H7" /></svg>',
  robinhood: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 20 12 12 21 4 12z" /></svg>',
};

/** The token's logo: DexScreener's image, else its public logo for the
 *  address; the letter on a dark tile stays underneath if neither loads. */
export function tile(symbol, image, chain, token) {
  const sym = String(symbol ?? "?");
  const src = image || (token && DS_CHAIN[chain] ? `https://dd.dexscreener.com/ds-data/tokens/${DS_CHAIN[chain]}/${token}.png` : "");
  return `<span class="tile"><b>${escapeHtml(sym.replace(/^\$/, "").slice(0, 1).toUpperCase())}</b>${src
    ? `<img src="${escapeHtml(src)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" />` : ""}</span>`;
}
if (typeof document !== "undefined") {
  document.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.parentElement?.classList.contains("tile")) event.target.remove();
  }, true);
}

export function logo(symbol, image, chain, token) {
  return `<span class="logo">${tile(symbol, image, chain, token)}<i class="chain-mark" data-chain="${escapeHtml(chain ?? "")}">${CHAIN_MARK[chain] ?? ""}</i></span>`;
}

/** Change pill: ↑ 42% green / ↓ 7% red, from a fraction. */
export function changePill(f) {
  if (f == null || !Number.isFinite(Number(f))) return `<em class="chg">—</em>`;
  const up = f >= 0;
  const p = Math.abs(f * 100);
  return `<em class="chg" data-sign="${up ? "up" : "down"}">${up ? "↑" : "↓"} ${p >= 1000 ? Math.round(p).toLocaleString("en-US") : p >= 10 ? Math.round(p) : p.toFixed(1)}%</em>`;
}

/**
 * One row for every list (memes, gems, search, leaderboard): logo with the
 * chain, name with a HOT/EARLY pill, ticker and age, market cap and a pill.
 */
export function tokenRow({ id, symbol, name, chain, token, image, cap, change, pill, badge, ageTs, sub, sign }) {
  const [a, fresh] = age(ageTs);
  const tone = sign ?? (change == null ? "" : change >= 0 ? "up" : "down");
  return `<li class="trow" data-sign="${tone}"><button type="button" data-open="${escapeHtml(id)}">
    ${logo(symbol, image, chain, token)}
    <span class="trow-main">
      <b>${escapeHtml(name || symbol)}${badge === "hot" ? ' <em class="hot">HOT</em>' : badge === "early" ? ' <em class="hot early">EARLY</em>' : ""}</b>
      <small>${escapeHtml(symbol)}${ageTs ? ` <span class="age${fresh ? " fresh" : ""}"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 14V7M8 9c0-3 2-4.5 5-4.5 0 3-2 4.5-5 4.5ZM8 8C8 5.5 6.3 4 3.5 4c0 2.6 1.7 4 4.5 4Z"/></svg>${a}</span>` : ""}${sub ? ` <span class="sub">${sub}</span>` : ""}</small>
    </span>
    <span class="trow-num"><b>${usdShort(cap)}</b>${pill ?? changePill(change)}</span>
  </button></li>`;
}
