import { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import type { Entry, Top } from "./types";
import { getTop } from "./api";
import { Dock, type Tab } from "./components/Dock";
import { TokenSheet } from "./components/TokenSheet";
import { GemsView } from "./views/GemsView";
import { ListView } from "./views/ListView";
import { SearchView } from "./views/SearchView";

const TITLE: Record<Tab, string> = { gems: "Gems", early: "Early", scout: "Scout", profile: "Profile", search: "Search" };
const isTab = (s: string): s is Tab => s in TITLE;

function bootInitial(): string {
  try {
    const b = JSON.parse(document.getElementById("onchain-boot")?.textContent ?? "{}");
    return String(b.user?.email ?? b.email ?? "L").charAt(0).toUpperCase();
  } catch { return "L"; }
}

export function App() {
  const [tab, setTab] = useState<Tab>(() => { const h = location.hash.slice(1); return isTab(h) ? h : "gems"; });
  const [top, setTop] = useState<Top | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<Entry | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => { getTop().then(setTop).catch((e) => setErr(String(e.message ?? e))); }, []);
  useEffect(() => { history.replaceState(null, "", `${location.search}#${tab}`); window.scrollTo(0, 0); }, [tab]);
  const scan = (s: string) => { setQ(s); setTab("search"); };

  return (
    <MotionConfig reducedMotion="user">
      <main className="mx-auto max-w-xl px-4 pb-[calc(104px+env(safe-area-inset-bottom))] pt-[calc(env(safe-area-inset-top)+18px)]">
        <h1 className="mb-4 text-[40px] font-bold leading-none tracking-tight">{TITLE[tab]}</h1>
        {err && <p className="rounded-2xl bg-down/10 p-4 text-down">Could not load the Top: {err}</p>}
        {!top && !err && <Skeleton />}
        {top && (
          <AnimatePresence mode="wait">
            <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}>
              {tab === "gems" && <GemsView top={top} onOpen={setOpen} onScan={scan} />}
              {tab === "early" && <ListView rows={top.early} onOpen={setOpen}
                intro="Young projects with the right signals, before they reach the arenas." empty="No early project right now." />}
              {tab === "search" && <SearchView top={top} q={q} onScan={setQ} onOpen={setOpen} />}
              {(tab === "scout" || tab === "profile") && (
                <p className="py-8 text-center text-[14px] text-ink-2">
                  {TITLE[tab]} moves here in a next step. Until then it is in the <a className="underline" href={`/onchain-app.html#${tab === "scout" ? "agent" : "profile"}`}>current app</a>.
                </p>
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </main>
      <Dock tab={tab} onTab={setTab} initial={bootInitial()} />
      <TokenSheet e={open} onClose={() => setOpen(null)} />
    </MotionConfig>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-2.5">{[0, 1, 2].map((i) => <div key={i} className="h-[132px] animate-pulse rounded-[20px] bg-card" />)}</div>
      {Array.from({ length: 6 }, (_, i) => <div key={i} className="h-16 animate-pulse rounded-2xl bg-card" />)}
    </div>
  );
}
