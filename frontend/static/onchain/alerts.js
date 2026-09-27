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
    if (!r) { root.hidden = true; return; }
    root.hidden = false;
    root.querySelector("[data-review-meta]").textContent = new Date(r.at * 1000).toLocaleDateString();
    root.querySelector("[data-review-body]").innerHTML = `<p class="rv-summary">${escapeHtml(r.summary ?? "")}</p>
      ${(r.actions ?? []).length ? `<ul class="rv-actions">${r.actions.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>` : ""}`;
  }).catch(() => { root.hidden = true; });
}

export function mountAlerts() {
  document.querySelectorAll("[data-alerts-kind]").forEach((root) => mountOne(root, root.dataset.alertsKind));
  const review = document.getElementById("review");
  if (review) mountReview(review);
}
