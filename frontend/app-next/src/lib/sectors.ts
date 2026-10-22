import type { Gem } from "./types";
import { ApiError, device } from "./api";
import { locale, t as tr } from "./i18n";

// /api/onchain/sectors (backend sectors.py): the arenas summed up per sector,
// and Today, what changed since about a day ago.
export type SectorGem = Gem & { z?: number | null };

export type Sector = {
  key: string; label: string; heat: number; size: number; median: number;
  strength: number; top_avg: number; change_24h: number | null; cap: number;
  momentum: number | null; top: SectorGem[]; entries: SectorGem[];
};

export type TodayKind = "champion" | "entered" | "dropped" | "moved";
export type TodayItem = { kind: TodayKind; text: string; detail: string; gem: Gem & { sector?: string } };
export type TodayView = { since: number | null; items: TodayItem[]; counts: Record<TodayKind, number> };
export type SectorsView = { sectors: Sector[]; today: TodayView; readings_since: number | null; momentum_ready: boolean };

let inFlight: Promise<SectorsView> | null = null;

export function getSectors(): Promise<SectorsView> {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    const r = await fetch("/api/onchain/sectors", { headers: device ? { "X-Device": device } : {}, signal: AbortSignal.timeout(15000) })
      .catch(() => { throw new ApiError(tr("network unreachable")); });
    if (r.status === 401) location.href = "/onchain-app.html";
    if (!r.ok) throw new ApiError(tr("error {n}", { n: r.status }), r.status);
    return r.json() as Promise<SectorsView>;
  })().finally(() => { inFlight = null; });
  return inFlight;
}

/** Changed since the last reading: the sectors whose champion changed. */
export const newChampions = (t: TodayView | undefined) =>
  new Set((t?.items ?? []).filter((i) => i.kind === "champion").map((i) => i.gem.sector ?? ""));

/** "since 21:04 yesterday" from a unix time. */
export function sinceText(t: number | null) {
  if (!t) return "";
  const d = new Date(t * 1000), now = new Date();
  const hm = d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date(now.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86400000);
  return days <= 0 ? tr("since {hm} today", { hm }) : days === 1 ? tr("since {hm} yesterday", { hm }) : tr("since {d}", { d: d.toLocaleDateString(locale(), { day: "numeric", month: "short" }) });
}
