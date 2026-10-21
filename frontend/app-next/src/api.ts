import type { Top } from "./types";
import { mockTop } from "./mock";

// `?mock` (or `npm run dev` with no backend) shows sample data, for screenshots.
const useMock = new URLSearchParams(location.search).has("mock");

export async function getTop(n = 50): Promise<Top> {
  if (useMock) return mockTop();
  const r = await fetch(`/api/onchain/top?n=${n}`, { credentials: "same-origin" });
  if (r.status === 401) { location.href = "/onchain-app.html"; throw new Error("login"); }
  if (!r.ok) throw new Error(`top ${r.status}`);
  const d = await r.json();
  return { entries: d.entries ?? [], early: d.early ?? [], arenas: d.arenas ?? [], p4p: d.p4p ?? [] };
}
