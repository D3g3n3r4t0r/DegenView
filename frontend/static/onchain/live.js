/**
 * The ticking balance (backend: live_prices.py, GET /api/onchain/live-prices).
 *
 * Lorenzo, 29/09, on pump.fun's app: the wallet's value moves all the time
 * with the price, gains and losses included. One poll for every screen:
 * each screen says which tokens it shows and whether it is on screen; the
 * poll asks for the union every POLL_MS while the page is visible, and
 * stops when nobody is on screen. A missed answer keeps the last prices.
 *
 * roll(): numbers whose digits spin to the new value, transform only.
 */
import * as api from "@onchain/api.js";

const POLL_MS = 2000;
const subs = new Set();
const last = new Map();   // "chain:addr" -> price
let timer = null;
let busy = false;

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
  return p.value_usd * (px / p.price_usd);
}

/** Sum of (live value - value) over positions: what to add to a total. */
export const liveDelta = (positions) => (positions ?? []).reduce((sum, p) =>
  (p.hidden || p.value_usd == null ? sum : sum + (liveValue(p) - p.value_usd)), 0);

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

async function tick() {
  timer = null;
  if (document.visibilityState !== "visible") return;   // visibilitychange restarts it
  const live = [...subs].filter((s) => s.active());
  const keys = [...new Set(live.flatMap((s) => s.keys()))].slice(0, 60);
  if (!keys.length) { if (subs.size) schedule(POLL_MS * 2); return; }
  if (!busy) {
    busy = true;
    try {
      const res = await api.getLivePrices(keys);
      for (const [k, v] of Object.entries(res.prices ?? {})) last.set(k, v.p);
      for (const s of live) s.onPrices(last);
    } catch { /* keep the last prices */ }
    busy = false;
  }
  schedule(POLL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && subs.size) schedule(0);
  else { clearTimeout(timer); timer = null; }
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
