import { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import type { Entry, Top } from "./types";
import { getTop } from "./api";
import { Dock, type Tab } from "./components/Dock";
import { TokenSheet } from "./components/TokenSheet";
import { TodayView } from "./views/TodayView";
import { SectorsView } from "./views/SectorsView";
import { SearchView } from "./views/SearchView";

const TITLE: Record<Tab, string> = { today: "Today", sectors: "Sectors", watch: "Watch", search: "Search" };

export function App() {
  const [tab, setTab] = useState<Tab>(() => (location.hash.slice(1) as Tab) in TITLE ? (location.hash.slice(1) as Tab) : "today");
  const [top, setTop] = useState<Top | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<Entry | null>(null);

  useEffect(() => { getTop().then(setTop).catch((e) => setErr(String(e.message ?? e))); }, []);
  useEffect(() => { history.replaceState(null, "", `#${tab}`); }, [tab]);

  return (
    <MotionConfig reducedMotion="user">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line/60 bg-bg/80 px-4 pb-3 pt-[max(14px,env(safe-area-inset-top))] backdrop-blur-xl">
        <h1 className="text-[22px] font-semibold tracking-tight">{TITLE[tab]}</h1>
        <span className="rounded-full border border-line px-2.5 py-1 text-[11px] text-ink-dim">DEGEN · preview</span>
      </header>
      <main className="mx-auto max-w-2xl px-4 pb-32 pt-4">
        {err && <p className="rounded-xl bg-down/10 p-4 text-down">Could not load the Top: {err}</p>}
        {!top && !err && <Skeleton />}
        {top && (
          <AnimatePresence mode="wait">
            <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
              {tab === "today" && <TodayView top={top} onOpen={setOpen} />}
              {tab === "sectors" && <SectorsView top={top} onOpen={setOpen} />}
              {tab === "search" && <SearchView top={top} onOpen={setOpen} />}
              {tab === "watch" && <p className="p-6 text-center text-ink-dim">Your watchlist lands here next.</p>}
            </motion.div>
          </AnimatePresence>
        )}
      </main>
      <Dock tab={tab} onTab={setTab} />
      <TokenSheet e={open} onClose={() => setOpen(null)} />
    </MotionConfig>
  );
}

function Skeleton() {
  return (
    <ul className="space-y-2">
      {Array.from({ length: 8 }, (_, i) => <li key={i} className="h-14 animate-pulse rounded-xl bg-panel" />)}
    </ul>
  );
}
