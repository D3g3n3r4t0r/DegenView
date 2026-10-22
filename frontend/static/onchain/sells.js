/**
 * Coordinated sells (Lorenzo, 22/10): the wallet clusters of a token, how
 * much of the supply they hold, when they sold together, and the token's
 * risk. The engine writes the reports (coordinated_sells.py has the format);
 * until it does, the server answers with a sample, marked as such.
 * Whitekobra's only: the server answers 404 to the others. Reached from
 * a pill at the top of Scout, #sells, and the Telegram alert.
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";

const POLL_MS = 60_000;
const LINKS = { same_funder: "Same funder", same_block_sells: "Same-block sells", same_amounts: "Same amounts" };

let box = null;

const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(x < 0.01 ? 2 : 1)}%`);
const short = (a) => (a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);
const level = (s) => (s == null ? "" : s >= 70 ? "high" : s >= 40 ? "mid" : "low");
const usd = (v) => (v == null ? "" : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v)}`);

function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function report(r) {
  const name = (c) => `Cluster ${r.clusters.indexOf(c) + 1}`;
  const byId = Object.fromEntries(r.clusters.map((c) => [c.id, c]));
  const held = r.clusters.reduce((t, c) => t + (c.share ?? 0), 0);
  const score = r.risk?.score;
  const bar = r.clusters.map((c, i) =>
    `<i class="cs-seg" data-i="${i % 4}" style="--w:${((c.share ?? 0) * 100).toFixed(2)}%"></i>`).join("");
  const clusters = r.clusters.map((c) => `
    <details class="cs-cluster">
      <summary><i class="cs-dot" data-i="${r.clusters.indexOf(c) % 4}"></i><b>${name(c)}</b>
        <span>${c.wallets.length} wallets · ${pct(c.share)}</span>
        <em data-level="${level(c.risk)}">${c.risk == null ? "" : Math.round(c.risk)}</em></summary>
      <p class="cs-links">${c.links.map((l) => `<span>${escapeHtml(LINKS[l] ?? l.replace(/_/g, " "))}</span>`).join("")}</p>
      <ol class="cs-wallets">${c.wallets.map((w) =>
        `<li><code title="${escapeHtml(w.address)}">${escapeHtml(short(w.address))}</code><span>${pct(w.share)}</span></li>`).join("")}</ol>
    </details>`).join("");
  const events = r.events.map((e) => {
    const c = byId[e.cluster];
    const win = e.window_s == null ? "" : e.window_s >= 60 ? ` in ${Math.round(e.window_s / 60)} min` : ` in ${Math.round(e.window_s)} s`;
    return `<li><i class="cs-dot" data-i="${r.clusters.indexOf(c) % 4}"></i>
      <p><b>${name(c)} sold ${pct(e.share_sold)}</b><small>${e.wallets} wallets${win}${e.usd ? ` · ${usd(e.usd)}` : ""}</small></p>
      <time>${ago(e.ts)}</time></li>`;
  }).join("");
  const title = r.symbol ? escapeHtml(r.symbol) : `<code>${escapeHtml(short(r.token))}</code>`;
  return `<article class="cs-card">
    <header class="cs-head">
      <p><b>${title}</b><small>${escapeHtml(r.chain.charAt(0).toUpperCase() + r.chain.slice(1))}${r.updated_at ? ` · updated ${ago(r.updated_at)}` : ""}</small></p>
      <p class="cs-risk" data-level="${level(score)}" style="--r:${(score ?? 0) / 100}"><b>${score == null ? "—" : Math.round(score)}</b><small>risk</small><i></i></p>
    </header>
    ${r.risk?.reasons?.length ? `<ul class="cs-why">${r.risk.reasons.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
    <h4>Supply held by clusters <span>${pct(held)}</span></h4>
    <div class="cs-bar" aria-hidden="true">${bar}</div>
    ${clusters}
    <h4>Sells together <span>${r.events.length}</span></h4>
    ${events ? `<ol class="cs-time">${events}</ol>` : `<p class="early-empty">No coordinated sell yet.</p>`}
  </article>`;
}

async function load() {
  let data;
  try {
    data = await api.getCoordinatedSells();
  } catch (error) {
    if (error?.status === 404) document.getElementById("sells-entry")?.setAttribute("hidden", "");
    return;
  }
  const entry = document.getElementById("sells-entry");
  if (entry) {
    const top = Math.max(-1, ...(data.reports ?? []).map((r) => r.risk?.score ?? -1));
    entry.hidden = false;
    entry.dataset.level = level(top < 0 ? null : top);
    entry.querySelector("[data-sells-entry-risk]").textContent = top < 0 ? "" : `risk ${Math.round(top)}`;
  }
  box.querySelector("[data-sells-sample]").hidden = !data.sample;
  box.querySelector("[data-sells-empty]").hidden = (data.reports ?? []).length > 0;
  const open = new Set([...box.querySelectorAll(".cs-cluster[open] b")].map((b) => b.textContent));
  box.querySelector("[data-sells-rows]").innerHTML = (data.reports ?? []).map(report).join("");
  box.querySelectorAll(".cs-cluster b").forEach((b) => { if (open.has(b.textContent)) b.closest("details").open = true; });
}

const shown = () => ["sells", "agent"].includes(document.getElementById("app-shell")?.dataset.view) && document.visibilityState === "visible";

async function upload(input) {
  const msg = box.querySelector("[data-sells-upload-msg]");
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  msg.textContent = "Uploading…";
  try {
    const r = await api.uploadCluster(JSON.parse(await file.text()));
    msg.textContent = `Saved: ${r.wallets ?? "?"} wallets. The first read takes a few minutes.`;
  } catch (error) {
    msg.textContent = error instanceof SyntaxError ? "Not a JSON file." : `Not saved: ${error?.message ?? "error"}`;
  }
}

export function mountSells() {
  box = document.querySelector("[data-sells-view]");
  if (!box) return;
  box.querySelector("[data-sells-upload]")?.addEventListener("change", (event) => upload(event.target));
  const shell = document.getElementById("app-shell");
  if (shell) new MutationObserver(() => { if (shown()) load(); }).observe(shell, { attributes: true, attributeFilter: ["data-view"] });
  load();
  setInterval(() => { if (shown()) load(); }, POLL_MS);
}
