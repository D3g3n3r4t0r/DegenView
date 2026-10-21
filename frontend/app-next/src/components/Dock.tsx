import { motion } from "motion/react";

export type Tab = "gems" | "early" | "scout" | "profile" | "search";
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "gems", label: "Gems", icon: <><circle cx="9.5" cy="10" r="6" /><path d="M15.2 8.4a6 6 0 1 1-6.8 8.3" /></> },
  { id: "early", label: "Early", icon: <><path d="M12 20v-8" /><path d="M12 12c0-3.5-2.5-6-6.5-6 0 3.5 2.5 6 6.5 6Z" /><path d="M12 13.5c0-3 2.2-5.5 6.5-5.5 0 3-2.2 5.5-6.5 5.5Z" /></> },
  { id: "scout", label: "Scout", icon: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.5" /><circle cx="12" cy="12" r="1" fill="currentColor" /></> },
];
const SHADOW = "shadow-[0_8px_24px_rgb(47_58_50/.18)]";

// The current app's floating deep green bar and round search button; the
// sage pill now slides to the chosen tab instead of jumping.
export function Dock({ tab, onTab, initial }: { tab: Tab; onTab: (t: Tab) => void; initial: string }) {
  const item = (id: Tab, label: string, icon: React.ReactNode) => (
    <button key={id} onClick={() => onTab(id)} aria-current={tab === id || undefined} aria-label={label}
      className={`relative flex h-14 flex-1 flex-col items-center justify-center gap-1 rounded-full transition-colors duration-200 ${tab === id ? "text-ink" : "text-on-ink/70"}`}>
      {tab === id && <motion.span layoutId="dock-pill" className="absolute inset-0 rounded-full bg-sage" transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
      <span className="relative h-[22px] w-[22px]">{icon}</span>
      <span className="relative text-[11px] font-medium leading-none">{label}</span>
    </button>
  );
  const svg = (paths: React.ReactNode) => (
    <svg viewBox="0 0 24 24" className="h-full w-full" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">{paths}</svg>
  );
  return (
    <>
      <nav aria-label="Sections"
        className={`fixed bottom-[calc(14px+env(safe-area-inset-bottom))] left-4 z-30 flex h-16 w-[calc(100vw-32px-70px)] gap-0.5 rounded-full border border-ink bg-ink p-1 ${SHADOW}`}>
        {TABS.map((t) => item(t.id, t.label, svg(t.icon)))}
        {item("profile", "Profile", <i className="grid h-full w-full place-items-center rounded-full bg-press text-[11px] not-italic text-ink">{initial}</i>)}
      </nav>
      <button onClick={() => onTab("search")} aria-label="Search a token"
        className={`fixed bottom-[calc(14px+env(safe-area-inset-bottom))] right-4 z-30 grid h-16 w-16 place-items-center rounded-full border border-ink bg-ink text-on-ink ${SHADOW}`}>
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" /></svg>
      </button>
    </>
  );
}
