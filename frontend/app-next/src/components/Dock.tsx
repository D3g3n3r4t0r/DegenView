import { motion } from "motion/react";

export type Tab = "today" | "sectors" | "watch" | "search";
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "today", label: "Today", icon: "M4 12h4l3-8 4 16 3-8h2" },
  { id: "sectors", label: "Sectors", icon: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" },
  { id: "watch", label: "Watch", icon: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zm10 3a3 3 0 100-6 3 3 0 000 6z" },
  { id: "search", label: "Search", icon: "M11 18a7 7 0 100-14 7 7 0 000 14zm9 3l-4.3-4.3" },
];

// Floating dock; the active pill slides between tabs (shared layout, transform only).
export function Dock({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 flex justify-center pb-[max(12px,env(safe-area-inset-bottom))]">
      <div className="flex gap-1 rounded-2xl border border-line bg-panel/85 p-1.5 shadow-2xl backdrop-blur-xl">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => onTab(t.id)} aria-current={tab === t.id}
            className={`relative flex w-[74px] flex-col items-center gap-0.5 rounded-xl py-1.5 text-[10px] transition-colors ${tab === t.id ? "text-ink" : "text-ink-faint hover:text-ink-dim"}`}>
            {tab === t.id && <motion.span layoutId="dock-pill" className="absolute inset-0 rounded-xl bg-raised"
              transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
            <svg viewBox="0 0 24 24" className="relative h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d={t.icon} />
            </svg>
            <span className="relative">{t.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}
