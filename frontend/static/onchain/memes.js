/**
 * Trending memes: tokens the serious scanner rejected for meme reasons
 * (name, website, GitHub) but that are alive, sellable and clean on
 * RugCheck/GoPlus, ranked by the meme engine. The list shows one fact per
 * line, like the reference app; score, reasons, risks and the track record
 * live on the token page (detail.js, "Why"). Gambling: the warning is there
 * too. Read-only: the autopilot never buys these.
 */
import * as api from "@onchain/api.js";
import { escapeHtml, tokenRow } from "@onchain/format.js";
import { register } from "@onchain/detail.js";
import { alertsFor } from "@onchain/alerts.js";
import { isHidden, onHiddenChange, withEntrance } from "@onchain/hidden.js";

const POLL_MS = 60_000;

let root = null;
let timer = null;
let lastTrack = null;
let items = [];
let chosen = [];

const pct = (f) => (f == null ? "—" : `${f > 0 ? "+" : ""}${Math.round(f * 100)}%`);
const usd = (n) => (n == null ? "—" : n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${Math.round(n / 1e3)}k` : `$${Math.round(n)}`);

function why(m) {
  const sc = Math.round(m.score ?? 0);
  const band = (lastTrack?.bands ?? []).find((b) => b.band === m.band && b.n);
  return `<div class="why-score"><span class="ring" style="--v:${sc}"><b>${sc}</b></span>
      <p><b>Meme engine score</b><small>${band ? `Picks scoring ${escapeHtml(m.band)} returned a median ${pct(band.median)} as $100 trades (${band.n} trades).` : "Flow, ticket size, momentum, depth and holders."}</small></p></div>
    <ul class="why-list">${(m.reasons ?? []).map((r) => `<li data-tone="good">${escapeHtml(r)}</li>`).join("")}
      ${(m.risks ?? []).map((r) => `<li data-tone="bad">${escapeHtml(r)}</li>`).join("")}</ul>
    <p class="muted">New token, thin liquidity. Only risk what you can lose.</p>`;
}

function row(m) {
  const id = `meme:${m.chain}:${m.token_address}`;
  register(id, {
    kind: "meme", symbol: m.symbol, name: m.name, chain: m.chain, token: m.token_address, pair: m.pair_address,
    pairUrl: m.pair_url, image: m.image, cap: m.market_cap, change: m.ret_since_seen, ageTs: m.seen_at,
    context: `liq ${usd(m.liquidity_usd)}${m.buys_h1 != null ? ` · ${m.buys_h1} buys / ${m.sells_h1 ?? 0} sells 1h` : ""}`,
    why: why(m), alerts: alertsFor(m.chain, m.token_address),
  });
  const nar = (m.narratives ?? []).slice().sort((a, b) => b.heat - a.heat)[0];
  const mine = nar && chosen.includes(nar.key);
  return tokenRow({ id, symbol: m.symbol, name: m.name, chain: m.chain, token: m.token_address, image: m.image,
    cap: m.market_cap, change: m.ret_since_seen, badge: m.band === "60+" ? "hot" : null, ageTs: m.seen_at,
    sub: nar ? `<span class="bd-nar${mine ? " is-mine" : ""}">${escapeHtml(nar.label)}</span>` : "",
    score: m.score });
}

function trackLine(t) {
  const el = document.querySelector("[data-memes-track]");
  if (!el) return;
  const s = t?.shown;
  el.textContent = s?.n
    ? `Picks shown here, as $100 trades with fees: median ${pct(s.median)} · ${Math.round((s.win_rate ?? 0) * 100)}% made +20% · ${s.n} trades`
    : "";
}

function paintList() {
  const shown = items.filter((m) => !isHidden(m.chain, m.token_address));
  const chosenSet = new Set(chosen);
  const ordered = chosenSet.size
    ? shown.slice().sort((a, b) => {
        const am = (a.narratives ?? []).some((n) => chosenSet.has(n.key)) ? 0 : 1;
        const bm = (b.narratives ?? []).some((n) => chosenSet.has(n.key)) ? 0 : 1;
        return am - bm;
      })
    : shown;
  withEntrance(root.querySelector("[data-memes-list]"), () => {
    root.querySelector("[data-memes-list]").innerHTML = ordered.map(row).join("");
  });
  root.querySelector("[data-memes-empty]").hidden = shown.length > 0;
}

async function refresh() {
  clearTimeout(timer);
  try {
    const data = await api.getRadarMemes();
    items = data.items ?? [];
    lastTrack = data.track ?? null;
    delete root.dataset.loading;
    paintList();
    const watched = data.track?.baseline?.n;
    const line = root.querySelector("[data-picks-line]");
    if (line && items.length) {
      line.textContent = `${items.length} picked${watched ? ` out of ${watched.toLocaleString("en-US")} memes tracked` : " from every new launch"}: pool alive, sellable, safety checks passed. Ranked by score.`;
    }
    trackLine(data.track);
  } catch {
    // If the server does not answer, keep what is on screen.
  }
  if (document.visibilityState === "visible") timer = setTimeout(refresh, POLL_MS);
}

export function mountMemes() {
  root = document.getElementById("memes");
  if (!root) return;
  onHiddenChange(() => paintList());
  api.getNarratives().then((d) => { chosen = d.selected ?? []; paintList(); }).catch(() => {});
  document.addEventListener("lae:narratives", (e) => {
    chosen = e.detail ?? [];
    paintList();
  });
  refresh();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
}
