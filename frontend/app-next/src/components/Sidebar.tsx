import { motion } from "motion/react";
import { ICONS, LABEL, type View } from "./Dock";
import { setLang, t, useLang } from "../lib/i18n";
import { useDarkTheme } from "../views/Profile";

export type Place = { v: View; sub?: "arenas" | "database"; label: string; icon?: View };

/** The desktop's dock: the same ink and sage, as a rail on the left with every
 *  place the phone keeps behind the avatar (Gems' segments, Quality, Scout, Profile). */
export function Sidebar({ view, sub, quality, initial, onGo }: {
  view: View; sub: "arenas" | "database"; quality: boolean; initial: string; onGo: (p: Place) => void;
}) {
  const groups: [string | null, Place[]][] = [
    [null, (["today", "sectors", "clusters", "watch", "search"] as View[]).map((v) => ({ v, label: LABEL[v] }))],
    ["Gems", [
      { v: "gems", sub: "arenas", label: "Arenas", icon: "gems" }, { v: "gems", sub: "database", label: "Database", icon: "rank" },
      { v: "pearl", label: "Pearl" }, { v: "top", label: "Early" }, { v: "rank", label: "Top 25", icon: "top" },
    ]],
    ["Engine", [...(quality ? [{ v: "quality" as View, label: "Quality" }] : []), { v: "agent", label: "Scout" }]],
  ];
  const on = (p: Place) => p.v === view && (p.v !== "gems" || p.sub === sub);
  return (
    <aside className="fixed bottom-3.5 left-3.5 top-3.5 z-30 hidden w-[224px] flex-col rounded-[28px] bg-ink px-3 py-5 text-[#aeb7a9] shadow-float desk:flex">
      <b className="px-3 text-[21px] font-bold tracking-[-0.04em] text-on-ink">DEGEN</b>
      <nav aria-label={t("Sections")} className="mt-5 min-h-0 flex-1 overflow-y-auto">
        {groups.map(([title, items]) => (
          <div key={title ?? "main"} className="mb-4">
            {title && <h2 className="mb-1 px-3 text-[10.5px] font-semibold uppercase tracking-[0.1em] opacity-60">{t(title)}</h2>}
            {items.map((p) => {
              const cur = on(p);
              return (
                <button key={p.label} type="button" onClick={() => onGo(p)} aria-current={cur || undefined}
                  className={`relative flex h-10 w-full items-center gap-3 rounded-full px-3 text-left text-[14px] transition-colors duration-200 ${cur ? "font-semibold text-ink" : "font-medium hover:text-on-ink"}`}>
                  {cur && <motion.span layoutId="rail-pill" className="absolute inset-0 rounded-full bg-sage" transition={{ type: "spring", stiffness: 520, damping: 42 }} />}
                  <svg viewBox="0 0 24 24" className="relative h-[18px] w-[18px] flex-none" fill="none" stroke="currentColor" strokeWidth={cur ? 2.1 : 1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[p.icon ?? p.v]}</svg>
                  <span className="relative truncate">{t(p.label)}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="flex items-center gap-2 border-t border-white/10 px-1 pt-3">
        <button type="button" onClick={() => onGo({ v: "profile", label: "Profile" })} aria-current={view === "profile" || undefined}
          className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-full p-1 pr-3 text-left text-[14px] ${view === "profile" ? "bg-sage font-semibold text-ink" : "font-medium hover:text-on-ink"}`}>
          <span className="grid h-8 w-8 flex-none place-items-center rounded-full bg-on-ink text-[13px] font-semibold text-ink">{initial}</span>
          <span className="truncate">{t("Profile")}</span>
        </button>
        <ThemePill />
        <LangPill />
      </div>
    </aside>
  );
}

function ThemePill() {
  const [dark, toggle] = useDarkTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? t("Switch to light theme") : t("Switch to dark theme")}
      title={dark ? t("Switch to light theme") : t("Switch to dark theme")}
      className="grid h-8 w-8 flex-none place-items-center rounded-full bg-white/10 text-[14px] text-on-ink transition-colors hover:bg-sage hover:text-ink"
    >
      {dark ? "☀" : "☾"}
    </button>
  );
}

function LangPill() {
  const lang = useLang();
  return (
    <div role="radiogroup" aria-label={t("Language")} className="flex rounded-full bg-white/10 p-0.5 text-[11px] font-semibold">
      {(["it", "en"] as const).map((l) => (
        <button key={l} type="button" role="radio" aria-checked={lang === l} onClick={() => setLang(l)}
          className={`h-7 w-8 rounded-full uppercase ${lang === l ? "bg-sage text-ink" : ""}`}>{l}</button>
      ))}
    </div>
  );
}
