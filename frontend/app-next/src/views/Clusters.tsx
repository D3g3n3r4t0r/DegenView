import { useEffect, useState } from "react";
import * as api from "../lib/api";
import type { Gem } from "../lib/types";
import { ClusterCheck, resolveClusterInput } from "../components/ClusterCheck";
import { ClusterQueue } from "../components/ClusterQueue";
import { CheckProgress, useClusterCheck } from "../components/CheckProgress";
import { Logo } from "../components/Logo";
import { SellsMap } from "../components/SellsMap";
import { AnimatePresence, motion } from "motion/react";
import { t } from "../lib/i18n";

const short = (a: string) => (a.length > 12 ? `${a.slice(0, 4)}…${a.slice(-4)}` : a);
const ago = (ts?: number | null) => {
  if (!ts) return "—";
  const h = (Date.now() / 1000 - ts) / 3600;
  return h < 1 ? t("<1h ago") : h < 48 ? t("{n}h ago", { n: Math.round(h) }) : t("{n}d ago", { n: Math.round(h / 24) });
};
const pct = (x?: number | null) => (x == null ? "—" : `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`);
// The real clusters' share of supply (the "top" group is holders with no link found).
const held = (r: api.SellsReport) => r.clusters.filter((c) => c.id !== "top").reduce((s, c) => s + (c.share ?? 0), 0);
const realClusterCount = (r: api.SellsReport) => r.clusters.filter((c) => c.id !== "top").length;

type SortBy = "risk" | "cluster" | "wave";

/** The Clusters tab (Lorenzo, 22/10: "voglio una tab a parte, oltre ad averlo
 *  sui progetti"): every checked token, riskiest first, and a check by
 *  address. A row opens the token page with its bubble map and waves. */
export const appKey = (chain: string, token: string) => `${chain}:${token.startsWith("0x") ? token.toLowerCase() : token}`;

export function Clusters({ onToken, inApp }: { onToken: (e: Gem) => void; inApp?: Map<string, string> }) {
  const [q, setQ] = useState("");
  const [list, setList] = useState<api.SellsReport[] | null>(null);
  const [chain, setChain] = useState("all");
  const [sortBy, setSortBy] = useState<SortBy>("risk");
  // The engine checks every token the app ever showed: by default only the ones on screen now.
  const [scope, setScope] = useState<"app" | "all">("app");
  const [asked, setAsked] = useState<{ chain: string; token: string; symbol?: string; at: number } | null>(null);
  const [screen, setScreen] = useState(false);
  const s = q.trim();
  const sLow = s.toLowerCase();
  const resolvedQuery = s ? resolveClusterInput(s) : null;

  useEffect(() => {
    api.getCoordinatedSells().then((d) => setList(d.sample ? [] : d.reports ?? [])).catch(() => setList([]));
  }, []);

  const open = (c: string, token: string, symbol?: string) => onToken({ chain: c, token_address: token, symbol: symbol || short(token) } as Gem);
  const chains = [...new Set((list ?? []).map((r) => r.chain))];
  const here = (r: api.SellsReport) => inApp?.get(appKey(r.chain, r.token));
  const nApp = (list ?? []).filter(here).length;
  const all = scope === "all" || !inApp?.size;

  const matchesSearch = (r: api.SellsReport) => {
    if (!sLow) return true;
    const sym = (r.symbol || "").toLowerCase();
    const tok = (r.token || "").toLowerCase();
    const ch = (r.chain || "").toLowerCase();
    const normTok = resolvedQuery?.token?.toLowerCase() || "";
    return (
      sym.includes(sLow) ||
      tok.includes(sLow) ||
      ch.includes(sLow) ||
      (normTok.length > 0 && (tok.includes(normTok) || sym.includes((resolvedQuery?.symbol || "").toLowerCase())))
    );
  };

  const baseRows = (list ?? []).filter((r) => (all || here(r)) && (chain === "all" || r.chain === chain));
  const filteredRows = sLow ? baseRows.filter(matchesSearch) : baseRows;
  // If the user pasted a fresh address/URL that matches no existing checked token, keep showing filteredRows (or fall back to baseRows if it's a pure URL not in list? No, requirement says: filter by search query s (matching symbol, token address, or chain) when s is typed).
  const rows = [...filteredRows].sort((a, b) => {
    if (sortBy === "cluster") return held(b) - held(a);
    if (sortBy === "wave") return (b.events[0]?.ts ?? 0) - (a.events[0]?.ts ?? 0);
    return (b.risk?.score ?? -1) - (a.risk?.score ?? -1);
  });

  return (
    // Desktop: the check and the live engine on the left, the checked tokens on the right.
    <div className="desk:grid desk:grid-cols-2 desk:items-start desk:gap-8">
      <div>
        <label className="flex h-12 items-center gap-2 rounded-full bg-card px-4 shadow-[inset_0_0_0_1.5px_var(--c-ink)]">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("Paste a token address, explorer URL, or search checked tokens")}
            autoComplete="off"
            spellCheck={false}
            aria-label={t("Token address")}
            className="min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-text-3"
          />
          {q && (
            <button type="button" aria-label={t("Clear")} onClick={() => setQ("")} className="rounded-md bg-pill px-2 py-0.5 font-mono text-[12px] text-text-2">
              ✕
            </button>
          )}
        </label>
        <div className="mt-3">
          <ClusterCheck
            address={s}
            onStart={(c, tok, sym) => {
              setAsked({ chain: c, token: tok || s, symbol: sym, at: Date.now() });
              setScreen(true);
            }}
            onOpen={(g) => {
              setAsked((prev) => ({
                chain: g.chain,
                token: g.token_address,
                symbol: g.symbol,
                at: prev?.at ?? Date.now(),
              }));
              setQ("");
            }}
            onFail={() => {
              setAsked(null);
              setScreen(false);
            }}
          />
        </div>
        {asked && (
          <Asked
            key={asked.at}
            chain={asked.chain}
            token={asked.token}
            symbol={asked.symbol}
            onOpen={() => setScreen(true)}
            onReady={() =>
              api
                .getCoordinatedSells()
                .then((d) => setList(d.sample ? [] : d.reports ?? []))
                .catch(() => {})
            }
          />
        )}
        <AnimatePresence>
          {asked && screen && (
            <LiveCheck
              key={asked.at}
              chain={asked.chain}
              token={asked.token}
              symbol={asked.symbol}
              onClose={() => setScreen(false)}
              onOpen={() => {
                setScreen(false);
                open(asked.chain, asked.token, asked.symbol);
              }}
            />
          )}
        </AnimatePresence>

        <h2 className="mb-2 mt-5 text-[11.5px] font-medium uppercase tracking-[0.07em] text-text-3">{t("Live")}</h2>
        <ClusterQueue onOpen={open} />
      </div>

      <div>
        <div className="mb-2 mt-5 flex flex-wrap items-center gap-1.5 desk:mt-0">
          <h2 className="mr-auto text-[11.5px] font-medium uppercase tracking-[0.07em] text-text-3">{t("Checked, riskiest first")}</h2>
          {!!inApp?.size &&
            (
              [
                ["app", `${t("In the app")} ${nApp}`],
                ["all", `${t("All")} ${list?.length ?? 0}`],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                onClick={() => setScope(k)}
                aria-pressed={scope === k}
                className={`num rounded-full px-2.5 py-1 text-[12px] ${scope === k ? "bg-ink font-semibold text-on-ink" : "bg-pill text-text-2"}`}
              >
                {label}
              </button>
            ))}
        </div>

        <div className="mb-2 flex flex-wrap items-center justify-between gap-1.5">
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label={t("Sort by")}>
            {(
              [
                ["risk", t("Risk")],
                ["cluster", t("Cluster %")],
                ["wave", t("Recent wave")],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                onClick={() => setSortBy(k)}
                aria-pressed={sortBy === k}
                className={`rounded-full px-2.5 py-1 text-[11.5px] transition-colors ${
                  sortBy === k ? "bg-ink font-semibold text-on-ink" : "bg-pill text-text-2"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap justify-end gap-1">
            {chains.length > 1 &&
              ["all", ...chains].map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setChain(c)}
                  aria-pressed={chain === c}
                  className={`rounded-full px-2.5 py-1 text-[11.5px] capitalize ${chain === c ? "bg-ink font-semibold text-on-ink" : "bg-pill text-text-2"}`}
                >
                  {c === "all" ? t("All") : c}
                </button>
              ))}
          </div>
        </div>

        {list == null ? (
          <div className="h-16 animate-pulse rounded-[16px] bg-card" />
        ) : rows.length ? (
          <ol className="rounded-[16px] bg-card p-1.5">
            {rows.map((r, idx) => {
              const risk = r.risk?.score;
              const last = r.events[0];
              const clusterShare = held(r);
              const nClusters = realClusterCount(r);
              const sharePctWidth = Math.min(100, Math.max(4, Math.round(clusterShare * 100)));
              return (
                <motion.li
                  key={`${r.chain}:${r.token}`}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.15, delay: Math.min(idx * 0.02, 0.2) }}
                >
                  <button
                    type="button"
                    onClick={() => open(r.chain, r.token, r.symbol)}
                    className="flex w-full items-center gap-3 rounded-[12px] px-2.5 py-2.5 text-left transition-colors hover:bg-pill/60 active:bg-pill"
                  >
                    <Logo size={36} symbol={r.symbol || short(r.token)} chain={r.chain} token={r.token} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <b className="truncate text-[15px] font-semibold leading-tight">
                          {r.symbol || short(r.token)}{" "}
                          <span className="text-[12.5px] font-normal text-text-3">
                            · {r.chain}
                            {here(r) ? ` · ${t(here(r)!)}` : ""}
                          </span>
                        </b>
                        {nClusters > 0 && (
                          <span className="num flex-none rounded-full bg-pill px-2 py-0.5 text-[11px] font-medium text-text-2">
                            {nClusters} {nClusters === 1 ? t("cluster") : t("clusters")}
                          </span>
                        )}
                      </span>
                      <small className="mt-0.5 block truncate text-[12.5px] text-text-3">
                        {t("clusters hold {p}", { p: pct(clusterShare) })} ·{" "}
                        {last ? t("last wave {t}, {p} sold", { t: ago(last.ts), p: pct(last.share_sold) }) : t("no wave yet")}
                      </small>
                      <span className="mt-1.5 block h-1 w-28 overflow-hidden rounded-full bg-pill" aria-hidden="true">
                        <i
                          className={`block h-full rounded-full ${
                            clusterShare >= 0.35 ? "bg-down" : clusterShare >= 0.15 ? "bg-amber" : "bg-ink"
                          }`}
                          style={{ width: `${sharePctWidth}%` }}
                        />
                      </span>
                    </span>
                    {risk != null && (
                      <span
                        className={`num flex-none rounded-full px-2.5 py-1 text-[13px] font-semibold ${
                          risk >= 60 ? "bg-down/15 text-down" : risk >= 30 ? "bg-amber/15 text-amber" : "bg-pill text-text-2"
                        }`}
                      >
                        {Math.round(risk)}
                      </span>
                    )}
                  </button>
                </motion.li>
              );
            })}
          </ol>
        ) : (
          <p className="rounded-[16px] bg-card p-4 text-[14px] text-text-2">
            {sLow && baseRows.length
              ? t("No checked token matches your search. Start a new cluster check on the left.")
              : list.length
                ? t("No token here checked yet: see All.")
                : t("No token checked yet. Paste an address above.")}
          </p>
        )}
      </div>
    </div>
  );
}

/** The check just asked, live from the tap: steps and bar until its report lands. */
function Asked({
  chain,
  token,
  symbol,
  onOpen,
  onReady,
}: {
  chain: string;
  token: string;
  symbol?: string;
  onOpen: () => void;
  onReady: () => void;
}) {
  const { rep, check } = useClusterCheck(chain, token, true);
  useEffect(() => {
    if (rep) onReady();
  }, [rep]);
  const label = symbol ? `${symbol} · ${chain}` : `${short(token)} · ${chain}`;
  return (
    <button type="button" onClick={onOpen} className="mt-3 block w-full text-left">
      {rep ? (
        <span className="flex items-center rounded-[16px] bg-card p-4 text-[14px]">
          <b className="flex-1 font-semibold">
            {label}: {t("ready")}
          </b>
          <span className="text-[13px] text-text-3">{t("open ›")}</span>
        </span>
      ) : (
        <CheckProgress check={check} title={label} chain={chain} token={token} />
      )}
    </button>
  );
}

/** The check's own screen (Lorenzo, 22/10: "la schermata che si apre sulla
 *  tab dedicata con il grafico dei cluster che si compila"): steps, counters,
 *  and the bubble map filling in as holders, links and sells are read. */
function LiveCheck({
  chain,
  token,
  symbol,
  onClose,
  onOpen,
}: {
  chain: string;
  token: string;
  symbol?: string;
  onClose: () => void;
  onOpen: () => void;
}) {
  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-label={t("Cluster check")}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 12 }}
      transition={{ duration: 0.2 }}
      className="fixed inset-0 z-40 overflow-y-auto bg-bg desk:left-[238px]"
    >
      <div className="mx-auto max-w-[540px] px-4 pb-28 pt-[calc(12px+env(safe-area-inset-top))] desk:max-w-[1100px] desk:pt-9">
        <header className="mb-4 flex items-center gap-2">
          <button type="button" onClick={onClose} aria-label={t("Back")} className="grid h-10 w-10 place-items-center rounded-full bg-pill text-[18px]">
            ‹
          </button>
          <span className="min-w-0 flex-1">
            <b className="block text-[18px] font-semibold leading-tight">
              {symbol ? `${t("Cluster check")} · ${symbol}` : t("Cluster check")}
            </b>
            <small className="block truncate font-mono text-[12px] text-text-3">
              {chain} · {short(token)}
            </small>
          </span>
          <button type="button" onClick={onOpen} className="rounded-full bg-ink px-3.5 py-2 text-[13px] font-semibold text-on-ink">
            {t("Token page")}
          </button>
        </header>
        <SellsMap chain={chain} token={token} starting bare />
      </div>
    </motion.div>
  );
}
