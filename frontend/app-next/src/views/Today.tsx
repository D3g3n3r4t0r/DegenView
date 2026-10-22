import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { Gem } from "../lib/types";
import { type SectorsView, type TodayKind, sinceText } from "../lib/sectors";
import { Logo } from "../components/Logo";
import { gemId } from "../components/TokenRow";

const FILTERS: [TodayKind | "all", string][] = [["all", "All"], ["champion", "Champions"], ["entered", "New"], ["dropped", "Dropped"]];
const MARK: Record<TodayKind, string> = { champion: "text-up", entered: "text-up", dropped: "text-down", moved: "text-text-3" };
const PREVIEW = 4;

/** Today (direction A, Lorenzo 10/10 and 22/10): what changed since about a
 *  day ago, then a glance at the strongest sectors. */
export function Today({ data, onOpen, onSectors }: { data: SectorsView | null; onOpen: (e: Gem) => void; onSectors: () => void }) {
  const [filter, setFilter] = useState<TodayKind | "all">("all");
  if (!data) return <div className="mt-2 space-y-2">{Array.from({ length: 5 }, (_, i) => <div key={i} className="h-16 animate-pulse rounded-[20px] bg-card" />)}</div>;
  const t = data.today;
  const items = t.items.filter((i) => filter === "all" || i.kind === filter);
  const ranked = new Set(data.sectors.flatMap((s) => s.entries.filter((e) => e.in !== false).map(gemId))).size;
  return (
    <>
      <p className="text-[13px] text-text-2">
        {t.since ? `${ranked} projects ranked · ${t.items.length} changes ${sinceText(t.since)}` : `${ranked} projects ranked`}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat label="New champions" v={t.counts.champion} />
        <Stat label="Dropped" v={t.counts.dropped} />
      </div>
      {t.since ? (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {FILTERS.map(([k, label]) => {
              const n = k === "all" ? t.items.length : t.counts[k];
              return (
                <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)} disabled={!n && k !== "all"}
                  className={`h-8 rounded-full px-3 text-[13px] font-medium disabled:opacity-40 ${filter === k ? "bg-ink text-on-ink" : "bg-pill text-text-2"}`}>
                  {label}{k !== "all" && n ? ` ${n}` : ""}
                </button>
              );
            })}
          </div>
          <ol className="mt-3 rounded-[20px] bg-card p-1.5">
            <AnimatePresence initial={false}>
              {items.map((i, n) => (
                <motion.li key={`${i.kind}:${gemId(i.gem)}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  transition={{ duration: 0.2, delay: Math.min(n, 8) * 0.02 }}>
                  <button type="button" onClick={() => i.kind !== "dropped" && onOpen(i.gem)} disabled={i.kind === "dropped"}
                    className="flex w-full items-center gap-3 rounded-[16px] px-2 py-2 text-left active:bg-pill disabled:active:bg-transparent">
                    <Logo size={38} symbol={i.gem.symbol} image={i.gem.image} chain={i.gem.chain} token={i.gem.token_address} />
                    <span className="min-w-0 flex-1">
                      <b className="block truncate text-[15px] font-medium leading-tight">{i.text}</b>
                      <small className="num block truncate text-[12.5px] text-text-2">{i.detail}</small>
                    </span>
                    <span className={`text-[11px] font-semibold uppercase tracking-wide ${MARK[i.kind]}`}>{i.kind === "entered" ? "new" : i.kind === "champion" ? "♛" : i.kind}</span>
                  </button>
                </motion.li>
              ))}
            </AnimatePresence>
            {!items.length && <li className="px-2 py-4 text-[14px] text-text-2">Nothing changed {sinceText(t.since)}.</li>}
          </ol>
        </>
      ) : (
        <p className="mt-3 rounded-[20px] bg-card p-4 text-[14px] text-text-2">
          Today compares the ranking with about a day ago. The first reading is saved now: changes show up after the next research run.
        </p>
      )}
      <div className="mt-5 flex items-baseline">
        <h2 className="flex-1 text-[11.5px] font-medium uppercase tracking-[0.07em] text-text-3">Strongest sectors</h2>
        <button type="button" onClick={onSectors} className="text-[13px] font-medium text-text-2">All sectors ›</button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {data.sectors.slice(0, PREVIEW).map((s) => (
          <button key={s.key} type="button" onClick={() => onOpen(s.top[0])} className="flex min-w-0 flex-col gap-1.5 rounded-[18px] bg-card p-3 text-left">
            <span className="truncate text-[11px] font-medium uppercase tracking-[0.07em] text-text-3">{s.label}</span>
            <span className="flex min-w-0 items-center gap-2">
              <Logo size={30} symbol={s.top[0].symbol} image={s.top[0].image} chain={s.top[0].chain} token={s.top[0].token_address} />
              <b className="min-w-0 flex-1 truncate text-[14px] font-semibold">{s.top[0].symbol}</b>
              <span className="num rounded-full bg-sage px-1.5 text-[11.5px] font-semibold text-on-sage">{Math.round(s.top[0].score ?? 0)}</span>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

function Stat({ label, v }: { label: string; v: number }) {
  return (
    <div className="rounded-[18px] bg-card px-3.5 py-2.5">
      <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-text-3">{label}</div>
      <div className="num text-[24px] font-semibold leading-tight">{v}</div>
    </div>
  );
}
