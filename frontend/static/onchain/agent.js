/**
 * The agent's presence: a living orb in the top bar and one line of what
 * DeepSeek is doing, always there (Lorenzo, 27/09: "dobbiamo dare l'idea
 * animata che tutto il sito sia gestito da DeepSeek [...] ci deve essere
 * qualcosa che si muove [...] un agent che esamina le cose").
 *
 * The orb breathes when idle and spins its rings while working (activity in
 * the last three minutes). The line cycles through the latest actions from
 * /api/agent; a tap opens the log. Nothing here is decoration only: every
 * line is something the server really did.
 */
import * as api from "@onchain/api.js";
import { escapeHtml } from "@onchain/format.js";
import { openSheet, setBody } from "@onchain/sheets.js";

const POLL_MS = 15_000;
const SAY_MS = 4_000;

let el = null;
let data = null;
let lines = [];
let at = 0;

const ago = (t) => {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? "now" : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`;
};

function sayings() {
  if (!data) return ["Agent starting"];
  const out = (data.items ?? []).slice(0, 6).map((a) => a.text);
  if (data.watching) out.push(`Watching ${data.watching} alerts`);
  const judged = data.today?.scanner ?? 0;
  if (judged) out.push(`${judged} readings today`);
  return out.length ? out : [data.active ? "Agent watching" : "Agent offline"];
}

function say() {
  const target = el?.querySelector("[data-agent-say]");
  if (!target || !lines.length) return;
  at = (at + 1) % lines.length;
  target.classList.remove("is-in");
  void target.offsetWidth;
  target.textContent = lines[at];
  target.classList.add("is-in");
}

async function poll() {
  if (document.visibilityState !== "visible") return;
  try {
    data = await api.getAgent();
  } catch {
    return;
  }
  lines = sayings();
  el.dataset.state = !data.active ? "off" : data.working ? "working" : "idle";
}

function openLog() {
  openSheet("The agent", "DeepSeek reads every alert and gem finalist, remembers past rugs and answers on Telegram. Its verdicts are measured before they filter anything.");
  const items = data?.items ?? [];
  const today = Object.entries(data?.today ?? {}).map(([k, n]) => `${n} ${escapeHtml(k)}`).join(" · ");
  setBody(`${today ? `<p class="sheet-note">Today: ${today}</p>` : ""}
    <ul class="agent-log">${items.length ? items.map((a) => `<li data-kind="${escapeHtml(a.kind)}">
      <span class="agent-dot" aria-hidden="true"></span><span>${escapeHtml(a.text)}</span><small>${ago(a.t)}</small></li>`).join("")
      : `<li class="agent-empty"><span>Nothing yet today: it reads new alerts every 10 minutes.</span></li>`}</ul>`);
}

export function mountAgent() {
  el = document.getElementById("agent");
  if (!el) return;
  el.addEventListener("click", openLog);
  poll();
  setInterval(poll, POLL_MS);
  setInterval(say, SAY_MS);
}
