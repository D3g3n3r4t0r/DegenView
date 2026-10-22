// `npm run dev` + `?mock`: every /api call answered from mock/*.json, for
// screenshots without a backend. Loaded only in dev (main.tsx), never built.
import top from "../mock/top.json";
import projects from "../mock/projects.json";
import token from "../mock/token.json";
import chart from "../mock/chart.json";
import quality from "../mock/quality.json";
import agent from "../mock/agent.json";
import agentLog from "../mock/agent-log.json";
import journey from "../mock/journey.json";

type G = { score?: number; change_24h?: number; market_cap?: number; arena_rank?: number; symbol?: string; arena_label?: string };
type A = { key: string; label: string; heat: number; size: number; median: number; entries: G[] };

function sectors() {
  const now = Date.now() / 1000;
  const list = (top.arenas as unknown as A[]).map((a, i) => {
    const e = [...a.entries].sort((x, y) => (y.score ?? 0) - (x.score ?? 0)).map((g, j) => ({ ...g, arena_rank: j + 1, z: 1.2 - j * 0.4 }));
    const t3 = e.slice(0, 3);
    return { key: a.key, label: a.label, heat: a.heat, size: a.size, median: a.median, strength: 1.4 - i * 0.12,
      top_avg: t3.reduce((s, g) => s + (g.score ?? 0), 0) / Math.max(1, t3.length),
      change_24h: [4.2, -2.1, 7.8, 0.6, -5.4, 1.9, 3.3, -0.8, 2.4][i] ?? 0,
      cap: e.reduce((s, g) => s + (g.market_cap ?? 0), 0), momentum: null, top: t3, entries: e };
  });
  const g = (s: number, k: number) => ({ ...list[s].top[k], sector: list[s].label });
  const items = [
    { kind: "champion", text: "", detail: "", gem: g(0, 0), args: { s: list[0].top[0].symbol, sector: list[0].label, was: list[0].top[1]?.symbol, n: 88 } },
    { kind: "entered", text: "", detail: "", gem: g(2, 1), args: { s: list[2].top[1].symbol, sector: list[2].label, n: 74 } },
    { kind: "moved", text: "", detail: "", gem: g(1, 0), args: { s: list[1].top[0].symbol, sector: list[1].label, d: 6, a: 77, b: 83 } },
    { kind: "moved", text: "", detail: "", gem: g(4, 1), args: { s: list[4].top[1].symbol, sector: list[4].label, d: -5, a: 71, b: 66 } },
  ];
  return { sectors: list, today: { since: now - 86400, items, counts: { champion: 1, entered: 1, dropped: 0, moved: 2 } },
    readings_since: now - 9 * 86400, momentum_ready: false };
}

const ROUTES: [RegExp, () => unknown][] = [
  [/^\/api\/onchain\/top/, () => top],
  [/^\/api\/onchain\/sectors/, sectors],
  [/^\/api\/onchain\/projects/, () => projects],
  [/^\/api\/onchain\/token\?/, () => token],
  [/^\/api\/onchain\/chart/, () => chart],
  [/^\/api\/onchain\/quality/, () => quality],
  [/^\/api\/agent\/log/, () => agentLog],
  [/^\/api\/agent\/journey/, () => journey],
  [/^\/api\/agent$/, () => agent],
  [/^\/api\/onchain\/coordinated-sells$/, () => ({ reports: [] })],
  [/^\/api\/onchain\/narratives\/coverage/, () => ({ items: (top.arenas as unknown as A[]).map((a) => ({ key: a.key, label: a.label, projects: a.size })) })],
  [/^\/api\/profile\/hidden/, () => ({ hidden: [] })],
  [/^\/api\/profile$/, () => ({ profile: { display_name: "Lorenzo", handle: "lorenzo", bio: "", joined: 1767000000 } })],
  [/^\/api\/onchain\/track/, () => ({ stats: { horizons: [] }, picks: [], missed: [] })],
  [/^\/api\/onchain\/clusters\/queue/, () => ({ running: [], queue: [], queued: 0, built_today: 3, max_per_day: 0, log: [], now: Date.now() / 1000 })],
  [/^\/api\/onchain\/alerts\//, () => ({ items: [] })],
];

const real = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url;
  if (!url.startsWith("/api/")) return real(input, init);
  const hit = ROUTES.find(([re]) => re.test(url));
  await new Promise((r) => setTimeout(r, 120));
  return hit
    ? new Response(JSON.stringify(hit[1]()), { status: 200, headers: { "Content-Type": "application/json" } })
    : new Response(JSON.stringify({ detail: "not in the mock" }), { status: 404, headers: { "Content-Type": "application/json" } });
};
