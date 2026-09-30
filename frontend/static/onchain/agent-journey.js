import { NODES, verifyChain, sha256Hex } from "@onchain/agent-map-model.js";

const STEP_MS = 650, MIN_STEP_MS = 90, REPLAY_MS = 20000;
const LABEL = Object.fromEntries(NODES.map(n => [n.id, n.label]));
LABEL.decision = "Decision";
const SOURCE = {
  "projects_db.first_seen": "Project database", "projects_db.verdict": "Project database",
  agent_activity: "Agent activity", deepseek_call: "DeepSeek call journal", strategy_lab: "Strategy lab",
  discovery: "Discovery log", "leaderboard.found": "Research queue", "leaderboard.pillar": "Pillar check",
  "leaderboard.rank": "Ranking", judge: "Judge cache", "research.dossier": "Research cache", "research.reading": "Research cache",
  code_review: "Code review cache", "gem_track.entry": "Top tracker", "gem_track.return": "Top tracker",
  "outcomes.journal": "Outcome journal", "outcomes.archive": "Outcome archive", alert_track: "Alert tracker",
};

/** Replays one token's recorded evaluation path, step by step, and checks its hash chain in the browser.
 * `load({q}|{chain,token})` returns the /api/agent/journey payload; `onStep(node)` lights the map. */
export function mountJourney(root, { load, onStep }) {
  const el = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  const timers = new Set();
  let run = 0;
  const form = el("form", null, "aj-form");
  const input = el("input"); input.type = "search"; input.placeholder = "Ticker or token address"; input.autocomplete = "off";
  input.setAttribute("aria-label", "Ticker or token address");
  const go = el("button", "Trace"); go.type = "submit";
  form.append(input, go);
  const status = el("p", "Type any ticker to replay how the engine evaluated it.", "aj-status");
  const choices = el("div", null, "aj-choices");
  const head = el("div", null, "aj-head");
  const rail = el("ol", null, "aj-rail");
  const tally = el("div", null, "aj-tally"); tally.setAttribute("aria-live", "polite");
  const controls = el("div", null, "aj-controls");
  const replay = el("button", "Replay", "aj-replay"); replay.type = "button"; replay.hidden = true;
  const skip = el("button", "Show all", "aj-replay"); skip.type = "button"; skip.hidden = true;
  controls.append(skip, replay);
  root.className = "aj";
  root.replaceChildren(form, status, choices, head, tally, controls, rail);
  let current = null;

  const clear = () => { timers.forEach(clearTimeout); timers.clear(); };
  const later = (fn, ms) => { const id = setTimeout(() => { timers.delete(id); fn(); }, ms); timers.add(id); };
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const short = h => `${h.slice(0, 8)}…${h.slice(-4)}`;
  const when = t => new Date(t * 1000).toLocaleString();
  const gap = s => s < 60 ? `+${Math.round(s)}s` : s < 3600 ? `+${Math.round(s / 60)}m` : s < 86400 ? `+${Math.round(s / 3600)}h` : `+${Math.round(s / 86400)}d`;

  function card(step, i, prev) {
    const li = el("li", null, "aj-step"); li.dataset.node = step.node;
    const top = el("div", null, "aj-top");
    top.append(el("span", LABEL[step.node] || "Other activity", "aj-pill"),
      el("time", prev ? `${when(step.t)} · ${gap(step.t - prev.t)}` : when(step.t)));
    const src = el("p", `${i + 1}. ${SOURCE[step.source] || step.source}`, "aj-src");
    const body = el("p", step.text || "No description recorded", "aj-text");
    const proof = el("details", null, "aj-proof");
    proof.append(el("summary", `record ${short(step.id)} · link ${short(step.link)}`));
    const pre = el("pre");
    try { pre.textContent = JSON.stringify(JSON.parse(step.record), null, 2); } catch { pre.textContent = step.record; }
    proof.append(pre);
    li.append(top, src, body, proof);
    return li;
  }

  async function show(j) {
    clear(); const mine = ++run; current = j;
    rail.replaceChildren(); head.replaceChildren(); tally.replaceChildren(); replay.hidden = true; skip.hidden = true;
    const n = j.steps.length;
    status.textContent = n ? `${j.symbol || j.token.slice(0, 8)} · ${j.chain} · ${n} recorded steps` : `No stored record for ${j.symbol || j.token}.`;
    if (!n) return;
    const check = el("p", "Verifying hash chain…", "aj-verify");
    head.append(check, el("p", j.limits, "aj-limits"));
    const v = await verifyChain(j, sha256Hex).catch(() => ({ ok: false, brokenAt: 0 }));
    if (mine !== run) return;
    check.dataset.ok = String(v.ok);
    check.textContent = v.ok
      ? `Chain verified in your browser · ${n} records · head ${short(j.head)}`
      : `Chain does not match at step ${(v.brokenAt ?? 0) + 1}: do not trust this trace`;
    const cards = j.steps.map((s, i) => card(s, i, j.steps[i - 1]));
    const counts = new Map(), pills = new Map();
    for (const s of j.steps) if (!pills.has(s.node)) {
      const pill = el("span", `${LABEL[s.node] || "Other"} 0`, "aj-pill"); pills.set(s.node, pill); tally.append(pill);
    }
    const count = node => {
      const c = (counts.get(node) || 0) + 1; counts.set(node, c);
      const pill = pills.get(node); pill.textContent = `${LABEL[node] || "Other"} ${c}`;
      if (!still()) pill.animate([{ transform: "scale(1.15)" }, { transform: "scale(1)" }], { duration: 260 });
    };
    const all = () => {
      clear(); rail.replaceChildren(...cards); cards.forEach(c => c.classList.remove("aj-in", "aj-now"));
      counts.clear(); j.steps.forEach(s => { const c = (counts.get(s.node) || 0) + 1; counts.set(s.node, c); pills.get(s.node).textContent = `${LABEL[s.node] || "Other"} ${c}`; });
      replay.hidden = false; skip.hidden = true;
    };
    skip.onclick = all;
    if (still()) { all(); return; }
    skip.hidden = false;
    const stepMs = Math.max(MIN_STEP_MS, Math.min(STEP_MS, REPLAY_MS / n));
    cards.forEach((c, i) => later(() => {
      if (mine !== run) return;
      c.classList.add("aj-in"); rail.append(c);
      rail.querySelectorAll(".aj-now").forEach(x => x.classList.remove("aj-now"));
      c.classList.add("aj-now");
      requestAnimationFrame(() => c.classList.remove("aj-in"));
      count(j.steps[i].node);
      onStep?.(j.steps[i].node, j.steps[i - 1]?.node);
      if (i === cards.length - 1) { replay.hidden = false; skip.hidden = true; }
    }, i * stepMs));
  }

  async function trace(args) {
    clear(); run++;
    choices.replaceChildren(); rail.replaceChildren(); head.replaceChildren(); tally.replaceChildren(); replay.hidden = true; skip.hidden = true;
    status.textContent = "Loading recorded steps…";
    let data;
    try { data = await load(args); } catch { status.textContent = "Trace unavailable. Try again."; return; }
    root.scrollIntoView?.({ behavior: "smooth", block: "start" });
    if (data?.journey) { input.value = data.journey.symbol || input.value; return show(data.journey); }
    const matches = data?.matches || [];
    if (!matches.length) { status.textContent = `No stored project matches “${args.q}”.`; return; }
    status.textContent = `${matches.length} tokens share this ticker. Pick one:`;
    for (const m of matches) {
      const b = el("button", `${m.symbol || "?"} · ${m.chain} · ${m.token.slice(0, 4)}…${m.token.slice(-4)}${m.status ? ` · ${m.status}` : ""}`);
      b.type = "button"; b.addEventListener("click", () => trace({ chain: m.chain, token: m.token }));
      choices.append(b);
    }
  }

  form.addEventListener("submit", e => { e.preventDefault(); const q = input.value.trim(); if (q) trace({ q }); });
  replay.addEventListener("click", () => { if (current) show(current); });
  return {
    trace,
    dispose() { clear(); run++; root.replaceChildren(); },
  };
}
