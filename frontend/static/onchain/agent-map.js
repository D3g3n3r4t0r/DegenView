import { NODES, projectsIn, projectGraph } from "@onchain/agent-map-model.js";

/** Mount once; reuse the parent view's authenticated polling and dispose on remount. */
export function mountAgentMap(root) {
  let selected = "study", key = null, snapshot = {}, disposed = false, frame = 0;
  const element = (tag, content, className) => {
    const el = document.createElement(tag);
    if (content != null) el.textContent = content;
    if (className) el.className = className;
    return el;
  };
  root.className = "agent-map";
  const heading = element("h3", "Inside Engine");
  const subtitle = element("p", "Select a node to inspect recorded work. Connections describe the architecture, not a verified decision trace.", "am-caption");
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
  stage.append(svg, grid); root.replaceChildren(heading, subtitle, label, freshness, usage, stage, detail);

  function draw(graph) {
    if (disposed || !stage.isConnected) return;
    const bounds = stage.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    svg.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
    svg.replaceChildren();
    const position = id => {
      const r = buttons.get(id).button.querySelector(".am-dot").getBoundingClientRect();
      return { x: r.left + r.width / 2 - bounds.left, y: r.top + r.height / 2 - bounds.top };
    };
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
    const graph = projectGraph({ ...snapshot, key });
    freshness.textContent = snapshot.receivedAt
      ? `${graph.stale ? "Updates interrupted" : "Feed received"} · ${new Date(snapshot.receivedAt).toLocaleTimeString()} · ${graph.eventCount} loaded events`
      : snapshot.failed ? "Activity unavailable. Retrying with the Scout feed." : "Waiting for activity…";
    root.dataset.stale = String(graph.stale);
    const count = n => n == null ? "unavailable" : n.toLocaleString();
    usage.textContent = graph.usage
      ? `Global today · ${count(graph.usage.calls)} recorded API calls · ${count(graph.usage.tokens)} reported tokens · estimated USD ${graph.usage.estimatedUsd == null ? "unavailable" : graph.usage.estimatedUsd.toFixed(4)}`
      : "Per-project API usage is not available in this feed. Global totals are not attributed to this project.";
    for (const node of graph.nodes) {
      const { button, status } = buttons.get(node.id);
      button.setAttribute("aria-pressed", String(node.id === selected));
      button.dataset.connected = String(node.kinds?.length !== 0);
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
    cancelAnimationFrame(frame); frame = requestAnimationFrame(() => draw(graph));
  }

  function options() {
    const projects = projectsIn(snapshot.items);
    const signature = JSON.stringify(projects);
    if (select.dataset.signature === signature) return;
    select.dataset.signature = signature;
    select.replaceChildren(new Option("All loaded projects", ""));
    projects.forEach(p => select.add(new Option(p.label, p.key)));
    // Retain selection when the bounded feed moves past its last event.
    if (key && !projects.some(p => p.key === key)) select.add(new Option("Selected project · outside loaded window", key));
    select.value = key || "";
  }
  select.addEventListener("change", () => { key = select.value || null; render(); });
  const observer = new ResizeObserver(() => render()); observer.observe(stage);
  const onVisibility = () => { if (document.visibilityState === "visible") render(); };
  document.addEventListener("visibilitychange", onVisibility);
  // Local freshness clock only: never polls or calls any model.
  const clock = setInterval(() => {
    if (document.visibilityState === "visible" && root.offsetParent !== null) render();
  }, 15000);
  options(); render();
  return {
    update(data) { snapshot = { ...snapshot, ...data }; options(); render(); },
    dispose() { disposed = true; clearInterval(clock); cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener("visibilitychange", onVisibility); root.replaceChildren(); },
  };
}
