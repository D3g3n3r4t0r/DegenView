/** Read-only projection of the legacy activity feed. No inferred causality. */
export const NODES = [
  { id: "scan", label: "Discovery", kinds: ["scan", "scanner", "manual"], role: "Find and check candidate tokens.", next: "Candidate checks and project research." },
  { id: "study", label: "Project study", kinds: ["study"], role: "Review GitHub, website and tokenomics pillars.", next: "Research and ranking evaluation." },
  { id: "research", label: "Research / judge", kinds: ["research", "judge", "review"], role: "Read project material and challenge the assessment.", next: "Validate findings before changing a decision." },
  { id: "code", label: "Code review", kinds: ["code"], role: "Examine repository evidence.", next: "Reuse or invalidate the review when its inputs change." },
  { id: "narratives", label: "Narratives", kinds: ["narratives"], role: "Associate projects with narrative categories.", next: "Update project context." },
  { id: "consistency", label: "Consistency", kinds: ["consistency"], role: "Look for contradictions in existing assessments.", next: "Confirm a finding before requesting another analysis." },
  { id: "memory", label: "Evidence / reuse", kinds: [], role: "Preserve evidence and reuse valid analysis.", next: "Connect versioned artifacts and dependency invalidation.", missing: "Artifact validity and reuse receipts are not exposed by this feed." },
  { id: "decision", label: "Decision", kinds: [], role: "Apply the ranking policy to available evidence.", next: "Connect the actual decision receipt and policy contributions.", missing: "A study note is not a ranking decision or an execution permission." },
  { id: "backtest", label: "Backtests", kinds: ["backtest"], role: "Evaluate strategies on historical data.", next: "Compare results while preserving historical data cutoffs." },
  { id: "outcomes", label: "Observed outcomes", kinds: [], role: "Compare an assessment with subsequent observations.", next: "Connect matured outcomes and data coverage.", missing: "Outcome labels and coverage are not exposed by this feed." },
  { id: "agent", label: "Agent objectives", kinds: [], role: "Prioritize open questions within a budget.", next: "Connect task objectives, priority reasons and stop conditions.", missing: "No structured objective or hypothesis is available in the current API." },
  { id: "other", label: "Other activity", kinds: null, role: "Keep activity without a mapped category visible.", next: "Classify new event kinds without losing their records." },
];
// Architecture edges, deliberately NOT receipt-backed traces.
export const EDGES = [["scan", "study"], ["study", "research"], ["study", "code"],
  ["research", "narratives"], ["research", "consistency"], ["code", "memory"],
  ["research", "memory"], ["memory", "decision"], ["consistency", "decision"],
  ["decision", "backtest"], ["backtest", "outcomes"], ["outcomes", "agent"],
  ["agent", "research"]];

const text = (v, max = 500) => typeof v === "string" ? v.slice(0, max) : "";
const number = (v) => typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;

export function projectKey(row) {
  return typeof row?.chain === "string" && row.chain && typeof row.token === "string" && row.token
    ? JSON.stringify([row.chain, row.token]) : null;
}

export function normalizeEvents(items) {
  if (!Array.isArray(items)) return [];
  // Do not deduplicate by timestamp: distinct events may share one timestamp.
  return items.filter(e => e && typeof e === "object" && number(e.t) !== null)
    .map(e => ({ t: e.t, kind: text(e.kind, 80), text: text(e.text), outcome: text(e.outcome),
      key: projectKey(e), chain: text(e.chain, 80), token: text(e.token, 160),
      symbol: text(e.symbol, 80), steps: Array.isArray(e.steps) ? e.steps.slice(0, 8).map(s => text(s)).filter(Boolean) : [] }))
    .sort((a, b) => b.t - a.t).slice(0, 300);
}

export function projectsIn(items) {
  const map = new Map();
  for (const e of normalizeEvents(items)) if (e.key && !map.has(e.key)) {
    map.set(e.key, { key: e.key, label: `${e.symbol || e.token.slice(0, 12)} · ${e.chain} · ${e.token.slice(-6)}` });
  }
  return [...map.values()];
}

export function projectGraph({ items, info, key = null, receivedAt = null, failed = false, now = Date.now() }) {
  const events = normalizeEvents(items).filter(e => !key || e.key === key);
  const stale = failed || receivedAt === null || now - receivedAt > 45000;
  const known = new Set(NODES.flatMap(n => n.kinds || []));
  const nodes = NODES.map(n => {
    const matches = events.filter(e => n.kinds === null ? !known.has(e.kind) : n.kinds.includes(e.kind));
    return { ...n, events: matches.slice(0, 8), count: matches.length,
      status: n.kinds?.length === 0 ? "Not connected" : stale ? "Updates unavailable" : matches.length ? "Recorded activity" : "No event in loaded window" };
  });
  const values = info?.today && typeof info.today === "object" ? Object.values(info.today) : null;
  const calls = values && values.every(v => number(v) !== null) ? values.reduce((a, b) => a + b, 0) : null;
  return { nodes, edges: EDGES, stale, receivedAt, eventCount: events.length,
    // Global daily numbers must never appear as selected-project expenditure.
    usage: key ? null : { calls, tokens: number(info?.tokens), estimatedUsd: number(info?.spent_usd) } };
}
