/**
 * The Telegram alerts' own leaderboard (backend: alert_track.py): what
 * entering when the message arrived would have paid, at 1, 2, 3, 4, 5, 6,
 * 8, 12, 24 and 48 hours and right now, next to the best backtested
 * strategy on the same token. One component, mounted for memes and gems.
 * Also the daily reviewer's lessons (ai_review.py).
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";

const POLL_MS = 60_000;
const CHAINS = { solana: "Solana", robinhood: "Robinhood" };

// Returns arrive as fractions (0.42 = +42%).
const pct = (f) => (f == null ? "—" : `${f > 0 ? "+" : ""}${Math.round(f * 100)}%`);
const tone = (f) => (f == null ? "" : f > 0 ? "up" : f < 0 ? "down" : "");
const ago = (ts) => {
  const s = Date.now() / 1000 - ts;
  return s < 3600 ? `${Math.max(1, Math.round(s / 60))}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`;
};

function cell(f) {
  return `<td data-sign="${tone(f)}">${pct(f)}</td>`;
}

function table(data) {
  const hs = data.checkpoints ?? [];
  const head = `<tr><th scope="col">Signal</th>${hs.map((h) => `<th scope="col">${h}h</th>`).join("")}<th scope="col" class="al-now">Now</th><th scope="col">Best strategy</th></tr>`;
  const sum = `<tr class="al-sum"><th scope="row">Median <small>${data.total} alerts</small></th>${(data.summary ?? []).map((s) =>
    `<td data-sign="${tone(s.median)}" title="${s.n} alerts · ${Math.round((s.positive ?? 0) * 100)}% in profit">${pct(s.median)}<small>${s.n ? `${Math.round((s.positive ?? 0) * 100)}%↑` : ""}</small></td>`).join("")}
    <td class="al-now" data-sign="${tone(data.now?.median)}">${pct(data.now?.median)}</td>
    <td>${data.strategy?.median_pct == null ? "—" : `${data.strategy.median_pct > 0 ? "+" : ""}${Math.round(data.strategy.median_pct)}%`}</td></tr>`;
  const rows = (data.items ?? []).map((a) => {
    const st = a.strategy;
    const strat = st?.return_pct == null ? "—"
      : `<span data-sign="${st.return_pct >= 0 ? "up" : "down"}">${st.return_pct > 0 ? "+" : ""}${Math.round(st.return_pct)}%</span><small>${escapeHtml(st.label ?? "")}</small>`;
    const name = a.pair_url ? `<a href="${escapeHtml(a.pair_url)}" target="_blank" rel="noopener">${escapeHtml(a.symbol)}</a>` : escapeHtml(a.symbol);
    return `<tr${a.gone ? ' data-gone="1"' : ""}><th scope="row"><b>${name}</b><small>${ago(a.at)} ago · ${CHAINS[a.chain] ?? escapeHtml(a.chain)}${a.gone ? " · pool gone" : ""}</small></th>
      ${hs.map((h) => cell(a.returns?.[String(h)])).join("")}
      <td class="al-now" data-sign="${tone(a.now)}">${pct(a.now)}</td><td class="al-strat">${strat}</td></tr>`;
  }).join("");
  return `<div class="al-scroll" tabindex="0" role="region" aria-label="Alert results by hour"><table class="al-table"><thead>${head}</thead><tbody>${sum}${rows}</tbody></table></div>`;
}

function mountOne(root, kind) {
  let timer = null;
  const refresh = async () => {
    clearTimeout(timer);
    try {
      const data = await api.getAlerts(kind);
      delete root.dataset.loading;
      root.querySelector("[data-alerts-meta]").textContent = data.total ? `${data.total} alerts` : "";
      root.querySelector("[data-alerts-body]").innerHTML = data.total
        ? table(data)
        : `<p class="track-note">No ${kind === "gem" ? "gem" : "meme"} alert sent yet. From the next Telegram message on, each one is followed from the moment it went out.</p>`;
    } catch {
      delete root.dataset.loading;
    }
    if (document.visibilityState === "visible") timer = setTimeout(refresh, POLL_MS);
  };
  refresh();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
}

/** The daily review, kept simple: two sentences and at most three actions. */
function mountReview(root) {
  api.getAiReview().then((data) => {
    const r = data.latest;
    delete root.dataset.loading;
    const body = root.querySelector("[data-review-body]");
    if (!r) {
      body.innerHTML = `<p class="track-note">${data.status?.enabled
        ? "The first review arrives within a day: what worked, what did not, what to change."
        : "Off until the Anthropic API key is set on the server."}</p>`;
      return;
    }
    root.querySelector("[data-review-meta]").textContent = new Date(r.at * 1000).toLocaleDateString();
    body.innerHTML = `<p class="rv-summary">${escapeHtml(r.summary ?? "")}</p>
      ${(r.actions ?? []).length ? `<ul class="rv-actions">${r.actions.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>` : ""}`;
  }).catch(() => { delete root.dataset.loading; });
}

/* ------------------------------------------------------------ the podium */

const DS_CHAIN = { solana: "solana", robinhood: "robinhood" };

/** The token's logo: the one DexScreener gave us, else DexScreener's public
 *  logo for that address, and when neither exists (a load error) the
 *  initials on a gradient picked from the name stay visible underneath. */
export function tile(symbol, image, chain, token) {
  const sym = String(symbol ?? "?");
  const h = [...sym].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 17);
  const src = image || (token && DS_CHAIN[chain] ? `https://dd.dexscreener.com/ds-data/tokens/${DS_CHAIN[chain]}/${token}.png` : "");
  return `<span class="tile" style="--h:${h}"><b>${escapeHtml(sym.slice(0, 2).toUpperCase())}</b>${src
    ? `<img src="${escapeHtml(src)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" />` : ""}</span>`;
}
// One listener for every logo on the page: a missing one just disappears.
document.addEventListener("error", (event) => {
  if (event.target instanceof HTMLImageElement && event.target.parentElement?.classList.contains("tile")) event.target.remove();
}, true);

const topState = { period: 1, kind: "meme", data: {} };
const CONFETTI = 22;

function topRows() {
  const d = topState.data[topState.kind];
  const since = Date.now() / 1000 - topState.period * 86400;
  return (d?.items ?? []).filter((a) => a.at >= since && a.now != null).sort((a, b) => b.now - a.now);
}

function heroCard(a, place) {
  return `<figure class="hero-card" data-place="${place}">
    ${place === 1 ? `<svg class="crown" viewBox="0 0 64 40" aria-hidden="true"><path d="M4 36 8 8l14 14L32 2l10 20L56 8l4 28z"/><circle cx="32" cy="2" r="3"/><circle cx="8" cy="8" r="3"/><circle cx="56" cy="8" r="3"/><circle cx="22" cy="28" r="2.6" class="gem"/><circle cx="32" cy="28" r="2.6" class="gem"/><circle cx="42" cy="28" r="2.6" class="gem"/></svg>` : `<b class="hero-num">${place}</b>`}
    ${tile(a.symbol, a.image, a.chain, a.token_address)}
  </figure>`;
}

function paintTop() {
  const root = document.getElementById("top");
  if (!root) return;
  const rows = topRows();
  delete root.dataset.loading;
  const first = rows[0];
  const second = rows[1];
  const hero = root.querySelector("[data-top-hero]");
  hero.innerHTML = first ? `
    <div class="confetti" aria-hidden="true">${Array.from({ length: CONFETTI }, (_, i) => `<i style="--i:${i}"></i>`).join("")}</div>
    <div class="hero-text"><b class="hero-rank">1</b><span><strong>${escapeHtml(first.symbol)}</strong><em data-sign="${tone(first.now)}">${pct(first.now)}</em><small>alert ${ago(first.at)} ago</small></span></div>
    ${second ? heroCard(second, 2) : ""}${heroCard(first, 1)}` : `<p class="track-note">No alert in this period yet.</p>`;
  hero.hidden = false;
  root.querySelector("[data-top-list]").innerHTML = rows.slice(0, 50).map((a, i) => `
    <li><a href="${escapeHtml(a.pair_url || "#")}" target="_blank" rel="noopener">
      <span class="top-rank" data-place="${i + 1}">${i + 1}</span>
      ${tile(a.symbol, a.image, a.chain, a.token_address)}
      <span class="top-name"><b>${escapeHtml(a.symbol)}${i < 3 ? ` <svg class="mini-crown" viewBox="0 0 24 16" aria-hidden="true"><path d="M2 14 4 3l5 5 3-7 3 7 5-5 2 11z"/></svg>` : ""}</b>
        <small>${ago(a.at)} ago${a.strategy?.return_pct != null ? ` · best strategy ${a.strategy.return_pct > 0 ? "+" : ""}${Math.round(a.strategy.return_pct)}%` : ""}</small></span>
      <span class="top-ret"><b data-sign="${tone(a.now)}">${pct(a.now)}</b><small>max ${pct(a.max)}</small></span>
    </a></li>`).join("");
  const d = topState.data[topState.kind];
  root.querySelector("[data-top-note]").textContent = d
    ? `If you had bought when each Telegram alert arrived. ${d.total} alerts in total · median now ${pct(d.now?.median)}.`
    : "";
}

async function loadTop() {
  try {
    const [meme, gem] = await Promise.all([api.getAlerts("meme"), api.getAlerts("gem")]);
    topState.data = { meme, gem };
    paintTop();
    const last = Math.max(0, ...[...(meme.items ?? []), ...(gem.items ?? [])].map((a) => a.at));
    const seen = Number(localStorageGet("inbox-seen") ?? 0);
    document.querySelector("[data-inbox-dot]")?.toggleAttribute("hidden", !(last > seen));
  } catch { /* keep what is on screen */ }
}

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

function mountTop() {
  const root = document.getElementById("top");
  if (!root) return;
  root.addEventListener("click", (event) => {
    const p = event.target.closest("[data-period]");
    const k = event.target.closest("[data-kind]");
    if (!p && !k) return;
    const b = p ?? k;
    b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (p) topState.period = Number(p.dataset.period);
    else topState.kind = k.dataset.kind;
    paintTop();
  });
  loadTop();
  setInterval(() => document.visibilityState === "visible" && loadTop(), POLL_MS);
}

/** The bell: the latest Telegram alerts, newest first. */
export function openInbox() {
  const all = [...(topState.data.meme?.items ?? []).map((a) => ({ ...a, kind: "Meme" })),
    ...(topState.data.gem?.items ?? []).map((a) => ({ ...a, kind: "Gem" }))].sort((a, b) => b.at - a.at).slice(0, 25);
  let dlg = document.getElementById("inbox");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "inbox";
    dlg.className = "sheet";
    dlg.setAttribute("aria-label", "Alerts");
    dlg.addEventListener("click", (event) => { if (event.target === dlg) dlg.close(); });
    document.body.append(dlg);
  }
  dlg.innerHTML = `<div class="grip" aria-hidden="true"></div><h2 class="sheet-title">Alerts</h2>
    <ol class="inbox">${all.length ? all.map((a) => `<li><a href="${escapeHtml(a.pair_url || "#")}" target="_blank" rel="noopener">
      ${tile(a.symbol, a.image, a.chain, a.token_address)}<span class="top-name"><b>${escapeHtml(a.symbol)}</b><small>${a.kind} · ${ago(a.at)} ago</small></span>
      <span class="top-ret"><b data-sign="${tone(a.now)}">${pct(a.now)}</b><small>since the alert</small></span></a></li>`).join("")
    : `<li class="track-note">No alert yet.</li>`}</ol>`;
  dlg.showModal();
  localStorageSet("inbox-seen", String(Date.now() / 1000));
  document.querySelector("[data-inbox-dot]")?.setAttribute("hidden", "");
}

export function mountAlerts() {
  document.querySelectorAll("[data-alerts-kind]").forEach((root) => mountOne(root, root.dataset.alertsKind));
  const review = document.getElementById("review");
  if (review) mountReview(review);
  mountTop();
}
