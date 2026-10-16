/**
 * The ticking balance (backend: live_prices.py, GET /api/onchain/live-stream).
 *
 * Lorenzo, 29/09, on pump.fun's app: the wallet's value moves all the time
 * with the price, gains and losses included. Then, 30/09: "vedere in tempo
 * reale i cambiamenti di prezzo [...] non dover aspettare diversi secondi".
 * One stream for every screen: each screen says which tokens it shows and
 * whether it is on screen; the union is pushed by the server (SSE) as soon
 * as a price moves (on-chain pools, Jupiter, DexScreener), and the stream
 * closes when nobody is on screen or the page is hidden. Without
 * EventSource, or when the stream keeps failing, the old poll every POLL_MS.
 * A missed answer keeps the last prices.
 *
 * roll(): numbers whose digits spin to the new value, transform only.
 */
import * as api from "@onchain/api.js";

const POLL_MS = 2000;
const CHECK_MS = 1000;    // how often the wanted key set is re-read (local only)
const subs = new Set();
const last = new Map();   // "chain:addr" -> price
let timer = null;
let busy = false;
let stream = null, streamKeys = "", failures = 0;

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export const priceOf = (key) => last.get(key);

/** "chain:address" as the server keys it; null for native coins. */
export const liveKey = (p) => (p.address && !p.native && p.chain
  ? `${p.chain}:${p.address.startsWith("0x") ? p.address.toLowerCase() : p.address}` : null);

/** A position ({chain, address, value_usd, price_usd}) re-marked at the
 * last live price: value x live / the price it was valued at. No such
 * price (the server does not know it, or the trade is no longer held):
 * its own value, never amount x price, which would mix two readings. */
export function liveValue(p) {
  const k = liveKey(p), px = k && last.get(k);
  if (!px || p.value_usd == null || !p.price_usd) return p.value_usd;
  const v = p.value_usd * (px / p.price_usd);
  return Number.isFinite(v) ? v : p.value_usd;
}

/** Sum of (live value - value) over positions: what to add to a total. */
export const liveDelta = (positions) => (positions ?? []).reduce((sum, p) =>
  (p.hidden || !Number.isFinite(p.value_usd) ? sum : sum + (liveValue(p) - p.value_usd)), 0);

/** watch({keys: () => [...], active: () => bool, onPrices: (map) => {}}) -> unwatch */
export function watch(sub) {
  subs.add(sub);
  schedule(0);
  return () => subs.delete(sub);
}

function schedule(ms) {
  clearTimeout(timer);
  timer = setTimeout(tick, ms);
}

const activeSubs = () => [...subs].filter((s) => s.active());
const wanted = (live) => [...new Set(live.flatMap((s) => s.keys()))].filter(Boolean).sort().slice(0, 60);

// A usable price: a finite number above zero ({p} from older servers too).
const asPrice = (v) => {
  const n = Number(v && typeof v === "object" ? v.p : v);
  return Number.isFinite(n) && n > 0 ? n : null;
};

function deliver(prices) {
  for (const [k, v] of Object.entries(prices ?? {})) {
    const p = asPrice(v);
    if (p != null) last.set(k, p);
  }
  for (const s of activeSubs()) s.onPrices(last);
}

function closeStream() {
  if (stream) stream.close();
  stream = null;
  streamKeys = "";
}

function openStream(keys) {
  closeStream();
  streamKeys = keys.join(",");
  const es = new EventSource(`/api/onchain/live-stream?ids=${encodeURIComponent(streamKeys)}`);
  stream = es;
  es.onopen = () => { failures = 0; };
  es.onmessage = (ev) => {
    try { deliver(JSON.parse(ev.data)); } catch { /* keep the last prices */ }
  };
  es.onerror = () => {
    // EventSource retries by itself; after a few failures in a row, poll
    if (++failures >= 3 && stream === es) closeStream();
  };
}

async function poll(keys) {
  if (busy) return;
  busy = true;
  try {
    const res = await api.getLivePrices(keys);
    deliver(res.prices);
  } catch { /* keep the last prices */ }
  busy = false;
}

async function tick() {
  timer = null;
  if (document.visibilityState !== "visible") { closeStream(); return; }   // visibilitychange restarts it
  const keys = wanted(activeSubs());
  if (!keys.length) { closeStream(); if (subs.size) schedule(POLL_MS * 2); return; }
  if (window.EventSource && failures < 3) {
    if (!stream || keys.join(",") !== streamKeys) openStream(keys);
    schedule(CHECK_MS);
    return;
  }
  await poll(keys);
  schedule(POLL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && subs.size) { failures = 0; schedule(0); }
  else { clearTimeout(timer); timer = null; closeStream(); }
});

/* ---------------------------------------------------------------- roll
 * Each digit is a 0-9 strip in a one-line window; a new value moves the
 * strip (translateY). Other characters are plain. A new shape ($9.99 ->
 * $10.01) rebuilds without spinning, then the next change spins. */
const STRIP = "0123456789".split("").map((d) => `<i>${d}</i>`).join("");

export function roll(el, text) {
  if (!el) return;
  if (el.dataset.roll === text) return;
  const shape = text.replace(/\d/g, "0");
  if (el.dataset.shape !== shape || reduced()) {
    el.innerHTML = `<span class="r-sr">${text}</span><span class="r-w" aria-hidden="true">${[...text].map((c) => (/\d/.test(c)
      ? `<span class="rd"><span class="rd-s" style="transform:translateY(-${c}0%)">${STRIP}</span></span>`
      : `<span class="rc">${c}</span>`)).join("")}</span>`;
    el.dataset.shape = shape;
    el.dataset.roll = text;
    return;
  }
  const strips = el.querySelectorAll(".rd-s");
  let n = 0;
  for (const c of text) if (/\d/.test(c)) strips[n++].style.transform = `translateY(-${c}0%)`;
  el.querySelector(".r-sr").textContent = text;
  el.dataset.roll = text;
}

/** A one-shot flash: two names per direction, so a repeat restarts the
 * CSS animation without forcing a layout. */
export function flash(el, dir) {
  if (!el || reduced()) return;
  el.dataset.tick = `${dir}${el.dataset.tick === `${dir}1` ? 2 : 1}`;
}
