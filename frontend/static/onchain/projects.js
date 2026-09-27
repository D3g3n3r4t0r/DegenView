/**
 * The project database under the leaderboard: everything the Gem Finder has
 * seen, with its verdict and why (backend: projects_db.py). Search by name,
 * ticker, address or site; filter by verdict. The funnel line says how many
 * projects are known, how many sit in the cap band and where they stand.
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";

const PAGE = 30;
const CHAINS = { solana: "Solana", robinhood: "Robinhood", base: "Base", bsc: "BSC", ethereum: "Ethereum" };
const LABEL = { ranked: "Ranked", studied: "Studied", rejected: "Rejected", new: "Waiting", analyzing: "Analyzing" };

let root = null;
let query = { q: "", status: "", offset: 0 };
let items = [];
let typing = null;

const usd = (v) => (v == null ? "—" : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v)}`);
const num = (n) => (n ?? 0).toLocaleString("en-US");

function row(p) {
  const why = p.why ? `<small class="pj-why">${escapeHtml(p.why)}</small>` : "";
  const score = p.score == null ? "—" : Math.round(p.score);
  const site = p.website ? (() => { try { return new URL(p.website).hostname.replace(/^www\./, ""); } catch { return ""; } })() : "";
  return `<li data-status="${escapeHtml(p.status)}">
    <span class="pj-score" title="Score">${score}</span>
    <span class="pj-name"><b>${escapeHtml(p.symbol ?? "?")}</b> <span>${escapeHtml(p.name ?? "")}</span>
      <small>${CHAINS[p.chain] ?? escapeHtml(p.chain)} · cap ${usd(p.mcap)} · liq ${usd(p.liq)}${site ? ` · ${escapeHtml(site)}` : ""}${p.github ? " · code" : ""}</small>
      ${why}</span>
    <em class="pj-status">${LABEL[p.status] ?? escapeHtml(p.status)}</em>
  </li>`;
}

function paintFunnel(st) {
  const by = st?.by_status ?? {};
  root.querySelector("[data-projects-meta]").textContent = st ? `${num(st.by_chain?.solana ?? 0)} Solana · ${num(st.by_chain?.robinhood ?? 0)} Robinhood · ${num(st.by_chain?.base ?? 0)} Base · ${num(st.by_chain?.ethereum ?? 0)} Ethereum` : "";
  root.querySelector("[data-projects-funnel]").innerHTML = st
    ? `<b>${num(st.total)}</b> projects known · <b>${num(st.in_band)}</b> in the $10k–$3M band · <b>${num((by.studied ?? 0) + (by.ranked ?? 0))}</b> studied · <b>${num(by.rejected ?? 0)}</b> rejected${st.top_rejections?.[0] ? ` (most often: ${escapeHtml(st.top_rejections[0].why)})` : ""}`
    : "";
}

async function load(append = false) {
  try {
    const data = await api.getProjects({ q: query.q, status: query.status, sort: "score", limit: PAGE, offset: query.offset });
    items = append ? [...items, ...(data.items ?? [])] : (data.items ?? []);
    delete root.dataset.loading;
    root.querySelector("[data-projects-list]").innerHTML = items.length
      ? items.map(row).join("")
      : `<li class="pj-empty">${query.q || query.status ? "Nothing matches." : "The database is filling up: sources are being read."}</li>`;
    root.querySelector("[data-projects-more]").hidden = items.length >= (data.total ?? 0);
    paintFunnel(data.stats);
  } catch {
    delete root.dataset.loading;
  }
}

export function mountProjects() {
  root = document.getElementById("projects");
  if (!root) return;
  root.querySelector("[data-projects-q]").addEventListener("input", (event) => {
    clearTimeout(typing);
    typing = setTimeout(() => { query = { ...query, q: event.target.value.trim(), offset: 0 }; load(); }, 250);
  });
  root.querySelector(".projects-filter").addEventListener("click", (event) => {
    const b = event.target.closest("[data-status]");
    if (!b) return;
    root.querySelectorAll(".projects-filter [data-status]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    query = { ...query, status: b.dataset.status, offset: 0 };
    load();
  });
  root.querySelector("[data-projects-more]").addEventListener("click", () => {
    query = { ...query, offset: items.length };
    load(true);
  });
  load();
}
