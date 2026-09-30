import { mountJourney } from "@onchain/agent-journey.js";
import { liveProject, projectPositions } from "@onchain/agent-map-model.js";

const RECENT = 8;

/** Mount once; reuse the parent view's authenticated polling and dispose on remount.
 * No block diagram: a live line, recent projects and the full recorded trace of one token. */
export function mountAgentMap(root, { loadJourney = null } = {}) {
  let snapshot = {}, disposed = false;
  const element = (tag, content, className) => {
    const el = document.createElement(tag);
    if (content != null) el.textContent = content;
    if (className) el.className = className;
    return el;
  };
  root.className = "agent-map";
  const heading = element("h3", "Inside Engine");
  const subtitle = element("p", "Every recorded step the engine took on a token, replayed in order and checked in your browser.", "am-caption");
  const live = element("button", null, "am-live"); live.type = "button";
  const liveDot = element("span", "", "am-dot"); liveDot.setAttribute("aria-hidden", "true");
  const liveText = element("span");
  live.append(liveDot, liveText);
  const recent = element("div", null, "am-recent"); recent.setAttribute("aria-label", "Recently analysed projects");
  const journeyBox = element("section"); journeyBox.setAttribute("aria-label", "Token journey");
  root.replaceChildren(heading, subtitle, live, recent, journeyBox);
  const journey = loadJourney ? mountJourney(journeyBox, { load: loadJourney }) : null;
  const open = key => { if (!journey || !key) return; const [chain, token] = JSON.parse(key); journey.trace({ chain, token }); };

  let liveKey = null;
  live.addEventListener("click", () => open(liveKey));

  function render() {
    if (disposed) return;
    const now = liveProject(snapshot.items);
    const stale = snapshot.failed || !snapshot.receivedAt || Date.now() - snapshot.receivedAt > 45000;
    const ago = s => s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
    liveKey = now?.key ?? null;
    live.disabled = !now;
    live.dataset.on = String(!!now && now.ageS < 120 && !stale);
    liveText.textContent = now
      ? `${live.dataset.on === "true" ? "Now analysing" : "Last analysed"} ${now.symbol} · ${now.chain} · ${ago(now.ageS)} · tap to trace`
      : snapshot.failed ? "Activity unavailable. Retrying." : "Waiting for activity…";
    const list = projectPositions(snapshot.items, RECENT);
    const signature = list.map(p => p.key).join("|");
    if (recent.dataset.signature !== signature) {
      recent.dataset.signature = signature;
      recent.replaceChildren(...list.map(p => {
        const b = element("button", p.symbol, "am-chip"); b.type = "button";
        b.addEventListener("click", () => open(p.key));
        return b;
      }));
    }
  }

  // Local freshness clock only: never polls or calls any model.
  const clock = setInterval(() => {
    if (document.visibilityState === "visible" && root.offsetParent !== null) render();
  }, 15000);
  render();
  return {
    update(data) { snapshot = { ...snapshot, ...data }; render(); },
    dispose() { disposed = true; journey?.dispose(); clearInterval(clock); root.replaceChildren(); },
  };
}
