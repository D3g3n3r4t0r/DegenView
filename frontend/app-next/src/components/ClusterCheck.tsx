import { useState } from "react";
import * as api from "../lib/api";
import type { Gem } from "../lib/types";
import { t } from "../lib/i18n";

const EVM_RE = /^0x[0-9a-fA-F]{40}$/;
const EVM_EXTRACT_RE = /0x[0-9a-fA-F]{40}/;
const SOL_RE = /^[1-9A-HJ-NP-Za-km-z]{32,48}$/;
const URL_RE = /^https?:\/\/\S+$/i;
const LAYER_RE = /^(kas-kaspa|kaspa|kas|octa-octaspace|octaspace|octa|cheqd-network|cheqd|cheq|inj-injective-protocol|injective|inj|arb-arbitrum|arbitrum|arb|op-optimism|optimism|op|tia-celestia|celestia|tia|sei-sei|sei|zro-layerzero|layerzero|zro|mnt-mantle|mantle|mnt|metis-metisdao|metis|zk-zksync|zksync|zk|zeta-zetachain|zetachain|zeta|axl-axelar|axelar|axl|w-wormhole|wormhole|[a-z0-9]{2,12}-[a-z0-9-]{2,40})$/i;
export const ADDRESS = /^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,48}|https?:\/\/\S+|(kas-kaspa|kaspa|kas|octa-octaspace|octaspace|octa|cheqd-network|cheqd|cheq|inj-injective-protocol|injective|inj|arb-arbitrum|arbitrum|arb|op-optimism|optimism|op|tia-celestia|celestia|tia|sei-sei|sei|zro-layerzero|layerzero|zro|mnt-mantle|mantle|mnt|metis-metisdao|metis|zk-zksync|zksync|zk|zeta-zetachain|zetachain|zeta|axl-axelar|axelar|axl|w-wormhole|wormhole|[a-z0-9]{2,12}-[a-z0-9-]{2,40}))$/i;
const EVM = [["robinhood", "Robinhood"], ["ethereum", "Ethereum"], ["base", "Base"], ["bsc", "BSC"]] as const;

const QUICK_SCANS = [
  { label: "OctaSpace · OCTA", raw: "octa-octaspace", url: "https://scan.octa.space/accounts" },
  { label: "Cheqd · CHEQ", raw: "cheqd-network", url: "https://explorer.cheqd.io/accounts" },
  { label: "Kaspa · KAS", raw: "kas-kaspa" },
  { label: "Injective · INJ", raw: "inj-injective-protocol" },
  { label: "Arbitrum · ARB", raw: "arb-arbitrum" },
] as const;

export function resolveClusterInput(raw: string): {
  chain: string;
  token: string;
  symbol?: string;
  isUrl: boolean;
  isEvm: boolean;
  sol: boolean;
  isLayer: boolean;
  ok: boolean;
} {
  const s = raw.trim();
  const low = s.toLowerCase();
  const isUrl = URL_RE.test(s);
  const isEvm = !isUrl && EVM_RE.test(s);
  const sol = !isUrl && !isEvm && SOL_RE.test(s);
  const isLayer = !isUrl && !isEvm && !sol && LAYER_RE.test(s);
  const ok = isUrl || isEvm || sol || isLayer;

  if (
    low === "octa" ||
    low === "octaspace" ||
    low === "octa-octaspace" ||
    low.includes("scan.octa.space") ||
    low.includes("octa.space")
  ) {
    return { chain: "layer", token: "octa-octaspace", symbol: "OCTA", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (
    low === "cheq" ||
    low === "cheqd" ||
    low === "cheqd-network" ||
    low.includes("explorer.cheqd.io") ||
    low.includes("cheqd.io") ||
    low.includes("cheqd.net")
  ) {
    return { chain: "layer", token: "cheqd-network", symbol: "CHEQ", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (
    low === "kas" ||
    low === "kaspa" ||
    low === "kas-kaspa" ||
    low.includes("kaspa.org") ||
    low.includes("kas.fyi")
  ) {
    return { chain: "layer", token: "kas-kaspa", symbol: "KAS", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (
    low === "inj" ||
    low === "injective" ||
    low === "inj-injective-protocol" ||
    low.includes("injective.network") ||
    low.includes("injective")
  ) {
    return { chain: "layer", token: "inj-injective-protocol", symbol: "INJ", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (low === "arb" || low === "arbitrum" || low === "arb-arbitrum") {
    return { chain: "layer", token: "arb-arbitrum", symbol: "ARB", isUrl, isEvm, sol, isLayer: true, ok: true };
  }
  if (low === "op" || low === "optimism" || low === "op-optimism") {
    return { chain: "layer", token: "op-optimism", symbol: "OP", isUrl, isEvm, sol, isLayer: true, ok: true };
  }
  if (low === "tia" || low === "celestia" || low === "tia-celestia") {
    return { chain: "layer", token: "tia-celestia", symbol: "TIA", isUrl, isEvm, sol, isLayer: true, ok: true };
  }
  if (low === "sei" || low === "sei-sei") {
    return { chain: "layer", token: "sei-sei", symbol: "SEI", isUrl, isEvm, sol, isLayer: true, ok: true };
  }

  if (isUrl) {
    const evmMatch = s.match(EVM_EXTRACT_RE);
    if (evmMatch) {
      const addr = evmMatch[0].toLowerCase();
      return {
        chain: "layer",
        token: addr,
        symbol: `${addr.slice(0, 4)}…${addr.slice(-4)}`,
        isUrl: true,
        isEvm: false,
        sol: false,
        isLayer: false,
        ok: true,
      };
    }
    const cleanHost = s.replace(/^https?:\/\/(www\.|explorer\.|scan\.|mainnet\.|app\.)?/i, "").split("/")[0];
    const slug = (cleanHost.split(".")[0] || "LINK").slice(0, 8).toUpperCase();
    return {
      chain: "layer",
      token: s,
      symbol: slug,
      isUrl: true,
      isEvm: false,
      sol: false,
      isLayer: false,
      ok: true,
    };
  }

  if (isLayer) {
    const sym = s.split("-")[0].toUpperCase().slice(0, 10);
    return { chain: "layer", token: low, symbol: sym, isUrl: false, isEvm: false, sol: false, isLayer: true, ok: true };
  }

  if (sol) {
    return {
      chain: "solana",
      token: s,
      symbol: `${s.slice(0, 4)}…${s.slice(-4)}`,
      isUrl: false,
      isEvm: false,
      sol: true,
      isLayer: false,
      ok: true,
    };
  }

  if (isEvm) {
    const addr = s.toLowerCase();
    return {
      chain: "robinhood",
      token: addr,
      symbol: `${addr.slice(0, 4)}…${addr.slice(-4)}`,
      isUrl: false,
      isEvm: true,
      sol: false,
      isLayer: false,
      ok: true,
    };
  }

  return { chain: "robinhood", token: s, isUrl: false, isEvm: false, sol: false, isLayer: false, ok: false };
}

/** A pasted address, Layer 0/1/2 chain id, or Explorer/DEX link: check its wallet clusters now
 *  (Lorenzo, 22-23/10: also covers Layer 0/1/2 chains and custom links for unsupported networks). */
export function ClusterCheck({
  address,
  onOpen,
  onStart,
  onFail,
}: {
  address: string;
  onOpen: (e: Gem) => void;
  onStart?: (chain: string, token?: string, symbol?: string) => void;
  onFail?: () => void;
}) {
  const resolved = resolveClusterInput(address);
  const { isUrl, isEvm, sol, isLayer, ok } = resolved;
  const [pick, setPick] = useState("robinhood");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const runTarget = async (targetRaw: string, customUrl?: string) => {
    const res = resolveClusterInput(targetRaw);
    if (!res.ok || busy) return;
    const targetChain = res.isEvm ? pick : res.chain;
    const linkUrl = customUrl || (res.isUrl ? targetRaw.trim() : undefined);
    setBusy(true);
    setMsg("");
    onStart?.(targetChain, res.token, res.symbol);
    try {
      const r = await api.askClusterCheck(targetChain, res.token, linkUrl);
      const outChain = r.chain || targetChain;
      const outToken = r.token || res.token;
      const sym =
        r.symbol ||
        res.symbol ||
        (res.isUrl
          ? outToken.slice(0, 8).toUpperCase()
          : res.isLayer
            ? outToken.toUpperCase().slice(0, 10)
            : `${outToken.slice(0, 4)}…${outToken.slice(-4)}`);
      onOpen({ chain: outChain, token_address: outToken, symbol: sym } as Gem);
      if (r.error) setMsg(r.error);
    } catch (e) {
      setMsg((e as Error).message || t("Not started, try again."));
      onFail?.();
    } finally {
      setBusy(false);
    }
  };

  const go = () => runTarget(address);
  const badge = isUrl ? t("Link analysis") : isLayer ? (resolved.symbol ? `${resolved.symbol} · Layer` : "Layer 0/1/2") : sol ? "Solana" : EVM.find(([k]) => k === pick)![1];

  return (
    <div className="rounded-[16px] bg-card p-4">
      <div className="flex items-baseline gap-2">
        <b className="flex-1 text-[15px] font-semibold">{t("Check wallet clusters")}</b>
        {ok && (
          <small className="text-[12.5px] text-text-3">
            {isUrl ? (resolved.symbol ? `${resolved.symbol} · ${t("Explorer / DEX link")}` : t("Explorer / DEX link")) : isLayer ? "Layer 0/1/2" : sol ? t("Detected: Solana") : t("Pick the chain")}
          </small>
        )}
      </div>
      <small className="mt-0.5 block text-[13px] text-text-3">{t("Who holds this token together, and whether they sell together.")}</small>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="mr-0.5 text-[11.5px] font-medium uppercase tracking-[0.06em] text-text-3">{t("Quick-Scan")}:</span>
        {QUICK_SCANS.map((q) => (
          <button
            key={q.raw}
            type="button"
            disabled={busy}
            onClick={() => runTarget(q.raw, "url" in q ? q.url : undefined)}
            className="h-7 rounded-full bg-pill px-2.5 text-[12px] font-medium text-text-2 transition-colors hover:bg-ink hover:text-on-ink active:scale-[0.98] disabled:opacity-40"
          >
            {q.label}
          </button>
        ))}
      </div>

      {isEvm && (
        <div className="mt-3 flex flex-wrap gap-1.5" role="radiogroup" aria-label="Chain">
          {EVM.map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={pick === k}
              onClick={() => setPick(k)}
              className={`h-8 rounded-full px-3 text-[13px] ${pick === k ? "bg-pill font-semibold text-ink shadow-[inset_0_0_0_1.5px_var(--c-ink)]" : "bg-pill text-text-2"}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        disabled={!ok || busy}
        onClick={go}
        className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-full bg-ink text-[15.5px] font-semibold text-on-ink transition-opacity disabled:opacity-40"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="7" cy="8" r="3" />
          <circle cx="17" cy="7" r="2.2" />
          <circle cx="14" cy="17" r="3.5" />
          <path d="m9.6 9.6 2.3 4.4M9.9 7.7l4.9-.5M16.6 9.2l-1.6 4.3" />
        </svg>
        {busy ? t("Starting…") : ok ? `${t("Start cluster check")} · ${badge}` : t("Start cluster check")}
      </button>
      {!ok && address && (
        <p className="mt-2 text-[13px] text-down">
          {t("Paste a 0x… address, Solana mint, Layer 0/1/2 chain (e.g. kaspa, injective), or an explorer/DexScreener link (https://…).")}
        </p>
      )}
      {!address && <p className="mt-2 text-[13px] text-text-3">{t("Paste a token address or an explorer link (https://…) above, or tap a Quick-Scan network.")}</p>}
      {msg && <p className="mt-2 text-[13px] text-down">{msg}</p>}
    </div>
  );
}
