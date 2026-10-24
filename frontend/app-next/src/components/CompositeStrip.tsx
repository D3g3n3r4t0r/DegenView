import { useEffect, useMemo, useState } from "react";
import { Sheet } from "./Sheet";
import { device } from "../lib/api";
import { changeText } from "../lib/format";
import { t } from "../lib/i18n";

export type CompositeCategory = "market_cap" | "dominance" | "ratio";
export type CompositeUnit = "B_USD" | "PCT" | "RATIO";
export type MacroRegime = "Altseason" | "BTC Season" | "Risk-Off" | "Macro Pulse";

export interface CompositeItem {
  symbol: string;
  name: string;
  category: CompositeCategory;
  unit: CompositeUnit;
  formula: string;
  description: string;
  value: number;
  change_24h: number;
  aliases: string[];
}

/** Built-in instant fallback list of all 20 TradingView Composite Indices (zero layout shift). */
export const FALLBACK_COMPOSITES: CompositeItem[] = [
  // Market Cap (8)
  {
    symbol: "TOTAL",
    name: "Crypto Total Market Cap",
    category: "market_cap",
    unit: "B_USD",
    formula: "BTC + ETH + Top 10 Alts + OTHERS + Stablecoins",
    description: "Total market capitalization of all cryptocurrencies.",
    value: 2680.4,
    change_24h: 1.4,
    aliases: ["CRYPTOCAP:TOTAL", "TOTAL1", "CRYPTO.TOTAL", "MARKET CAP"],
  },
  {
    symbol: "TOTAL2",
    name: "Crypto Total Market Cap Ex-BTC",
    category: "market_cap",
    unit: "B_USD",
    formula: "TOTAL - BTC",
    description: "Total cryptocurrency market capitalization excluding Bitcoin.",
    value: 1045.2,
    change_24h: 1.9,
    aliases: ["CRYPTOCAP:TOTAL2", "TOTAL.2", "ALTS MCAP"],
  },
  {
    symbol: "TOTAL3",
    name: "Crypto Total Market Cap Ex-BTC & ETH",
    category: "market_cap",
    unit: "B_USD",
    formula: "TOTAL - BTC - ETH",
    description: "Total altcoin market capitalization excluding Bitcoin and Ethereum.",
    value: 734.8,
    change_24h: 2.3,
    aliases: ["CRYPTOCAP:TOTAL3", "TOTAL.3"],
  },
  {
    symbol: "TOTALES",
    name: "Crypto Total Market Cap Ex-Stablecoins",
    category: "market_cap",
    unit: "B_USD",
    formula: "TOTAL - Stablecoins",
    description: "Total cryptocurrency market capitalization excluding stablecoins.",
    value: 2476.4,
    change_24h: 1.5,
    aliases: ["CRYPTOCAP:TOTALES", "TOTAL.ES", "TOTAL_ES"],
  },
  {
    symbol: "TOTAL2ES",
    name: "Crypto Total Market Cap Ex-BTC & Stablecoins",
    category: "market_cap",
    unit: "B_USD",
    formula: "TOTAL2 - Stablecoins",
    description: "Total altcoin market cap excluding Bitcoin and stablecoins.",
    value: 841.2,
    change_24h: 2.2,
    aliases: ["CRYPTOCAP:TOTAL2ES", "TOTAL2.ES", "TOTAL2_ES"],
  },
  {
    symbol: "TOTAL3ES",
    name: "Crypto Total Market Cap Ex-BTC, ETH & Stablecoins",
    category: "market_cap",
    unit: "B_USD",
    formula: "TOTAL3 - Stablecoins",
    description: "Pure altcoin market cap excluding Bitcoin, Ethereum, and stablecoins.",
    value: 530.8,
    change_24h: 2.8,
    aliases: ["CRYPTOCAP:TOTAL3ES", "TOTAL3.ES", "TOTAL3_ES"],
  },
  {
    symbol: "OTHERS",
    name: "Crypto Total Market Cap Ex-Top 10",
    category: "market_cap",
    unit: "B_USD",
    formula: "TOTAL - Top 10",
    description: "Altcoin mid/small-cap market capitalization excluding top 10 coins.",
    value: 284.6,
    change_24h: 3.1,
    aliases: ["CRYPTOCAP:OTHERS", "OTHERSMCAP"],
  },
  {
    symbol: "TOTALDEFI",
    name: "DeFi Total Market Cap",
    category: "market_cap",
    unit: "B_USD",
    formula: "DeFi Basket Market Cap",
    description: "Total decentralized finance (DeFi) market capitalization.",
    value: 96.4,
    change_24h: 2.5,
    aliases: ["CRYPTOCAP:TOTALDEFI", "DEFI.MCAP", "TOTAL.DEFI"],
  },

  // Dominance % (8)
  {
    symbol: "BTC.D",
    name: "Bitcoin Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "BTC / TOTAL × 100",
    description: "Bitcoin share of total cryptocurrency market capitalization.",
    value: 61.0,
    change_24h: -0.3,
    aliases: ["BTCD", "BTCDOM", "BTC.DOM", "CRYPTOCAP:BTC.D", "BITCOIN DOMINANCE"],
  },
  {
    symbol: "ETH.D",
    name: "Ethereum Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "ETH / TOTAL × 100",
    description: "Ethereum share of total cryptocurrency market capitalization.",
    value: 11.6,
    change_24h: 0.1,
    aliases: ["ETHD", "ETHDOM", "ETH.DOM", "CRYPTOCAP:ETH.D", "ETHEREUM DOMINANCE"],
  },
  {
    symbol: "USDT.D",
    name: "Tether USDT Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "USDT / TOTAL × 100",
    description: "Tether (USDT) share of total cryptocurrency market capitalization.",
    value: 5.32,
    change_24h: -0.8,
    aliases: ["USDTD", "USDTDOM", "USDT.DOM", "CRYPTOCAP:USDT.D", "TETHER DOMINANCE"],
  },
  {
    symbol: "USDC.D",
    name: "USD Coin Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "USDC / TOTAL × 100",
    description: "USD Coin (USDC) share of total cryptocurrency market capitalization.",
    value: 2.1,
    change_24h: -0.6,
    aliases: ["USDCD", "USDCDOM", "USDC.DOM", "CRYPTOCAP:USDC.D"],
  },
  {
    symbol: "STABLE.C.D",
    name: "Total Stablecoin Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "Stablecoins / TOTAL × 100",
    description: "Combined stablecoin (USDT + USDC + DAI) share of total crypto market cap.",
    value: 7.61,
    change_24h: -0.7,
    aliases: ["STABLE.D", "STABLED", "STABLES.D", "STABLESD", "CRYPTOCAP:STABLE.C.D", "STABLECOIN DOMINANCE"],
  },
  {
    symbol: "OTHERS.D",
    name: "Others (Ex-Top 10) Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "OTHERS / TOTAL × 100",
    description: "Mid/small-cap altcoin (ex-Top 10) share of total crypto market cap.",
    value: 10.62,
    change_24h: 1.2,
    aliases: ["OTHERSD", "OTHERSDOM", "OTHERS.DOM", "CRYPTOCAP:OTHERS.D"],
  },
  {
    symbol: "TOTAL3.D",
    name: "Total3 (Ex-BTC & ETH) Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "TOTAL3 / TOTAL × 100",
    description: "Altcoin (ex-BTC & ETH) share of total crypto market cap.",
    value: 27.41,
    change_24h: 0.8,
    aliases: ["TOTAL3D", "TOTAL3.DOM", "CRYPTOCAP:TOTAL3.D"],
  },
  {
    symbol: "ALTS.D",
    name: "Altcoin (Ex-BTC) Dominance",
    category: "dominance",
    unit: "PCT",
    formula: "TOTAL2 / TOTAL × 100",
    description: "Total altcoin (ex-BTC) share of total crypto market cap.",
    value: 39.0,
    change_24h: 0.5,
    aliases: ["ALTSD", "TOTAL2.D", "TOTAL2D", "ALTS.DOM", "CRYPTOCAP:TOTAL2.D"],
  },

  // Ratios & Rotations (4)
  {
    symbol: "ETHBTC",
    name: "Ethereum / Bitcoin Ratio",
    category: "ratio",
    unit: "RATIO",
    formula: "ETH / BTC",
    description: "Relative strength ratio of Ethereum priced in Bitcoin.",
    value: 0.0318,
    change_24h: 0.4,
    aliases: ["ETH.BTC", "ETH/BTC"],
  },
  {
    symbol: "SOLBTC",
    name: "Solana / Bitcoin Ratio",
    category: "ratio",
    unit: "RATIO",
    formula: "SOL / BTC",
    description: "Relative strength ratio of Solana priced in Bitcoin.",
    value: 0.00214,
    change_24h: 1.8,
    aliases: ["SOL.BTC", "SOL/BTC"],
  },
  {
    symbol: "SOLETH",
    name: "Solana / Ethereum Ratio",
    category: "ratio",
    unit: "RATIO",
    formula: "SOL / ETH",
    description: "Relative strength ratio of Solana priced in Ethereum.",
    value: 0.0673,
    change_24h: 1.4,
    aliases: ["SOL.ETH", "SOL/ETH"],
  },
  {
    symbol: "DEFIETH",
    name: "DeFi / Ethereum Rotation Index",
    category: "ratio",
    unit: "RATIO",
    formula: "TOTALDEFI / ETH_MCAP × 100",
    description: "DeFi total market cap relative to Ethereum market cap.",
    value: 31.1,
    change_24h: 0.9,
    aliases: ["DEFI.ETH", "DEFI/ETH", "TOTALDEFI/ETH"],
  },
];

/** Key tickers featured directly in the horizontal strip. */
export const STRIP_TICKERS: readonly string[] = [
  "TOTAL",
  "TOTAL2",
  "TOTAL3",
  "TOTALES",
  "OTHERS",
  "BTC.D",
  "ETH.D",
  "USDT.D",
  "STABLE.C.D",
  "OTHERS.D",
  "TOTAL3.D",
  "ETHBTC",
  "SOLBTC",
];

export const COMPOSITE_GROUPS: readonly {
  key: CompositeCategory;
  title: string;
  subtitle: string;
  symbols: readonly string[];
}[] = [
  {
    key: "market_cap",
    title: "Market Cap",
    subtitle: "Total & excluding BTC / ETH / Stablecoins / Top 10",
    symbols: ["TOTAL", "TOTAL2", "TOTAL3", "TOTALES", "TOTAL2ES", "TOTAL3ES", "OTHERS", "TOTALDEFI"],
  },
  {
    key: "dominance",
    title: "Dominance %",
    subtitle: "Share of total crypto market capitalization (0–100%)",
    symbols: ["BTC.D", "ETH.D", "USDT.D", "USDC.D", "STABLE.C.D", "OTHERS.D", "TOTAL3.D", "ALTS.D"],
  },
  {
    key: "ratio",
    title: "Ratios & Rotations",
    subtitle: "Cross-asset relative strength & capital rotation pairs",
    symbols: ["ETHBTC", "SOLBTC", "SOLETH", "DEFIETH"],
  },
];

export function formatCompositeValue(item: Pick<CompositeItem, "unit" | "value">): string {
  const v = Number(item.value);
  if (!Number.isFinite(v) || v <= 0) return "—";
  if (item.unit === "B_USD") {
    // Support either Billions USD (e.g. 2680.4) or raw USD (e.g. 2.68e12)
    const b = v >= 1e9 ? v / 1e9 : v;
    if (b >= 1000) return `$${(b / 1000).toFixed(2)}T`;
    if (b >= 100) return `$${b.toFixed(0)}B`;
    return `$${b.toFixed(1)}B`;
  }
  if (item.unit === "PCT") {
    return `${v.toFixed(v >= 10 ? 1 : 2)}%`;
  }
  if (v < 0.01) return v.toFixed(5);
  if (v < 1) return v.toFixed(4);
  return v.toFixed(2);
}

export function deriveMacroRegime(items: CompositeItem[], serverRegime?: string | null): MacroRegime {
  if (serverRegime) {
    const s = serverRegime.toLowerCase();
    if (s.includes("alt")) return "Altseason";
    if (s.includes("btc")) return "BTC Season";
    if (s.includes("risk") || s.includes("off") || s.includes("defensive")) return "Risk-Off";
    if (s.includes("pulse") || s.includes("neutral") || s.includes("macro")) return "Macro Pulse";
  }
  const bySym = new Map(items.map((i) => [i.symbol, i]));
  const totalChg = bySym.get("TOTAL")?.change_24h ?? 0;
  const btcDomChg = bySym.get("BTC.D")?.change_24h ?? 0;
  const othersDomChg = bySym.get("OTHERS.D")?.change_24h ?? 0;
  const total3DomChg = bySym.get("TOTAL3.D")?.change_24h ?? 0;
  const stableDomChg = bySym.get("STABLE.C.D")?.change_24h ?? bySym.get("USDT.D")?.change_24h ?? 0;

  if (stableDomChg >= 1.2 && totalChg <= -1.0) return "Risk-Off";
  if ((othersDomChg >= 0.4 || total3DomChg >= 0.4) && btcDomChg <= 0.1) return "Altseason";
  if (btcDomChg >= 0.35 && totalChg >= -0.5) return "BTC Season";
  return "Macro Pulse";
}

const REGIME_STYLE: Record<MacroRegime, { badge: string; dot: string; hint: string }> = {
  Altseason: {
    badge: "bg-sage text-on-sage",
    dot: "bg-up",
    hint: "Capital rotating into TOTAL3 & OTHERS faster than BTC",
  },
  "BTC Season": {
    badge: "bg-pill text-text",
    dot: "bg-amber",
    hint: "Bitcoin dominance expanding against altcoins",
  },
  "Risk-Off": {
    badge: "bg-pill text-down",
    dot: "bg-down",
    hint: "Stablecoin dominance rising as market de-risks",
  },
  "Macro Pulse": {
    badge: "bg-pill text-text-2",
    dot: "bg-text-3",
    hint: "Balanced liquidity across majors, alts, and stablecoins",
  },
};

interface SnapshotState {
  items: CompositeItem[];
  regime: MacroRegime;
  updatedAt: number;
}

let cachedSnapshot: SnapshotState = {
  items: FALLBACK_COMPOSITES,
  regime: deriveMacroRegime(FALLBACK_COMPOSITES),
  updatedAt: 0,
};
let inFlightSnapshot: Promise<SnapshotState> | null = null;
const SNAPSHOT_TTL_MS = 30_000;

function normalizeFormula(f?: string, fallback?: string): string {
  const raw = f || fallback || "";
  return raw.replace(/\s*\*\s*/g, " × ").replace(/\bSTABLES\b/g, "Stablecoins");
}

function parseSnapshotPayload(payload: unknown): SnapshotState {
  if (!payload || typeof payload !== "object") return cachedSnapshot;
  const obj = payload as Record<string, unknown>;

  let rawList: unknown[] = [];
  if (Array.isArray(payload)) {
    rawList = payload;
  } else if (Array.isArray(obj.items)) {
    rawList = obj.items;
  } else if (Array.isArray(obj.indices)) {
    rawList = obj.indices;
  } else if (Array.isArray(obj.composites)) {
    rawList = obj.composites;
  } else if (Array.isArray(obj.data)) {
    rawList = obj.data;
  } else {
    const mapCandidate =
      (obj.snapshot && typeof obj.snapshot === "object" ? (obj.snapshot as Record<string, unknown>) : null) ||
      (obj.items && typeof obj.items === "object" ? (obj.items as Record<string, unknown>) : null) ||
      obj;
    for (const [k, v] of Object.entries(mapCandidate)) {
      if (v && typeof v === "object" && !Array.isArray(v)) {
        rawList.push({ symbol: k, ...(v as Record<string, unknown>) });
      }
    }
  }

  const updates = new Map<string, Record<string, unknown>>();
  for (const entry of rawList) {
    if (!entry || typeof entry !== "object") continue;
    const rec = entry as Record<string, unknown>;
    const sym = String(rec.symbol ?? rec.ticker ?? "").trim().toUpperCase();
    if (sym) updates.set(sym, rec);
  }

  const merged = FALLBACK_COMPOSITES.map((base) => {
    const u = updates.get(base.symbol);
    if (!u) return base;
    const rawVal = Number(u.value ?? u.price ?? u.close ?? u.last ?? base.value);
    const rawChg = Number(
      u.change_24h_pct ?? u.change_24h ?? u.change_pct ?? u.pct_24h ?? u.change ?? u.chg_24h ?? base.change_24h
    );
    return {
      ...base,
      name: typeof u.name === "string" && u.name ? u.name.replace(/\s*\(\$B\)|\s*\(%\)/g, "") : base.name,
      formula: normalizeFormula(typeof u.formula === "string" ? u.formula : undefined, base.formula),
      description: typeof u.description === "string" && u.description ? u.description : base.description,
      value: Number.isFinite(rawVal) && rawVal > 0 ? rawVal : base.value,
      change_24h: Number.isFinite(rawChg) ? rawChg : base.change_24h,
    };
  });

  const rawRegime =
    typeof obj.regime === "string"
      ? obj.regime
      : obj.regime && typeof obj.regime === "object"
        ? String((obj.regime as Record<string, unknown>).label ?? (obj.regime as Record<string, unknown>).name ?? "")
        : typeof obj.macro_regime === "string"
          ? obj.macro_regime
          : null;

  return {
    items: merged,
    regime: deriveMacroRegime(merged, rawRegime),
    updatedAt: Date.now(),
  };
}

export async function fetchCompositesSnapshot(force = false): Promise<SnapshotState> {
  if (!force && cachedSnapshot.updatedAt > 0 && Date.now() - cachedSnapshot.updatedAt < SNAPSHOT_TTL_MS) {
    return cachedSnapshot;
  }
  if (inFlightSnapshot) return inFlightSnapshot;

  inFlightSnapshot = (async () => {
    try {
      const r = await fetch("/api/composites/snapshot", {
        headers: device ? { "X-Device": device } : undefined,
        signal: AbortSignal.timeout(6000),
      });
      if (r.ok) {
        const json = await r.json();
        cachedSnapshot = parseSnapshotPayload(json);
      }
    } catch {
      // Keep instant fallback snapshot on offline/timeout
    } finally {
      inFlightSnapshot = null;
    }
    return cachedSnapshot;
  })();

  return inFlightSnapshot;
}

export function useCompositesSnapshot(): SnapshotState {
  const [state, setState] = useState<SnapshotState>(() => cachedSnapshot);

  useEffect(() => {
    let alive = true;
    const load = () => {
      fetchCompositesSnapshot().then((next) => {
        if (alive) setState(next);
      });
    };
    load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchCompositesSnapshot(true).then((next) => {
          if (alive) setState(next);
        });
      }
    }, 45_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return state;
}

/** Search helper used by Search.tsx to match composite tickers by symbol, alias, formula, or keyword. */
export function searchCompositeIndices(
  query: string,
  items: CompositeItem[] = cachedSnapshot.items
): CompositeItem[] {
  const raw = (query || "").trim();
  if (!raw) return [];
  const q = raw.toUpperCase().replace(/^CRYPTOCAP:/, "").trim();
  if (!q) return [];
  const qCompact = q.replace(/[./\-_\s]/g, "");

  const scored: { rank: number; idx: number; item: CompositeItem }[] = [];

  items.forEach((item, idx) => {
    const sym = item.symbol.toUpperCase();
    const symCompact = sym.replace(/[./\-_\s]/g, "");
    const aliases = item.aliases.map((a) => a.toUpperCase());
    const aliasesCompact = aliases.map((a) => a.replace(/[./\-_\s:]/g, ""));
    const nameUp = item.name.toUpperCase();
    const formulaUp = item.formula.toUpperCase();
    const descUp = item.description.toUpperCase();
    const catUp = item.category.toUpperCase();

    let rank = 99;
    if (q === sym || qCompact === symCompact || aliases.includes(q) || aliasesCompact.includes(qCompact)) {
      rank = 0;
    } else if (sym.startsWith(q) || (qCompact.length >= 2 && symCompact.startsWith(qCompact))) {
      rank = 1;
    } else if (aliases.some((a) => a.startsWith(q)) || (qCompact.length >= 2 && aliasesCompact.some((a) => a.startsWith(qCompact)))) {
      rank = 2;
    } else if (q.length >= 2 && (sym.includes(q) || (qCompact.length >= 2 && symCompact.includes(qCompact)))) {
      rank = 3;
    } else if (
      (q === "DOMINANCE" || q === "DOM" || q === ".D") &&
      item.category === "dominance"
    ) {
      rank = 4;
    } else if (
      (q === "RATIO" || q === "RATIOS" || q === "ROTATION" || q === "ROTATIONS") &&
      item.category === "ratio"
    ) {
      rank = 4;
    } else if (
      (q === "COMPOSITE" || q === "COMPOSITES" || q === "INDEX" || q === "INDICES" || q === "MACRO")
    ) {
      rank = 5;
    } else if (q.length >= 2 && (nameUp.includes(q) || formulaUp.includes(q) || descUp.includes(q) || catUp.includes(q))) {
      rank = 6;
    }

    if (rank < 99) {
      scored.push({ rank, idx, item });
    }
  });

  scored.sort((a, b) => a.rank - b.rank || a.idx - b.idx);
  return scored.map((s) => s.item);
}

/** Editorial horizontal bar + Sheet modal for all 20 TradingView Composite Tickers. */
export function CompositeStrip() {
  const { items, regime } = useCompositesSnapshot();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const bySymbol = useMemo(() => new Map(items.map((i) => [i.symbol, i])), [items]);
  const stripItems = useMemo(
    () => STRIP_TICKERS.map((sym) => bySymbol.get(sym)).filter((x): x is CompositeItem => Boolean(x)),
    [bySymbol]
  );

  const selectedItem = selectedSymbol ? bySymbol.get(selectedSymbol) ?? null : null;
  const regimeMeta = REGIME_STYLE[regime];

  const openModal = (sym?: string) => {
    setSelectedSymbol(sym ?? null);
    setSheetOpen(true);
  };

  return (
    <>
      <section
        aria-label={t("TradingView Composite Indices")}
        className="mb-3 rounded-[18px] bg-card px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--c-line)]"
      >
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar">
          {/* Macro Regime Pill */}
          <button
            type="button"
            onClick={() => openModal()}
            title={regimeMeta.hint}
            className={`flex h-7 flex-none items-center gap-1.5 rounded-full px-2.5 text-[11.5px] font-semibold tracking-tight transition-opacity active:opacity-80 ${regimeMeta.badge}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${regimeMeta.dot}`} />
            <span>{regime}</span>
          </button>

          <span className="h-4 w-px flex-none bg-line" aria-hidden="true" />

          {/* Key Composite Tickers */}
          {stripItems.map((item) => {
            const [chg, sign] = changeText(item.change_24h);
            return (
              <button
                key={item.symbol}
                type="button"
                onClick={() => openModal(item.symbol)}
                title={`${item.name} (${item.formula})`}
                className="flex h-7 flex-none items-center gap-1.5 rounded-full bg-bg/75 px-2.5 text-[12px] transition-colors hover:bg-pill active:bg-press"
              >
                <b className="font-semibold tracking-tight text-text">{item.symbol}</b>
                <span className="num text-[11.5px] text-text-2">{formatCompositeValue(item)}</span>
                <em
                  className={`num text-[11px] font-medium not-italic ${
                    sign === "up" ? "text-up" : sign === "down" ? "text-down" : "text-text-3"
                  }`}
                >
                  {chg}
                </em>
              </button>
            );
          })}

          {/* All 20 Indices button */}
          <button
            type="button"
            onClick={() => openModal()}
            className="ml-auto flex h-7 flex-none items-center gap-1 rounded-full bg-ink px-2.5 text-[11.5px] font-semibold text-on-ink transition-opacity hover:opacity-90 active:opacity-80"
          >
            <span>All 20 Indices ▾</span>
          </button>
        </div>
      </section>

      <Sheet
        open={sheetOpen}
        title="TradingView Composite Indices"
        sub="Live synthetic market-cap, dominance %, and rotation ratios across 20 canonical indices."
        onClose={() => setSheetOpen(false)}
      >
        {/* Macro Regime Bar */}
        <div className="mb-4 rounded-[16px] bg-bg p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.07em] text-text-3">
              Macro Regime
            </span>
            <div className="flex flex-wrap gap-1">
              {(["Altseason", "BTC Season", "Risk-Off", "Macro Pulse"] as const).map((r) => {
                const active = r === regime;
                return (
                  <span
                    key={r}
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      active ? "bg-ink text-on-ink" : "bg-pill text-text-3 opacity-75"
                    }`}
                  >
                    {r}
                  </span>
                );
              })}
            </div>
          </div>
          <p className="mt-1.5 text-[12.5px] text-text-2">{regimeMeta.hint}</p>
        </div>

        {/* Highlighted Selected Ticker Card (if user tapped a specific ticker chip) */}
        {selectedItem && (
          <div className="mb-4 rounded-[18px] border border-sage bg-bg p-3.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <b className="text-[16px] font-semibold">{selectedItem.symbol}</b>
                  <span className="rounded-md bg-pill px-1.5 py-0.5 font-mono text-[11px] text-text-2">
                    {selectedItem.formula}
                  </span>
                </div>
                <div className="mt-0.5 text-[13px] font-medium text-text-2">{selectedItem.name}</div>
                <p className="mt-1 text-[12px] text-text-3">{selectedItem.description}</p>
              </div>
              <div className="flex flex-col items-end">
                <b className="num text-[16px] font-semibold">{formatCompositeValue(selectedItem)}</b>
                {(() => {
                  const [chg, sign] = changeText(selectedItem.change_24h);
                  return (
                    <em
                      className={`num text-[12px] font-medium not-italic ${
                        sign === "up" ? "text-up" : sign === "down" ? "text-down" : "text-text-3"
                      }`}
                    >
                      {chg}
                    </em>
                  );
                })()}
              </div>
            </div>
            <div className="mt-3 flex justify-end">
              <a
                href={`/?symbol=${encodeURIComponent(selectedItem.symbol)}`}
                className="inline-flex items-center gap-1 rounded-full bg-ink px-3 py-1.5 text-[12.5px] font-semibold text-on-ink no-underline active:opacity-80"
              >
                Open Chart ↗
              </a>
            </div>
          </div>
        )}

        {/* All 20 Indices Grouped by Category */}
        <div className="space-y-5">
          {COMPOSITE_GROUPS.map((group) => {
            const groupItems = group.symbols
              .map((sym) => bySymbol.get(sym))
              .filter((x): x is CompositeItem => Boolean(x));
            return (
              <div key={group.key}>
                <div className="mb-2 flex items-baseline justify-between">
                  <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] text-text-3">
                    {group.title}
                  </h3>
                  <span className="text-[11.5px] text-text-3">{group.subtitle}</span>
                </div>
                <ol className="divide-y divide-line rounded-[18px] bg-bg p-1.5">
                  {group.symbols.map((sym) => {
                    const item = bySymbol.get(sym);
                    if (!item) return null;
                    const [chg, sign] = changeText(item.change_24h);
                    const isSelected = selectedSymbol === item.symbol;
                    return (
                      <li
                        key={item.symbol}
                        className={`flex items-center justify-between gap-2.5 rounded-[12px] px-2.5 py-2.5 ${
                          isSelected ? "bg-pill/70" : ""
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <b className="text-[14px] font-semibold leading-tight text-text">
                              {item.symbol}
                            </b>
                            <span className=" truncate text-[12.5px] text-text-2">{item.name}</span>
                          </div>
                          <div className="mt-0.5 truncate font-mono text-[11px] text-text-3">
                            {item.formula}
                          </div>
                        </div>
                        <div className="flex flex-none items-center gap-2.5">
                          <div className="flex flex-col items-end">
                            <b className="num text-[13.5px] font-semibold text-text">
                              {formatCompositeValue(item)}
                            </b>
                            <em
                              className={`num text-[11.5px] not-italic ${
                                sign === "up" ? "text-up" : sign === "down" ? "text-down" : "text-text-3"
                              }`}
                            >
                              {chg}
                            </em>
                          </div>
                          <a
                            href={`/?symbol=${encodeURIComponent(item.symbol)}`}
                            className="flex-none rounded-full bg-pill px-2.5 py-1 text-[11.5px] font-semibold text-text no-underline transition-colors hover:bg-ink hover:text-on-ink active:bg-press"
                          >
                            Open Chart ↗
                          </a>
                        </div>
                      </li>
                    );
                  })}
                  {!groupItems.length && null}
                </ol>
              </div>
            );
          })}
        </div>
      </Sheet>
    </>
  );
}
