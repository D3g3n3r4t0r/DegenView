import { NODES, projectsIn, projectGraph, liveProject, cycleTrace, freshEvents, projectPositions } from "@onchain/agent-map-model.js";

const LIVE = "__live";
const STEP_MS = 520;
const MAX_PROJECTS = 8;

/** Mount once; reuse the parent view's authenticated polling and dispose on remount. */
export function mountAgentMap(root) {
  let selected = "study", key = LIVE, snapshot = {}, disposed = false, frame = 0, primed = false;
  const seen = new Set(), timers = new Set();
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const element = (tag, content, className) => {
    const el = document.createElement(tag);
    if (content != null) el.textContent = content;
    if (className) el.className = className;
    return el;
  };
  root.className = "agent-map";
  const heading = element("h3", "Inside Engine");
  const subtitle = element("p", "Each chip is a project sitting on the step of its latest recorded event; it moves when a new event arrives. Nodes light up on real events; lines describe the architecture, not a verified decision trace.", "am-caption");
  const live = element("p", "", "am-live");
  const liveDot = element("span", "", "am-dot"); liveDot.setAttribute("aria-hidden", "true");
  const liveText = element("span");
  live.append(liveDot, liveText);
  const label = element("label", "Project in loaded activity");
  const select = element("select");
  label.append(select);
  const freshness = element("p", "Waiting for activity…", "am-freshness");
  const usage = element("p", "", "am-usage");
  const stage = element("div", null, "am-stage");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("am-links"); svg.setAttribute("aria-hidden", "true");
  const grid = element("div", null, "am-grid");
  const detail = element("section", null, "am-detail");
  detail.setAttribute("aria-live", "polite"); detail.setAttribute("aria-label", "Selected node details");
  const buttons = new Map();
  for (const node of NODES) {
    const button = element("button"); button.type = "button"; button.dataset.node = node.id;
    const dot = element("span", "", "am-dot"); dot.setAttribute("aria-hidden", "true");
    const status = element("small");
    button.append(dot, element("span", node.label), status);
    button.addEventListener("click", () => { selected = node.id; render(); });
    buttons.set(node.id, { button, status }); grid.append(button);
  }
  stage.append(svg, grid); const sparks = element("div", null, "am-sparks"); sparks.setAttribute("aria-hidden", "true");
  const tokens = element("div", null, "am-tokens");
  stage.append(sparks, tokens);
  // Project chips: each sits on the node of its latest recorded event and hops on new events.
  const where = new Map(), chips = new Map(), pending = new Set();
  root.replaceChildren(heading, subtitle, live, label, freshness, usage, stage, detail);
  const activeKey = () => key === LIVE ? liveProject(snapshot.items)?.key ?? null : key;

  function center(id, bounds = stage.getBoundingClientRect()) {
    const r = buttons.get(id).button.querySelector(".am-dot").getBoundingClientRect();
    return { x: r.left + r.width / 2 - bounds.left, y: r.top + r.height / 2 - bounds.top };
  }

  // Motion only reacts to recorded events; transform and opacity only.
  const later = (fn, ms) => { const id = setTimeout(() => { timers.delete(id); fn(); }, ms); timers.add(id); };
  function pulse(id) {
    if (disposed || still.matches) return;
    const { button } = buttons.get(id);
    button.animate([{ transform: "scale(1)" }, { transform: "scale(1.05)" }, { transform: "scale(1)" }],
      { duration: 480, easing: "cubic-bezier(.2,.8,.2,1)" });
    const ring = element("span", null, "am-ring"); button.append(ring);
    ring.animate([{ transform: "scale(.6)", opacity: .9 }, { transform: "scale(1.6)", opacity: 0 }],
      { duration: 700, easing: "ease-out" }).onfinish = () => ring.remove();
  }
  function spark(from, to) {
    if (disposed || still.matches || from === to || !stage.isConnected) return;
    const a = center(from), b = center(to);
    const dot = element("span", null, "am-spark"); sparks.append(dot);
    dot.animate([{ transform: `translate(${a.x}px,${a.y}px) scale(.6)`, opacity: 0 },
      { transform: `translate(${(a.x + b.x) / 2}px,${(a.y + b.y) / 2}px) scale(1)`, opacity: 1, offset: .5 },
      { transform: `translate(${b.x}px,${b.y}px) scale(.6)`, opacity: 0 }],
      { duration: STEP_MS, easing: "ease-in-out" }).onfinish = () => dot.remove();
  }
  function play(steps) {
    steps.forEach((s, i) => later(() => {
      if (i > 0) spark(steps[i - 1].node, s.node);
      if (!s.quiet) later(() => pulse(s.node), i > 0 ? STEP_MS * .8 : 0);
    }, i * STEP_MS));
  }
  function layoutTokens() {
    if (disposed || !stage.isConnected) return;
    const bounds = stage.getBoundingClientRect();
    if (!bounds.width) return;
    const list = projectPositions(snapshot.items, MAX_PROJECTS);
    const keep = new Set(list.map(p => p.key));
    for (const [k, chip] of chips) if (!keep.has(k)) {
      chips.delete(k); where.delete(k); chip.style.opacity = "0";
      later(() => chip.remove(), 400);
    }
    const slots = new Map();
    for (const p of list) {
      if (!where.has(p.key)) { if (pending.has(p.key)) continue; where.set(p.key, p.node); }
      let chip = chips.get(p.key);
      if (!chip) {
        chip = element("button", p.symbol, "am-chip"); chip.type = "button";
        chip.title = `${p.symbol}: latest recorded step`;
        chip.addEventListener("click", () => {
          key = p.key; options(); select.value = key; render(); play(cycleTrace(snapshot.items, key));
        });
        chip.style.opacity = "0"; tokens.append(chip); chips.set(p.key, chip);
      }
      const node = where.get(p.key), slot = slots.get(node) || 0; slots.set(node, slot + 1);
      const r = buttons.get(node).button.getBoundingClientRect();
      const x = r.left - bounds.left + r.width / 2 + ((slot % 3) - 1) * Math.min(58, r.width / 3.2);
      const y = r.bottom - bounds.top - 16 - Math.floor(slot / 3) * 22;
      chip.style.transform = `translate(${x}px,${y}px) translate(-50%,-50%)`;
      chip.dataset.selected = String(p.key === activeKey());
      if (chip.style.opacity === "0") requestAnimationFrame(() => { chip.style.opacity = "1"; });
    }
  }
  function hops(fresh) {
    const top = new Set(projectPositions(snapshot.items, MAX_PROJECTS).map(p => p.key));
    const byKey = new Map();
    for (const e of fresh) if (e.key && top.has(e.key)) byKey.set(e.key, [...(byKey.get(e.key) || []), e.node]);
    let lane = 0;
    for (const [k, nodes] of byKey) {
      const offset = lane++ * 140; pending.add(k);
      nodes.slice(-6).forEach((node, j) => later(() => {
        pending.delete(k); where.set(k, node); layoutTokens();
        if (k !== activeKey()) pulse(node);
      }, offset + j * STEP_MS));
    }
  }
  function animate() {
    const fresh = freshEvents(seen, snapshot.items);
    const k = activeKey();
    if (!primed) { primed = true; layoutTokens(); if (k) play(cycleTrace(snapshot.items, k)); return; }
    if (document.visibilityState !== "visible" || !fresh.length) return;
    if (!still.matches) hops(fresh);
    else { for (const p of projectPositions(snapshot.items, MAX_PROJECTS)) where.set(p.key, p.node); layoutTokens(); }
    const mine = fresh.filter(e => !k || e.key === k);
    if (!mine.length) return;
    const trace = k ? cycleTrace(snapshot.items, k) : [];
    const firstIdx = trace.findIndex(s => s.t >= mine[0].t);
    const prev = firstIdx > 0 ? trace[firstIdx - 1].node : null;
    play([...(prev ? [{ node: prev, quiet: true }] : []), ...mine.slice(-8).map(e => ({ node: e.node }))]);
  }

  function draw(graph) {
    if (disposed || !stage.isConnected) return;
    const bounds = stage.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    svg.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
    svg.replaceChildren();
    const position = id => center(id, bounds);
    for (const [from, to] of graph.edges) {
      const a = position(from), b = position(to);
      const line = document.createElementNS(svg.namespaceURI, "path");
      const bend = Math.max(20, Math.abs(b.y - a.y) * .45);
      line.setAttribute("d", `M${a.x},${a.y} C${a.x},${a.y + bend} ${b.x},${b.y - bend} ${b.x},${b.y}`);
      if (from === selected || to === selected) line.classList.add("am-related");
      svg.append(line);
    }
  }

  function render() {
    if (disposed) return;
    const graph = projectGraph({ ...snapshot, key: activeKey() });
    freshness.textContent = snapshot.receivedAt
      ? `${graph.stale ? "Updates interrupted" : "Feed received"} · ${new Date(snapshot.receivedAt).toLocaleTimeString()} · ${graph.eventCount} loaded events`
      : snapshot.failed ? "Activity unavailable. Retrying with the Scout feed." : "Waiting for activity…";
    root.dataset.stale = String(graph.stale);
    const now = liveProject(snapshot.items);
    const ago = s => s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
    live.dataset.on = String(!!now && now.ageS < 120 && !graph.stale);
    liveText.textContent = now
      ? `${live.dataset.on === "true" ? "Now analysing" : "Last analysed"} ${now.symbol} · ${now.chain} · ${NODES.find(n => n.id === now.node).label} · ${ago(now.ageS)}`
      : "No project in the loaded activity yet";
    const k = activeKey(), cutoff = Date.now() / 1000 - 90;
    const recent = new Set(k ? cycleTrace(snapshot.items, k).filter(s => s.t >= cutoff).map(s => s.node) : []);
    const count = n => n == null ? "unavailable" : n.toLocaleString();
    usage.textContent = graph.usage
      ? `Global today · ${count(graph.usage.calls)} recorded API calls · ${count(graph.usage.tokens)} reported tokens · estimated USD ${graph.usage.estimatedUsd == null ? "unavailable" : graph.usage.estimatedUsd.toFixed(4)}`
      : "Per-project API usage is not available in this feed. Global totals are not attributed to this project.";
    for (const node of graph.nodes) {
      const { button, status } = buttons.get(node.id);
      button.setAttribute("aria-pressed", String(node.id === selected));
      button.dataset.connected = String(node.kinds?.length !== 0);
      button.dataset.live = String(recent.has(node.id));
      status.textContent = node.count ? `${node.count} events · ${node.status}` : node.status;
    }
    const node = graph.nodes.find(n => n.id === selected);
    const field = (name, value) => {
      const div = element("div"); div.append(element("h4", name), element("p", value)); return div;
    };
    const content = element("div", null, "am-fields");
    content.append(field("Role", node.role), field("Next architectural step", node.next),
      field("Recorded objective / priority", "Not available. Activity notes do not expose the agent's task plan."),
      field("Evidence and limits", node.missing || "Notes and reported steps only; source snapshots, validation and receipt links are not available."));
    const list = element("ol", null, "am-events");
    for (const event of node.events) {
      const row = element("li");
      row.append(element("time", new Date(event.t * 1000).toLocaleString()), element("p", event.text || "No description recorded"));
      if (event.outcome) row.append(element("p", `Reported result: ${event.outcome}`));
      if (event.steps.length) {
        const disclosure = element("details"); disclosure.append(element("summary", "Reported checks"));
        const steps = element("ul"); event.steps.forEach(s => steps.append(element("li", s)));
        disclosure.append(steps); row.append(disclosure);
      }
      list.append(row);
    }
    detail.replaceChildren(element("h3", node.label), content,
      node.events.length ? list : element("p", node.missing || "No event in the loaded window. This does not mean the module never ran."));
    cancelAnimationFrame(frame); frame = requestAnimationFrame(() => { draw(graph); if (primed) layoutTokens(); });
  }

  function options() {
    const projects = projectsIn(snapshot.items);
    const signature = JSON.stringify(projects);
    if (select.dataset.signature === signature) return;
    select.dataset.signature = signature;
    select.replaceChildren(new Option("Follow live · latest project", LIVE), new Option("All loaded projects", ""));
    projects.forEach(p => select.add(new Option(p.label, p.key)));
    // Retain selection when the bounded feed moves past its last event.
    if (key && key !== LIVE && !projects.some(p => p.key === key)) select.add(new Option("Selected project · outside loaded window", key));
    select.value = key || "";
  }
  select.addEventListener("change", () => {
    key = select.value || null; render();
    const k = activeKey(); if (k) play(cycleTrace(snapshot.items, k));
  });
  const observer = new ResizeObserver(() => render()); observer.observe(stage);
  const onVisibility = () => { if (document.visibilityState === "visible") render(); };
  document.addEventListener("visibilitychange", onVisibility);
  // Local freshness clock only: never polls or calls any model.
  const clock = setInterval(() => {
    if (document.visibilityState === "visible" && root.offsetParent !== null) render();
  }, 15000);
  options(); render();
  return {
    update(data) {
      snapshot = { ...snapshot, ...data }; options(); render();
      if (data.items) requestAnimationFrame(animate);
    },
    dispose() { disposed = true; timers.forEach(clearTimeout); timers.clear(); clearInterval(clock); cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener("visibilitychange", onVisibility); root.replaceChildren(); },
  };
}
