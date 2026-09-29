/**
 * The project database under the leaderboard: everything the Gem Finder has
 * seen, with its verdict and why (backend: projects_db.py). Search by name,
 * ticker, address or site; filter by verdict. The funnel line says how many
 * projects are known, how many sit in the cap band and where they stand.
 */
import * as api from "@onchain/api.js";
import { register } from "@onchain/detail.js";
import { escapeHtml } from "@onchain/format.js";
import { isHidden, onHiddenChange, withEntrance } from "@onchain/hidden.js";
import * as narr from "@onchain/narrative_pick.js";

const PAGE = 30;
const CHAINS = { solana: "Solana", robinhood: "Robinhood", base: "Base", bsc: "BSC", ethereum: "Ethereum" };
const LABEL = { ranked: "Ranked", studied: "Studied", rejected: "Rejected", new: "Waiting", analyzing: "Analyzing" };

let root = null;
let query = { q: "", status: "", offset: 0 };
let items = [];
let typing = null;
let narratives = [];   // coverage items, most projects first

const usd = (v) => (v == null ? "—" : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v)}`);
const num = (n) => (n ?? 0).toLocaleString("en-US");

function row(p) {
  const why = p.why ? `<small class="pj-why">${escapeHtml(p.why)}</small>` : "";
  // Only a ranked project's score competes with the board; the others show
  // theirs dimmed, with why they are out (the reason line below).
  const score = p.score == null ? "—" : Math.round(p.score);
  const out = p.status !== "ranked" && p.score != null;
  const site = p.website ? (() => { try { return new URL(p.website).hostname.replace(/^www\./, ""); } catch { return ""; } })() : "";
  const id = `gem:${p.chain}:${p.token}`;
  register(id, {
    kind: "gem",
    symbol: p.symbol,
    name: p.name,
    chain: p.chain,
    token: p.token,
    image: p.image,
    cap: p.mcap,
    context: `Database · score ${score} · ${p.status}${p.why ? ` · ${p.why}` : ""}`,
  });
  return `<li data-status="${escapeHtml(p.status)}">
    <button type="button" class="pj-open" data-open="${escapeHtml(id)}">
      <span class="pj-score${out ? " is-out" : ""}" title="${out ? "Score, not on the board" : "Score"}">${score}</span>
      <span class="pj-name"><b>${escapeHtml(p.symbol ?? "?")}</b> <span>${escapeHtml(p.name ?? "")}</span>
        <small>${CHAINS[p.chain] ?? escapeHtml(p.chain)} · cap ${usd(p.mcap)} · liq ${usd(p.liq)}${site ? ` · ${escapeHtml(site)}` : ""}${p.github ? " · code" : ""}</small>
        ${why}</span>
      <em class="pj-status">${LABEL[p.status] ?? escapeHtml(p.status)}</em>
    </button>
  </li>`;
}

function paintFunnel(st) {
  const by = st?.by_status ?? {};
  root.querySelector("[data-projects-meta]").textContent = st ? `${num(st.by_chain?.solana ?? 0)} Solana · ${num(st.by_chain?.robinhood ?? 0)} Robinhood · ${num(st.by_chain?.base ?? 0)} Base · ${num(st.by_chain?.ethereum ?? 0)} Ethereum` : "";
  root.querySelector("[data-projects-funnel]").innerHTML = st
    ? `<b>${num(st.total)}</b> projects known · <b>${num(st.in_band)}</b> in the $10k–$3M band · <b>${num((by.studied ?? 0) + (by.ranked ?? 0))}</b> studied · <b>${num(by.rejected ?? 0)}</b> rejected${st.top_rejections?.[0] ? ` (most often: ${escapeHtml(st.top_rejections[0].why)})` : ""}`
    : "";
}

function paintList() {
  const shown = items.filter((p) => !isHidden(p.chain, p.token));
  withEntrance(root.querySelector("[data-projects-list]"), () => {
    root.querySelector("[data-projects-list]").innerHTML = shown.length
      ? shown.map(row).join("")
      : `<li class="pj-empty">${narr.get().length ? "No project in these narratives yet."
        : query.q || query.status ? "Nothing matches." : "The database is filling up: sources are being read."}</li>`;
  });
}

function paintNarr() {
  const box = root.querySelector("[data-projects-narr]");
  if (!box || !narratives.length) return;
  const sel = new Set(narr.get());
  box.innerHTML = `<button type="button" data-narr="" aria-pressed="${!sel.size}">All</button>`
    + narratives.map((n) => `<button type="button" data-narr="${escapeHtml(n.key)}" aria-pressed="${sel.has(n.key)}">${escapeHtml(n.label)} <small>${num(n.projects)}</small></button>`).join("");
}

async function load(append = false) {
  try {
    const params = { q: query.q, status: query.status, sort: "score", limit: PAGE, offset: query.offset };
    const keys = narr.get();
    if (keys.length) params.narrative = keys.join(",");
    const data = await api.getProjects(params);
    items = append ? [...items, ...(data.items ?? [])] : (data.items ?? []);
    delete root.dataset.loading;
    paintList();
    root.querySelector("[data-projects-more]").hidden = items.length >= (data.total ?? 0);
    paintFunnel(data.stats);
  } catch {
    delete root.dataset.loading;
  }
}

export function mountProjects() {
  root = document.getElementById("projects");
  if (!root) return;
  onHiddenChange(() => paintList());
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
  root.querySelector("[data-projects-narr]")?.addEventListener("click", (event) => {
    const b = event.target.closest("[data-narr]");
    if (!b) return;
    const key = b.dataset.narr;
    const keys = narr.get();
    narr.set(!key ? [] : keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]);
  });
  narr.onChange(() => {
    query = { ...query, offset: 0 };
    paintNarr();
    load();
  });
  narr.coverage().then((list) => {
    narratives = list.slice().sort((a, b) => (b.projects ?? 0) - (a.projects ?? 0));
    paintNarr();
  });
  root.querySelector("[data-projects-more]").addEventListener("click", () => {
    query = { ...query, offset: items.length };
    load(true);
  });
  load();
}
