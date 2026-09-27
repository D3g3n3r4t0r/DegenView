/**
 * The scanner: what the engine is doing right now.
 *
 * Lorenzo: "la scheda scanner e' confusionaria, non voglio che rimanga il
 * grafico di una crypto per tutto il giorno, devi ristudiarla per bene".
 * The old tab had a chart "stage" that followed the last listing, so with no
 * new listing the same chart stayed up for hours; it also repeated the Picks
 * list and used letter placeholders. Now it answers three questions:
 *
 * - is it working? one status line (listening / checking X), the chains, the
 *   time of the last scan, and three numbers: new pools in 10 minutes, passed
 *   and rejected in 24 hours;
 * - what did it decide? a feed of the latest decisions, newest first, each
 *   token with its real logo, Passed or Rejected and the reason. A tap opens
 *   the token page: chart on demand, the report card under "Why";
 * - is it right? one line of what the outcomes taught (rug rate of passed vs
 *   rejected) and, folded, the Wall of Rugs.
 *
 * New decisions arrive by SSE and slide in at the top; nothing else moves.
 */
import * as api from "@onchain/api.js";
import { escapeHtml, strategyLabel, tokenRow } from "@onchain/format.js";
import { openDetail, register } from "@onchain/detail.js";

const POLL_MS = 60_000;
const CHAINS = { solana: "Solana", robinhood: "Robinhood", base: "Base", bsc: "BSC", ethereum: "Ethereum" };
const FEED_SHOWN = 25;
const FEED_MAX = 80;
const DAY_S = 86_400;

let root = null;
let data = null;
let timer = null;
let toast = null;
let stream = null;
let feedAll = false;
let flashTimer = null;
let lastPulse = null;
let lessons = null;

const usd = (v) => {
  if (v == null) return "—";
  if (v >= 1e6) return `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M`;
  if (v >= 1e3) return `$${Math.round(v / 1e3)}k`;
  return `$${Math.round(v)}`;
};
const ago = (ts) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 90 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 172_800 ? `${Math.round(s / 3600)}h ago`
    : `${Math.round(s / 86_400)}d ago`;
};
const lkey = (l) => `${l.chain}:${l.pair_address}`;
const rkey = (r) => `${r.chain}:${r.token_address || r.pair_address}`;

export function mountRadar({ toast: notify } = {}) {
  toast = notify ?? null;
  root = document.getElementById("radar");
  if (!root) return;
  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-feed-more]")) { feedAll = !feedAll; paintFeed(); }
  });
  listen();
  setInterval(() => data && paintStats(), 30_000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
  refresh();
}

function listen() {
  if (!window.EventSource || stream) return;
  stream = new EventSource("/api/onchain/radar/stream");
  const on = (name, fn) => stream.addEventListener(name, (event) => {
    let item;
    try { item = JSON.parse(event.data); } catch { return; }
    if (data) fn(item);
  });
  on("listing", (item) => {
    data.listings = [item, ...(data.listings ?? []).filter((x) => lkey(x) !== lkey(item))];
    paintFeed(`pass:${lkey(item)}`);
    paintStats();
    toast?.(`Passed: ${item.symbol}`, `${CHAINS[item.chain] ?? item.chain} · cap ${usd(item.market_cap)} · liq. ${usd(item.liquidity_usd)}`);
    navigator.vibrate?.(25);
  });
  on("rejected", (item) => {
    data.rejected = [item, ...(data.rejected ?? []).filter((x) => rkey(x) !== rkey(item))];
    paintFeed(`rej:${rkey(item)}`);
    paintStats();
    flash(`${item.symbol} rejected · ${item.reason}`);
  });
  on("update", (item) => {
    data.listings = (data.listings ?? []).map((x) => (lkey(x) === lkey(item) ? item : x));
  });
  on("pulse", (p) => paintPulse(p));
}

async function refresh() {
  clearTimeout(timer);
  try {
    data = await api.getRadar();
    paint();
  } catch {
    // The scanner is read-only: if the server does not answer, keep the screen.
  }
  api.getRadarLessons().then((m) => { lessons = m; paintLearned(); }, () => {});
  if (document.visibilityState === "visible") timer = setTimeout(refresh, POLL_MS);
}

function paint() {
  delete root.dataset.loading;
  root.dataset.running = String(Boolean(data.running));
  const chains = Object.keys(data.chains ?? {}).map((c) => CHAINS[c] ?? c);
  root.querySelector("[data-scan-chains]").textContent = (chains.length ? chains : ["Solana", "Robinhood", "BSC"]).join(" · ");
  paintPulse(data.pulse);
  paintStats();
  paintFeed();
  paintShame();
  paintLearned();
  openFromLink();
}

// The Telegram alert links to #listing=<chain>:<pair>: open that token's page.
let linkDone = false;
function openFromLink() {
  const m = !linkDone && location.hash.match(/listing=([^&]+)/);
  if (!m) return;
  linkDone = true;
  const k = `pass:${decodeURIComponent(m[1])}`;
  if (decisions().some((d) => d.k === k)) openDetail(`scan:${k}`);
}

/* ------------------------------------------------------------ status */

function paintPulse(p) {
  if (p) lastPulse = p;
  const now = root.querySelector("[data-scan-now]");
  const clock = root.querySelector("[data-radar-clock]");
  if (data) clock.textContent = data.running ? "scanning…" : data.last_scan ? `last scan ${ago(data.last_scan)}` : "first scan any moment";
  if (!lastPulse) return;
  root.dataset.busy = String((lastPulse.checking ?? []).length > 0);
  root.querySelector("[data-stat-new]").textContent = String(lastPulse.arrivals_10m ?? 0);
  if (flashTimer) return;   // a rejection stays readable for its few seconds
  const text = lastPulse.checking?.length ? `Checking ${lastPulse.checking.slice(0, 3).join(", ")}` : "Listening for new pools";
  if (now.textContent !== text) now.textContent = text;
}

function flash(text) {
  const now = root.querySelector("[data-scan-now]");
  clearTimeout(flashTimer);
  now.textContent = text;
  now.dataset.tone = "no";
  flashTimer = setTimeout(() => {
    flashTimer = null;
    delete now.dataset.tone;
    now.textContent = "";
    paintPulse();
  }, 4_000);
}

function paintStats() {
  const since = Date.now() / 1000 - DAY_S;
  const passed = (data.listings ?? []).filter((l) => (l.found_at ?? 0) >= since).length;
  const rejected = (data.rejected ?? []).filter((r) => (r.at ?? 0) >= since).length;
  root.querySelector("[data-stat-pass]").textContent = String(passed);
  root.querySelector("[data-stat-rej]").textContent = String(rejected);
}

/* -------------------------------------------------------------- feed */

function decisions() {
  const pass = (data.listings ?? []).map((l) => ({ v: "pass", k: `pass:${lkey(l)}`, at: l.found_at ?? 0, t: l }));
  const rej = (data.rejected ?? []).map((r) => ({ v: "rej", k: `rej:${rkey(r)}`, at: r.at ?? 0, t: r }));
  return [...pass, ...rej].sort((a, b) => b.at - a.at).slice(0, FEED_MAX);
}

function why(d) {
  const t = d.t;
  const head = d.v === "pass"
    ? `<p class="scan-why" data-v="pass">Passed every check: it went out as a Telegram alert.</p>`
    : `<p class="scan-why" data-v="rej">Rejected: ${escapeHtml(t.reason ?? "")}</p>`;
  const nav = links(t);
  return `${head}${reportCard(t)}${nav ? `<nav class="stage-links">${nav}</nav>` : ""}`;
}

function feedRow(d) {
  const t = d.t;
  const id = `scan:${d.k}`;
  register(id, {
    kind: "scan", symbol: t.symbol, name: t.name, chain: t.chain, token: t.token_address, pair: t.pair_address,
    pairUrl: t.pair_url, image: t.image, cap: t.market_cap, ageTs: t.created_at,
    context: `${d.v === "pass" ? "Passed" : "Rejected"} ${ago(d.at)} · ${CHAINS[t.chain] ?? t.chain} · liq ${usd(t.liquidity_usd)}`,
    why: why(d), noTrade: d.v === "rej",   // no buy button under a token the engine threw out
  });
  const verdict = d.v === "pass"
    ? `<span class="verdict" data-v="pass">Passed</span>`
    : `<span class="verdict" data-v="rej">Rejected</span>`;
  return tokenRow({ id, symbol: t.symbol, name: t.name, chain: t.chain, token: t.token_address, image: t.image,
    cap: t.market_cap, pill: verdict, sign: d.v === "pass" ? "up" : "", ageTs: t.created_at,
    sub: `${escapeHtml(ago(d.at))} · ${d.v === "rej" ? escapeHtml(t.reason ?? "") : "alert sent"}` });
}

function paintFeed(arrived) {
  const all = decisions();
  const shown = feedAll ? all : all.slice(0, FEED_SHOWN);
  const list = root.querySelector("[data-scan-feed]");
  list.innerHTML = shown.map(feedRow).join("");
  root.querySelector("[data-scan-empty]").hidden = all.length > 0;
  const more = root.querySelector("[data-feed-more]");
  more.hidden = all.length <= FEED_SHOWN;
  more.textContent = feedAll ? "Show less" : `Show more (${all.length})`;
  if (arrived && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const i = shown.findIndex((d) => d.k === arrived);
    list.children[i]?.animate([{ opacity: 0, transform: "translateY(-10px)" }, { opacity: 1, transform: "none" }],
      { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
}

/* ----------------------------------------------------- is it right? */

function paintLearned() {
  const el = root?.querySelector("[data-scan-learn]");
  if (!el) return;
  const m = lessons;
  const rate = (g) => (g?.rug_rate == null ? null : `${Math.round(g.rug_rate * 100)}%`);
  const a = rate(m?.passed), b = rate(m?.rejected);
  el.textContent = a && b ? `What the outcomes say: ${a} of what passed turned out a rug, against ${b} of what we rejected.` : "";
}

const SHAME_QUIPS = ["waved goodbye on the way out", "took the money and ran", "promoted, then evaporated",
  "thoughts and prayers to the holders", "the GitHub was someone else's"];

function paintShame() {
  const box = root.querySelector("[data-radar-shame]");
  const all = data.shame ?? [];
  box.hidden = all.length === 0;
  box.querySelector("[data-shame-count]").textContent = all.length ? String(all.length) : "";
  box.querySelector("ol").innerHTML = all.map((e, i) => {
    const when = e.rug_at ? new Date(e.rug_at * 1000).toLocaleDateString("en-US", { day: "2-digit", month: "short" }) : "";
    const quip = e.fooled_by ? `fooled us with ${e.fooled_by}` : SHAME_QUIPS[i % SHAME_QUIPS.length];
    const id = `rug:${e.chain}:${e.token_address || e.symbol}`;
    register(id, { kind: "scan", symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address,
      pair: e.pair_address, image: e.image, noTrade: true, context: `${when ? `${when} · ` : ""}${quip}`,
      why: `<p class="scan-why" data-v="rej">Passed our checks, then: ${escapeHtml(e.rug_why ?? "rug")}.</p>` });
    return tokenRow({ id, symbol: e.symbol, name: e.name, chain: e.chain, token: e.token_address, image: e.image,
      cap: e.market_cap, pill: `<span class="verdict" data-v="rug">${escapeHtml(e.rug_why ?? "rug")}</span>`, sign: "down",
      sub: escapeHtml(`${when ? `${when} · ` : ""}${quip}`) });
  }).join("");
}

/* ---------------------------------------------- the report card (Why) */

function links(p) {
  const out = [];
  const a = (url, label, cls = "") => `<a class="${cls}" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`;
  if (p.website) out.push(a(p.website, "Project website", "is-main"));
  if (p.github) out.push(a(p.github, "GitHub"));
  for (const s of p.socials ?? []) {
    if (s.type === "twitter") out.push(a(s.url, "X"));
    if (s.type === "telegram") out.push(a(s.url, "Telegram"));
  }
  if (p.scan_url) out.push(a(p.scan_url, "RugCheck"));
  if (p.pair_url) out.push(a(p.pair_url, "DexScreener"));
  return out.join("");
}

// La pagella: quanto bene ha passato ogni filtro, non solo se l'ha passato.
// Richiesta: "un bel benchmark che mi faccia capire [...] se in modo
// eccellente oppure [...] mediocri".
const GRADE_TONE = { eccellente: "top", buono: "good", sufficiente: "mid", mediocre: "low", excellent: "top", good: "good", fair: "mid", sufficient: "mid", poor: "low" };

function reportCard(p) {
  const checks = p.checks ?? [];
  if (!checks.length) return "";
  const mark = (ok) => (ok === true ? "✓" : ok === false ? "✕" : "·");
  const tone = (ok) => (ok === true ? "ok" : ok === false ? "no" : "info");
  const r = p.report;
  const head = r ? `
    <div class="rc-head" data-grade="${GRADE_TONE[r.grade] ?? "mid"}">
      <span class="rc-score">${r.score}</span>
      <span><b>${escapeHtml(r.grade)}</b><small>average of ${r.counted} checks · weakest: ${escapeHtml(r.weakest)}</small></span>
    </div>` : "";
  const rows = checks.map((c) => {
    const bar = c.score == null ? "" : `
      <span class="rc-meter" data-grade="${GRADE_TONE[c.grade] ?? "mid"}"><span class="rc-bar"><i style="--w:${Math.max(3, Math.min(100, c.score))}%"></i></span><span class="rc-grade">${escapeHtml(c.grade ?? "")} · ${Math.round(c.score)}</span></span>`;
    return `
      <li>
        <span class="mark" data-tone="${tone(c.ok)}">${mark(c.ok)}</span>
        <span class="rc-label">${escapeHtml(strategyLabel(c.label))}</span>
        <span class="rc-detail">${escapeHtml(c.detail ?? "")}</span>
        ${bar}
        ${factsOf(c)}
      </li>`;
  }).join("");
  return `<section class="report-card">${head}<ul class="rc-list">${rows}</ul></section>`;
}

const when = (iso) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? null : ago(t / 1000);
};

function factsOf(c) {
  const f = c.facts;
  const pairs = [];
  if (c.key === "github" && f) {
    pairs.push(["Repository", f.url ? `<a href="${escapeHtml(f.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(f.repo)} ↗</a>` : escapeHtml(f.repo)]);
    if (f.description) pairs.push(["Description", escapeHtml(f.description)]);
    pairs.push(["Language", escapeHtml(f.language ?? "—")], ["Commit", escapeHtml(String(f.commits))],
      ["Active days", String(f.active_days)], ["Authors", String(f.authors)], ["Stars", String(f.stars)],
      ["Forks", String(f.forks)], ["Watchers", String(f.watchers)], ["Open issues", String(f.open_issues)],
      ["Created", escapeHtml(when(f.created_at) ?? "—")], ["Last push", escapeHtml(when(f.pushed_at) ?? "—")],
      ["License", escapeHtml(f.license ?? "none")]);
  } else if (c.key === "site" && f) {
    pairs.push(["Page", `<a href="${escapeHtml(f.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(f.title || f.url)} ↗</a>`],
      ["Words", String(f.words)], ["HTTPS", f.https ? "yes" : "no"], ["Cites contract", f.cites_contract ? "yes" : "no"]);
  } else if (c.key === "contract" && f) {
    pairs.push(["Name & logo", f.metadata_mutable ? "mutable" : "locked"],
      ["Transfer tax", `${f.transfer_fee_pct ?? 0}%`]);
    if (f.holders) pairs.push(["Holder", escapeHtml(String(f.holders))]);
  } else if (c.key === "ai" && c.red_flags?.length) {
    pairs.push(["Red flags", escapeHtml(c.red_flags.join(", "))]);
  }
  if (!pairs.length) return "";
  return `<dl class="rc-facts">${pairs.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>`;
}
