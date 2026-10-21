import { AnimatePresence, motion } from "motion/react";
import type { Arena, Entry } from "../types";
import { TokenRow } from "./TokenRow";

// Same mosaic as the current app (onchain-v1/top.js): the biggest arenas take
// the biggest tiles, the colour is the median 24h move of their projects.
const SPANS = [[4, 3], [2, 3], [3, 2], [3, 2], [2, 2], [2, 2], [2, 2]];
const MAX = 13;
const SHORT: Record<string, string> = {
  "Perps & Derivatives": "Perps", "Chains L0/L1/L2": "Chains", "Stablecoin Payments": "Payments",
  "Wallets & Account Abstraction": "Wallets", "NFT & Collectibles": "NFT", "Lending & Credit": "Lending",
  "Music & Media": "Music", "Dev Tools & RPC": "Dev tools", "Yield & Vaults": "Yield",
  "Robotics / Physical AI": "Robotics", "Identity / Personhood": "Identity", "AI Data / Oracles": "AI Data",
  "Prediction Markets": "Predictions", "Chain Abstraction": "Chain Abstr.", "AI-Managed Money": "AI Money",
};

function median(a: Arena): number | null {
  const xs = a.entries.map((e) => e.change_24h).filter((v): v is number => v != null).sort((x, y) => x - y);
  if (!xs.length) return null;
  const m = xs.length >> 1;
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
}
const tone = (ch: number | null) =>
  ch == null ? "bg-card" : ch >= 3 ? "bg-up/10" : ch >= 0.5 ? "bg-up/5" : ch <= -3 ? "bg-down/10" : ch <= -0.5 ? "bg-down/5" : "bg-card";

export function Mosaic({ arenas, open, onPick, all, onAll, onOpen }: {
  arenas: Arena[]; open: string | null; onPick: (k: string | null) => void;
  all: boolean; onAll: () => void; onOpen: (e: Entry) => void;
}) {
  if (!arenas.length) return null;
  const list = [...arenas].sort((a, b) => b.entries.length - a.entries.length);
  const cut = all || list.length <= MAX ? list.length : MAX - 1;
  const picked = open ? arenas.find((a) => a.key === open) : null;
  return (
    <>
      <p className="mx-0.5 mb-3 mt-4 text-[15px] leading-snug text-ink-2">Each tile is a narrative: its projects compete only with each other. Tap one for its ranking.</p>
      <div className="grid auto-rows-[48px] grid-flow-dense grid-cols-6 gap-2" role="group" aria-label="Arenas">
        {list.slice(0, cut).map((a, i) => {
          const [c, r] = SPANS[i] ?? [2, 1];
          const n = a.entries.length, ch = median(a), lead = a.entries[0];
          const sel = a.key === open;
          return (
            <motion.button key={a.key} onClick={() => onPick(sel ? null : a.key)} aria-expanded={sel}
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} whileTap={{ scale: 0.98 }}
              transition={{ delay: Math.min(i, 8) * 0.03, duration: 0.26 }}
              style={{ gridColumn: `span ${c}`, gridRow: `span ${r}` }}
              className={`flex min-w-0 flex-col justify-between overflow-hidden ${r > 1 ? "rounded-[20px]" : "rounded-2xl"} border px-3 ${r > 1 ? "py-2.5" : "py-1.5"} text-left ${tone(ch)} ${sel ? "border-ink" : "border-transparent"}`}>
              <b className="truncate text-[14px] font-medium">{SHORT[a.label] ?? a.label}</b>
              {r > 1 ? (
                <>
                  <span className="num text-[26px] font-medium leading-none">{n}<em className="ml-1 text-[11px] not-italic tracking-wide text-ink-3">projects</em></span>
                  <small className="truncate text-[11px] text-ink-3">
                    {lead ? `♛ ${lead.symbol}` : "searching"}
                    {ch != null && <span className={ch >= 0 ? "text-up" : "text-down"}> {ch >= 0 ? "+" : "−"}{Math.abs(ch).toFixed(Math.abs(ch) < 10 ? 1 : 0)}%</span>}
                  </small>
                </>
              ) : <small className="truncate text-[11px] text-ink-3">{n} · {lead ? `♛ ${lead.symbol}` : "searching"}</small>}
            </motion.button>
          );
        })}
        {cut < list.length && (
          <button onClick={onAll} style={{ gridColumn: "span 2" }} className="flex flex-col justify-between rounded-2xl bg-card px-3 py-1.5 text-left">
            <b className="text-[14px] font-medium text-ink-2">+ {list.length - cut} more</b>
            <small className="text-[11px] text-ink-3">smaller arenas</small>
          </button>
        )}
      </div>
      <p className="mx-0.5 mt-2 flex justify-between text-[10.5px] text-ink-3">
        <span>♛ leader · size = projects</span>
        <span><i className="not-italic text-up">■</i> up 24h <i className="not-italic text-down">■</i> down 24h</span>
      </p>
      <AnimatePresence mode="wait">
        {picked && (
          <motion.section key={picked.key} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.26 }} className="mt-5">
            <header className="mb-1 flex items-baseline justify-between">
              <h4 className="text-[20px] font-semibold">{picked.label}</h4>
              <span className="num text-[12px] text-ink-3">{picked.entries.length} projects{picked.median != null && ` · median ${Math.round(picked.median)}`}</span>
            </header>
            {picked.entries.length
              ? <ol>{picked.entries.map((e, i) => <TokenRow key={e.chain + e.token_address} e={e} rank={e.arena_rank ?? i + 1} i={i} onOpen={onOpen} />)}</ol>
              : <p className="py-4 text-[14px] text-ink-2">No {picked.label} project has passed the checks yet: they appear here as the research finds them.</p>}
          </motion.section>
        )}
      </AnimatePresence>
    </>
  );
}
