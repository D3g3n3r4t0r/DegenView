import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import type { ClusterLive, SellsReport } from "../lib/api";
import { CheckProgress, useClusterCheck } from "./CheckProgress";
import { t, locale } from "../lib/i18n";

// The bubble map lives once, in the classic app's static files: the same
// module draws it here (canvas, 60 fps, still with reduced motion).
const MAP_URL = "/static/onchain/cluster-map.js";
type MapApi = { highlight(a: Set<string> | null): void; update(r: SellsReport): void; destroy(): void };
type Pick = { address: string; share: number; cluster: { id: string }; label?: string | null; others?: number } | null;

const pct = (x?: number | null) => (x == null ? "—" : `${(x * 100).toFixed(x < 0.01 ? 2 : 1)}%`);
const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;
const when = (ts: number) => {
  const s = Date.now() / 1000 - ts;
  return s < 3600 ? t("{n}m ago", { n: Math.max(1, Math.round(s / 60)) }) : s < 86400 ? t("{n}h ago", { n: Math.round(s / 3600) })
    : new Date(ts * 1000).toLocaleDateString(locale(), { month: "short", day: "numeric" });
};
const liveSig = (l: ClusterLive) => `${l.holders?.length ?? 0}.${l.clusters?.length ?? 0}.${(l.clusters ?? []).reduce((s, c) => s + (c.edges?.length ?? 0) + c.wallets.length, 0)}.${l.events?.length ?? 0}`;
/** What a running check has read so far, as a report: its clusters, then
 *  every other holder in the grey top group. */
function fromLive(chain: string, token: string, l: ClusterLive): SellsReport {
  const share = new Map((l.holders ?? []).map((h) => [h.address, h.share ?? 0]));
  const inside = new Set((l.clusters ?? []).flatMap((c) => c.wallets));
  const clusters = (l.clusters ?? []).map((c) => ({ id: c.id, edges: c.edges, links: c.links, wallets: c.wallets.map((a) => ({ address: a, share: share.get(a) ?? 0 })),
    share: c.wallets.reduce((s, a) => s + (share.get(a) ?? 0), 0) }));
  const top = (l.holders ?? []).filter((h) => !inside.has(h.address));
  return { chain, token, clusters: top.length ? [...clusters, { id: "top", wallets: top }] : clusters, events: [...(l.events ?? [])].sort((a, b) => b.ts - a.ts) };
}
const riskBadgeTone = (s?: number | null) =>
  s == null ? "bg-pill text-text-3" : s >= 60 ? "bg-down/15 text-down" : s >= 30 ? "bg-amber/15 text-amber" : "bg-up/15 text-up";
const riskBarTone = (s?: number | null) =>
  s == null ? "bg-text-3" : s >= 60 ? "bg-down" : s >= 30 ? "bg-amber" : "bg-up";
const riskLabel = (s?: number | null) =>
  s == null ? "—" : s >= 60 ? t("High") : s >= 30 ? t("Medium") : t("Low");

/** Coordinated sells of one token: its wallet clusters as bubbles and the
 *  waves they sold in; without a report, where its check stands. */
export function SellsMap({ chain, token, starting = false, bare = false }: { chain: string; token: string; starting?: boolean; bare?: boolean }) {
  const [bump, setBump] = useState(0);
  const { rep: done, check } = useClusterCheck(chain, token, starting, bump);
  // While the check runs, what it has read so far is drawn and fills in.
  const sig = check?.live ? liveSig(check.live) : "";
  // The last live picture stays until the report replaces it (live goes when the run ends).
  const last = useRef<SellsReport | null>(null);
  const rep = useMemo(() => done ?? (last.current = check?.live ? fromLive(chain, token, check.live) : last.current), [done, sig]);
  const [pick, setPick] = useState<Pick>(null);
  const [copied, setCopied] = useState(false);
  const [lit, setLit] = useState<number | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<MapApi | null>(null);
  const has = !!rep && rep.clusters.some((c) => c.wallets.length);

  useEffect(() => {
    if (!has || !host.current) return;
    if (map.current) { map.current.update(rep!); return; }
    let gone = false;
    import(/* @vite-ignore */ MAP_URL).then((m) => {
      if (gone || !host.current) return;
      map.current = m.clusterMap(host.current, rep, { onPick: setPick, words: { cluster: t("Cluster"), wallets: t("wallets"), nolink: t("No link found"), none: t("No linked wallets among the top holders."), together: t("Sold together"), thicker: t("thicker line = more waves together") } });
    }).catch(() => {});
    return () => { gone = true; };
  }, [rep, has]);
  useEffect(() => () => { map.current?.destroy(); map.current = null; }, []);

  if (!rep || !has) {
    if (!check && !starting) return null;
    return (
      <section className={bare ? "" : "mt-5"}>
        {!bare && <h3 className="mb-2 text-[11.5px] font-medium uppercase tracking-[0.07em] text-text-3">{t("Coordinated sells")}</h3>}
        <CheckProgress check={check} chain={chain} token={token} onStarted={() => setBump((b) => b + 1)} />
        {bare && <div className="cp-empty mt-3 grid h-[280px] place-items-center rounded-[16px] bg-card text-[13px] text-text-3">{t("The map fills in as holders are read")}</div>}
      </section>
    );
  }
  const real = rep.clusters.filter((c) => c.id !== "top");
  const name = (id: string) => (id === "top" ? t("Top holders") : `Cluster ${real.findIndex((c) => c.id === id) + 1}`);
  const waves = rep.events.slice(0, 6);
  const score = rep.risk?.score;
  const pickedCluster = pick ? rep.clusters.find((c) => c.id === pick.cluster.id) : null;

  const copyAddr = (addr: string) => {
    navigator.clipboard?.writeText(addr).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  };

  const light = (i: number) => {
    const next = lit === i ? null : i;
    setLit(next);
    const e = next == null ? null : waves[next];
    const c = e && rep.clusters.find((x) => x.id === e.cluster);
    map.current?.highlight(e ? new Set(e.sellers?.length ? e.sellers : (c?.wallets ?? []).map((w) => w.address)) : null);
  };

  return (
    <section className={bare ? "" : "mt-5"}>
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[11.5px] font-medium uppercase tracking-[0.07em] text-text-3">
          {t("Coordinated sells")}
        </h3>
        <div className="flex items-center gap-2">
          {done && score != null && (
            <div className="flex items-center gap-1.5" aria-label={t("Risk gauge")}>
              <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-pill">
                <i
                  className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ${riskBarTone(score)}`}
                  style={{ width: `${Math.min(100, Math.max(4, Math.round(score)))}%` }}
                />
              </span>
            </div>
          )}
          <span className={`num inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${done ? riskBadgeTone(score) : "bg-amber/15 text-amber"}`}>
            {done
              ? score == null
                ? t("risk {n}", { n: "—" })
                : `${Math.round(score)}/100 · ${riskLabel(score)}`
              : t("live")}
          </span>
        </div>
      </div>

      {!done && <div className="mb-3"><CheckProgress check={check} chain={chain} token={token} onStarted={() => setBump((b) => b + 1)} /></div>}
      <div ref={host} className="overflow-hidden rounded-[16px] bg-card" aria-label={t("Wallet bubble map")} />

      {pick ? (
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 rounded-[14px] bg-card px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--c-line)]">
          {pick.label ? (
            <div className="min-w-0 flex-1">
              <b className="block text-[13.5px] font-semibold text-text">
                {t("{n} smaller holders, no link found", { n: pick.others ?? 0 })}
              </b>
              <small className="text-[12px] text-text-3">
                {t("{p} of supply", { p: pct(pick.share) })}
              </small>
            </div>
          ) : (
            <>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <b className="font-mono text-[13.5px] font-semibold text-text">{short(pick.address)}</b>
                  <span className="rounded-full bg-pill px-2 py-0.5 text-[11px] font-medium text-text-2">
                    {pick.cluster.id === "top" ? t("top holder, no link found") : name(pick.cluster.id)}
                  </span>
                </div>
                <small className="mt-0.5 block text-[12px] text-text-3">
                  {t("Wallet holds {p} of supply", { p: pct(pick.share) })}
                  {pickedCluster && pick.cluster.id !== "top" && pickedCluster.share != null
                    ? ` · ${t("Cluster share {p}", { p: pct(pickedCluster.share) })}`
                    : ""}
                </small>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => copyAddr(pick.address)}
                  className="rounded-full bg-sage px-2.5 py-1 text-[11.5px] font-semibold text-on-sage transition-opacity hover:opacity-90"
                >
                  {copied ? t("Copied ✓") : t("Copy address")}
                </button>
              </div>
            </>
          )}
        </div>
      ) : (
        <p className="mt-1.5 min-h-[1.4em] text-[12.5px] text-text-3">
          {t("Bubble size = share of supply. Tap a bubble or a sell.")}
        </p>
      )}

      {waves.length > 0 && (
        <ol className="mt-2.5 space-y-1.5">
          {waves.map((e, i) => (
            <motion.li
              key={e.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18, delay: i * 0.03 }}
            >
              <button
                type="button"
                onClick={() => light(i)}
                aria-pressed={lit === i}
                className={`flex w-full items-baseline gap-3 rounded-[14px] bg-card px-3.5 py-2.5 text-left transition-all ${
                  lit === i
                    ? "shadow-[inset_0_0_0_1.5px_var(--c-sage)]"
                    : lit != null
                      ? "opacity-45"
                      : "hover:bg-pill/60"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <b className="block text-[14px] font-semibold">{t("{who} sold {p}", { who: name(e.cluster), p: pct(e.share_sold) })}</b>
                  <small className="text-[12.5px] text-text-3">
                    {t("{n} wallets", { n: e.sellers?.length || e.wallets })}
                    {e.window_s ? ` ${t("in")} ${e.window_s >= 60 ? `${Math.round(e.window_s / 60)} min` : `${Math.round(e.window_s)} s`}` : ""}
                  </small>
                </span>
                <time className="num text-[12px] font-medium text-text-3">{when(e.ts)}</time>
              </button>
            </motion.li>
          ))}
        </ol>
      )}
    </section>
  );
}
