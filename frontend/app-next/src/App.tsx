import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import * as api from "./lib/api";
import type { Arena, Gem, Project } from "./lib/types";
import { coverage, loadHidden, useNarratives } from "./lib/store";
import { Dock, LABEL, type View } from "./components/Dock";
import { setLang, t, useLang } from "./lib/i18n";
import { Top3 } from "./components/Top3";
import { Sheet } from "./components/Sheet";
import { gemId } from "./components/TokenRow";
import { Arenas } from "./views/Arenas";
import { Database } from "./views/Database";
import { GemList } from "./views/GemList";
import { Sectors } from "./views/Sectors";
import { Today } from "./views/Today";
import { getSectors, type SectorsView } from "./lib/sectors";
import { TokenPage, type Opened } from "./views/TokenPage";
import { Quality, qualityContext } from "./views/Quality";
import { Scout } from "./views/Scout";
import { Watch } from "./views/Watch";
import { Search } from "./views/Search";
import { TokenSheet } from "./views/TokenSheet";
import { Profile, syncAutoTheme, useDarkTheme } from "./views/Profile";
import { Clusters, appKey } from "./views/Clusters";
import { Sidebar } from "./components/Sidebar";
import { useDesk } from "./lib/desk";

const POLL_MS = 30_000;
const PEARL_MIN = 70;          // a "70" on screen is always a pearl
const PEARL_MAX_AGE_DAYS = 30;
const ALL: View[] = ["today", "sectors", "watch", "search", "gems", "pearl", "top", "rank", "quality", "agent", "clusters", "profile"];
// Direction A (Lorenzo 22/10 "come in questo pdf"): the dock holds Today,
// Sectors, Clusters, Watch and Search; the rest opens from the avatar.
const GEMS: View[] = ["gems", "pearl", "top", "rank"];
// On a computer these keep the list on the left with the token page beside it (the old desktop
// terminal, 29/09); the others are boards, and the page covers them.
const SPLIT: View[] = ["gems", "pearl", "top", "rank", "quality", "watch", "search"];
const LIST_W = 470;

// Read before the view's own hash replaces it.
const LINK = location.hash.match(/&token=([^:&]+):([^&]+)/);

type Data = { entries: Gem[]; early: Gem[]; arenas: Arena[] };

function boot(): { initial: string } {
  try {
    const b = JSON.parse(document.getElementById("onchain-boot")?.textContent ?? "{}");
    const u = b.user ?? {};
    return { initial: String(u.display_name || u.username || u.email || "?").charAt(0).toUpperCase() };
  } catch { return { initial: "?" }; }
}

export function App() {
  const [view, setView] = useState<View>(() => { const h = location.hash.slice(1).split("&")[0] as View; return ALL.includes(h) ? h : "today"; });
  const [sub, setSub] = useState<"arenas" | "database">("arenas");
  const [data, setData] = useState<Data | null>(null);
  const [sec, setSec] = useState<SectorsView | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpenRaw] = useState<Opened | null>(null);
  const [more, setMore] = useState(false);
  const [peek, setPeek] = useState<Opened | null>(null);
  const closePage = useCallback(() => setOpenRaw(null), []);
  const [quality, setQuality] = useState(false);
  const [sells, setSells] = useState<{ risk: number | null } | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const narr = useNarratives();
  const [{ initial }] = useState(boot);
  // The desktop opens a row straight on the token page beside the rail: the preview sheet is the phone's.
  const desk = useDesk();

  const load = useCallback(async () => {
    try {
      const top = await api.getTop(50, narr);
      // A page served before the arenas: one arena holding the whole list.
      const arenas = top.arenas ?? [{ key: "all", label: t("All projects"), heat: 0, size: top.entries.length, median: 0,
        entries: top.entries.map((e, i) => ({ ...e, arena_rank: i + 1, in: true })) }];
      setData({ entries: top.entries ?? [], early: top.early ?? [], arenas });
      setErr("");
    } catch (e) { setErr((e as Error).message); }
  }, [narr]);

  useEffect(() => { load(); const t = setInterval(() => document.visibilityState === "visible" && load(), POLL_MS); return () => clearInterval(t); }, [load]);
  useEffect(() => {
    syncAutoTheme();
    const id = window.setInterval(syncAutoTheme, 60_000);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onVis = () => { if (document.visibilityState === "visible") syncAutoTheme(); };
    document.addEventListener("visibilitychange", onVis);
    mq.addEventListener?.("change", syncAutoTheme);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", onVis); mq.removeEventListener?.("change", syncAutoTheme); };
  }, []);
  const wantSec = view === "today" || view === "sectors";
  useEffect(() => {
    if (!wantSec) return;
    const go = () => getSectors().then(setSec).catch((e) => setErr((e as Error).message));
    go();
    const t = setInterval(() => document.visibilityState === "visible" && go(), POLL_MS);
    return () => clearInterval(t);
  }, [wantSec]);
  useEffect(() => { loadHidden(); coverage().then((l) => setLabels(Object.fromEntries(l.map((n) => [n.key, n.label ?? n.key])))); }, []);
  // Quality is one account's (quality.js): its button shows only when the list answers.
  useEffect(() => { fetch("/api/onchain/quality").then((r) => setQuality(r.ok)).catch(() => {}); }, []);
  // Coordinated sells is one account's too (sells.js): a pill at the top of Scout, with the highest risk, opening the Clusters tab.
  useEffect(() => {
    api.getCoordinatedSells().then((d) => {
      const top = Math.max(-1, ...(d.reports ?? []).map((r) => r.risk?.score ?? -1));
      setSells({ risk: top < 0 ? null : top });
    }).catch(() => {});
  }, []);
  useEffect(() => { history.replaceState(null, "", `${location.pathname}${location.search}#${view}`); scrollTo(0, 0); }, [view]);
  // Escape closes the token page, as Back does on the phone.
  useEffect(() => {
    if (!open) return;
    const k = (ev: KeyboardEvent) => { if (ev.key === "Escape") history.state?.detail ? history.back() : closePage(); };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [open, closePage]);
  const split = desk && !!open && SPLIT.includes(view);

  const inGems = GEMS.includes(view);
  // Which tokens the app shows now, for the Clusters tab ("vedo piu di 200 cluster [...] i progetti in sectors sono 46").
  const inApp = useMemo(() => new Map([...(data?.entries ?? []).map((e) => [appKey(e.chain, e.token_address), "Top"] as const),
    ...(data?.early ?? []).map((e) => [appKey(e.chain, e.token_address), "Early"] as const)]), [data]);
  const podium = data ? [...data.entries].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 3) : [];
  const born = Date.now() / 1000 - PEARL_MAX_AGE_DAYS * 86400;
  const sc = (e: { score?: number }) => Math.round(e.score ?? 0);
  // Each list says where the token was seen, on the page's context line (top.js, projects.js register()).
  const openWith = (context: (e: Gem) => string) => (e: Gem) => (desk ? setOpenRaw : setPeek)({ e, context: context(e) });
  const setOpen = (o: Opened | null) => setOpenRaw(o);
  const byScore = data ? [...data.entries].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)) : [];
  const openArena = openWith((e) => {
    const a = data?.arenas.find((x) => x.entries.some((y) => gemId(y) === gemId(e)));
    return a ? `${a.label} · ${t("#{n} of {m}", { n: e.arena_rank ?? 0, m: a.size })} · ${t("score {n}", { n: sc(e) })}` : t("score {n}", { n: sc(e) });
  });
  const openRanked = openWith((e) => `Top 25 · #${byScore.findIndex((x) => gemId(x) === gemId(e)) + 1} · ${t("score {n}", { n: sc(e) })}`);
  const openProject = (p: Project) => (desk ? setOpenRaw : setPeek)({
    e: { chain: p.chain, token_address: p.token, symbol: p.symbol ?? "?", name: p.name, image: p.image, score: p.score, market_cap: p.mcap, liquidity_usd: p.liq },
    context: `Database · ${t("score {n}", { n: p.score == null ? "—" : Math.round(p.score) })} · ${p.status}${p.why ? ` · ${p.why}` : ""}` });

  // A shared link or an alert: #<view>&token=<chain>:<address>[&tab=why] opens that token.
  useEffect(() => {
    const m = LINK;
    if (!m) return;
    const chain = decodeURIComponent(m[1]), token = decodeURIComponent(m[2]);
    api.getToken(chain, token).then((r) => {
      const p = r.entry;
      setOpen({ e: { chain, token_address: token, symbol: p?.symbol ?? token.slice(0, 6), name: p?.name, image: p?.image, pair_address: p?.pair_address,
        pair_url: p?.pair_url, market_cap: p?.market_cap, change_24h: p?.change_24h, launched_at: p?.launched_at } });
    }).catch(() => {});
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <Sidebar view={view} sub={sub} quality={quality} initial={initial} onGo={(p) => { if (p.sub) setSub(p.sub); setView(p.v); }} />
      <main className="mx-auto max-w-xl px-4 pb-[calc(128px+env(safe-area-inset-bottom))] pt-[calc(env(safe-area-inset-top)+18px)] desk:ml-[238px] desk:mr-0 desk:max-w-none desk:px-10 desk:pb-16 desk:pt-9" style={split ? { width: LIST_W, paddingInline: 20 } : undefined}>
       <div className="desk:mx-auto desk:max-w-[1240px]">
        {(view !== "search" || desk) && (
          <header className="mb-3 flex items-center justify-between gap-3 desk:mb-5">
            <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.03em] desk:text-[34px]">{t(view === "gems" && desk ? (sub === "database" ? "Database" : "Arenas") : LABEL[view])}</h1>
            <span className="ml-auto flex items-center gap-1.5"><ThemeSwitch /><span className="desk:hidden"><LangSwitch /></span></span>
            <button type="button" onClick={() => setMore(true)} aria-label={t("Profile and more")}
              className="grid h-9 w-9 flex-none place-items-center rounded-full bg-ink text-[14px] font-semibold text-on-ink desk:hidden">{initial}</button>
            {inGems && desk && !split && <div className="w-[min(520px,50%)]"><Top3 list={podium} onOpen={openWith((e) => `Top 25 · ${t("score {n}", { n: sc(e) })}`)} /></div>}
          </header>
        )}
        {inGems && !desk && <Top3 list={podium} onOpen={openWith((e) => `Top 25 · ${t("score {n}", { n: sc(e) })}`)} />}
        {err && !data && <p className="rounded-2xl bg-card p-4 text-[14px] text-down">{t("Could not load the gems: {err}", { err })}</p>}
        <AnimatePresence mode="wait">
          <motion.div key={view} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }}
            className={view === "search" || view === "profile" ? "desk:max-w-[820px]" : ""}>
            {view === "today" && <Today data={sec} onOpen={openWith((e) => `${t("Today")} · ${(e as Gem & { sector?: string }).sector ?? t("Sectors")} · ${t("score {n}", { n: sc(e) })}`)} onSectors={() => setView("sectors")} onWatch={() => setView("watch")} early={data?.early.length ?? null} onEarly={() => setView("top")} />}
            {view === "sectors" && <Sectors data={sec} onOpen={openWith((e) => `${t("Sectors")} · ${e.arena_rank ? `#${e.arena_rank} · ` : ""}${t("score {n}", { n: sc(e) })}`)} />}
            {view === "watch" && <Watch data={sec} gems={data ? [...data.entries, ...data.early] : []} onOpen={openWith((e) => `${t("Watch")} · ${t("score {n}", { n: sc(e) })}`)} />}
            {view === "search" && <Search sectors={sec} onProject={openProject} onSector={() => setView("sectors")} onToken={(e) => setOpen({ e, context: t("Scan") })} />}
            {inGems && (
              <div className="flex gap-1 rounded-full bg-pill p-1 desk:hidden">
                {([["arenas", "Arenas", "gems"], ["database", "Database", "gems"], ["pearl", "Pearl", "pearl"], ["early", "Early", "top"], ["rank", "Top", "rank"]] as const).map(([s, label, v]) => {
                  const on = view === v && (v !== "gems" || sub === s);
                  return (
                    <button key={s} type="button" onClick={() => { if (v === "gems") setSub(s as "arenas" | "database"); setView(v); }} aria-pressed={on}
                      className={`relative h-9 min-w-0 flex-1 rounded-full text-[13.5px] font-medium transition-colors duration-200 ${on ? "text-text" : "text-text-2"}`}>
                      {on && <motion.span layoutId="gems-sub" className="absolute inset-0 rounded-full bg-card shadow-[0_1px_2px_rgb(0_0_0/.06)]" transition={{ type: "spring", stiffness: 520, damping: 42 }} />}
                      <span className="relative">{t(label)}</span>
                    </button>
                  );
                })}
              </div>
            )}
            {view === "gems" && (
              <>
                {sub === "arenas" ? (
                  <>
                    <ScanButton onClick={() => setView("search")} />
                    {data ? <Arenas arenas={data.arenas} filtered={narr.length > 0} labels={labels} onOpen={openArena} /> : <Skeleton />}
                  </>
                ) : <Database onOpen={openProject} scan={<ScanButton onClick={() => setView("search")} />} />}
              </>
            )}
            {view === "pearl" && data && (
              <GemList title={t("Pearl")} rule={t("Early gems scoring 70 or more, at most 30 days old")} badge="early" onOpen={openWith((e) => `${t("Pearl")} · ${t("score {n}", { n: sc(e) })}`)}
                lead={t("The best of Early: under $300k cap, every bar of the Top passed, and a score of at least 70. Small and risky. Research, not advice.")}
                empty={t("No Early gem of the last 30 days scores 70 or more right now. The list is refreshed by the nightly scan.")}
                rows={data.early.filter((e) => Math.round(e.score ?? 0) >= PEARL_MIN && (e.launched_at ?? 0) >= born)} />
            )}
            {view === "top" && data && (
              <GemList title="Early" rule={t("under $300k cap")} badge="early" onOpen={openWith((e) => `Early · ${t("score {n}", { n: sc(e) })}`)} rows={data.early}
                lead={t("Small projects that pass every other bar of the Top: real usage, holders, code and research. Smaller and riskier. Research, not advice.")}
                empty={t("No project under $300k passes the bars right now. The list is refreshed by the nightly scan.")} />
            )}
            {view === "rank" && data && (
              <GemList title={narr.length ? `Top 25 · ${narr.map((k) => labels[k] ?? k).join(", ")}` : "Top 25"} rule={t("the best gems by score")} ranked onOpen={openRanked} rows={data.entries}
                lead={t("The 25 highest scores among the gems that passed the checks: usage, holders, code, research and tokenomics. Market cap and 24h change live from DexScreener. Research, not advice.")}
                empty={t("The ranking is filling up: gems appear as they pass the checks.")} />
            )}
            {view === "quality" && <Quality onOpen={openWith(qualityContext)} />}
            {view === "agent" && <Scout sells={sells} onSells={() => setView("clusters")} />}
            {view === "clusters" && <Clusters onToken={(e) => setOpen({ e, context: t("Cluster check") })} inApp={inApp} />}
            {view === "profile" && <Profile onOpen={(e, context) => setPeek({ e, context })} />}
          </motion.div>
        </AnimatePresence>
       </div>
      </main>
      <Dock view={view} onView={setView} />
      <Sheet open={more} title={t("More")} onClose={() => setMore(false)}>
        <nav className="grid gap-1.5">
          {([["top", "Early", "Projects under $300k cap that pass every other bar"], ["gems", "Gems", "Arenas, Database, Pearl, Early and Top 25"], ...(quality ? [["quality", "Quality", "Quality 80 or more, to accept or discard"]] : []),
            ["agent", "Scout", "What the engine is doing, and every token's journey"], ["profile", "Profile", "Picture, name, theme and the picks' track record"]] as [View, string, string][]).map(([v, label, sub]) => (
            <button key={v} type="button" onClick={() => { setMore(false); setView(v); }} className="flex flex-col rounded-[16px] bg-bg px-4 py-3 text-left active:bg-pill">
              <b className="text-[16px] font-semibold">{t(label)}</b><small className="text-[13px] text-text-3">{t(sub)}</small>
            </button>
          ))}
        </nav>
      </Sheet>
      <TokenSheet open={peek} onClose={() => setPeek(null)} onFull={(o) => { setPeek(null); setOpen(o); }} />
      <div style={{ "--tp-left": split ? `${238 + LIST_W}px` : "238px" } as React.CSSProperties}>
        <AnimatePresence>{open && <TokenPage key={gemId(open.e)} open={open} onClose={closePage} />}</AnimatePresence>
      </div>
    </MotionConfig>
  );
}

function ScanButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="relative mt-3 flex h-12 w-full items-center rounded-full border border-line pl-5 text-left text-[16px] text-text-3">
      {t("Scan a token: ticker or address")}
      <span className="absolute right-1 top-1 grid h-10 w-10 place-items-center rounded-full bg-ink text-on-ink">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
      </span>
    </button>
  );
}

/** IT / EN (Lorenzo 22/10: "metti poi tastino per selezionare EN o IT"). */
function LangSwitch() {
  const lang = useLang();
  return (
    <div role="radiogroup" aria-label={t("Language")} className="flex rounded-full bg-pill p-0.5 text-[11.5px] font-semibold">
      {(["it", "en"] as const).map((l) => (
        <button key={l} type="button" role="radio" aria-checked={lang === l} onClick={() => setLang(l)}
          className={`h-7 w-8 rounded-full uppercase ${lang === l ? "bg-card text-text shadow-[0_1px_2px_rgb(0_0_0/.06)]" : "text-text-3"}`}>{l}</button>
      ))}
    </div>
  );
}

function ThemeSwitch() {
  const [dark, toggle] = useDarkTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? t("Switch to light theme") : t("Switch to dark theme")}
      title={dark ? t("Switch to light theme") : t("Switch to dark theme")}
      className="grid h-8 w-8 flex-none place-items-center rounded-full bg-pill text-[15px] text-text transition-colors hover:bg-ink hover:text-on-ink active:scale-95"
    >
      {dark ? "☀" : "☾"}
    </button>
  );
}

function Skeleton() {
  return <div className="mt-4 space-y-2">{Array.from({ length: 6 }, (_, i) => <div key={i} className="h-[72px] animate-pulse rounded-[20px] bg-card" />)}</div>;
}
