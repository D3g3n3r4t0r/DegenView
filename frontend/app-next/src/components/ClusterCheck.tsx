import { useEffect, useState } from "react";
import * as api from "../lib/api";
import type { Gem } from "../lib/types";
import { t } from "../lib/i18n";

const EVM_RE = /^0x[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$/;
const EVM_EXTRACT_RE = /0x[0-9a-fA-F]{40}/;
const SOL_RE = /^[1-9A-HJ-NP-Za-km-z]{32,48}$/;
const KASPA_ADDR_RE = /^kaspa:[a-z0-9]{40,75}$/i;
const BECH32_ADDR_RE = /^([a-z]{2,14})1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{20,85}$/i;
const URL_RE = /^https?:\/\/\S+$/i;
const LAYER_RE = /^(kas-kaspa|kaspa|kas|octa-octaspace|octaspace|octa|cheqd-network|cheqd|cheq|inj-injective-protocol|injective|inj|arb-arbitrum|arbitrum|arb|op-optimism|optimism|op|tia-celestia|celestia|tia|sei-sei|sei|zro-layerzero|layerzero|zro|mnt-mantle|mantle|mnt|metis-metisdao|metis|zk-zksync|zksync|zk|zeta-zetachain|zetachain|zeta|axl-axelar|axelar|axl|w-wormhole|wormhole|[a-z0-9]{2,12}-[a-z0-9-]{2,40})$/i;
export const ADDRESS = /^(0x[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?|[1-9A-HJ-NP-Za-km-z]{32,48}|kaspa:[a-z0-9]{40,75}|[a-z]{2,14}1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{20,85}|https?:\/\/\S+|(kas-kaspa|kaspa|kas|octa-octaspace|octaspace|octa|cheqd-network|cheqd|cheq|inj-injective-protocol|injective|inj|arb-arbitrum|arbitrum|arb|op-optimism|optimism|op|tia-celestia|celestia|tia|sei-sei|sei|zro-layerzero|layerzero|zro|mnt-mantle|mantle|mnt|metis-metisdao|metis|zk-zksync|zksync|zk|zeta-zetachain|zetachain|zeta|axl-axelar|axelar|axl|w-wormhole|wormhole|[a-z0-9]{2,12}-[a-z0-9-]{2,40}))$/i;

const BECH32_PREFIXES: Record<string, [string, string, string]> = {
  cheqd: ["cheqd-network", "CHEQ", "Cheqd"],
  osmo: ["osmo-osmosis", "OSMO", "Osmosis"],
  cosmos: ["atom-cosmos", "ATOM", "Cosmos Hub"],
  inj: ["inj-injective-protocol", "INJ", "Injective"],
  celestia: ["tia-celestia", "TIA", "Celestia"],
  sei: ["sei-sei", "SEI", "Sei"],
  stars: ["stars-stargaze", "STARS", "Stargaze"],
  kujira: ["kuji-kujira", "KUJI", "Kujira"],
  neutron: ["ntrn-neutron", "NTRN", "Neutron"],
  akash: ["akt-akash-network", "AKT", "Akash"],
  juno: ["juno-juno-network", "JUNO", "Juno"],
  kava: ["kava-kava", "KAVA", "Kava"],
  dym: ["dym-dymension", "DYM", "Dymension"],
  saga: ["saga-saga", "SAGA", "Saga"],
  archway: ["arch-archway", "ARCH", "Archway"],
  desmos: ["dsm-desmos", "DSM", "Desmos"],
  secret: ["scrt-secret", "SCRT", "Secret"],
  axelar: ["axl-axelar", "AXL", "Axelar"],
};

const CHAIN_LABELS: Record<string, string> = {
  ethereum: "Ethereum",
  base: "Base",
  bsc: "BSC",
  robinhood: "Robinhood Chain",
  solana: "Solana",
  arbitrum: "Arbitrum",
  optimism: "Optimism",
  polygon: "Polygon",
  avalanche: "Avalanche",
  monad: "Monad",
  mantle: "Mantle",
  zksync: "zkSync",
  manta: "Manta",
  octaspace: "OctaSpace",
  kaspa: "Kaspa",
  cheqd: "Cheqd",
  injective: "Injective",
  layer: "Layer 0/1/2",
};

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
  detectedLabel?: string;
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
  const isKaspaAddr = !isUrl && !isEvm && KASPA_ADDR_RE.test(s);
  const bechMatch = !isUrl && !isEvm && !isKaspaAddr ? low.match(BECH32_ADDR_RE) : null;
  const sol = !isUrl && !isEvm && !isKaspaAddr && !bechMatch && SOL_RE.test(s);
  const isLayer = !isUrl && !isEvm && !sol && (isKaspaAddr || !!bechMatch || LAYER_RE.test(s));
  const ok = isUrl || isEvm || sol || isLayer;

  if (isKaspaAddr) {
    return { chain: "layer", token: "kas-kaspa", symbol: "KAS", detectedLabel: "Kaspa · KAS", isUrl: false, isEvm: false, sol: false, isLayer: true, ok: true };
  }
  if (bechMatch) {
    const hrp = bechMatch[1].toLowerCase();
    const mapped = BECH32_PREFIXES[hrp];
    if (mapped) {
      return { chain: "layer", token: mapped[0], symbol: mapped[1], detectedLabel: `${mapped[2]} · ${mapped[1]}`, isUrl: false, isEvm: false, sol: false, isLayer: true, ok: true };
    }
    return { chain: "layer", token: hrp, symbol: hrp.toUpperCase(), detectedLabel: `${hrp.toUpperCase()} · Cosmos`, isUrl: false, isEvm: false, sol: false, isLayer: true, ok: true };
  }

  if (
    low === "octa" ||
    low === "octaspace" ||
    low === "octa-octaspace" ||
    low.includes("scan.octa.space") ||
    low.includes("octa.space")
  ) {
    return { chain: "layer", token: "octa-octaspace", symbol: "OCTA", detectedLabel: "OctaSpace · OCTA", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (
    low === "cheq" ||
    low === "cheqd" ||
    low === "cheqd-network" ||
    low.includes("explorer.cheqd.io") ||
    low.includes("cheqd.io") ||
    low.includes("cheqd.net")
  ) {
    return { chain: "layer", token: "cheqd-network", symbol: "CHEQ", detectedLabel: "Cheqd · CHEQ", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (
    low === "kas" ||
    low === "kaspa" ||
    low === "kas-kaspa" ||
    low.includes("kaspa.org") ||
    low.includes("kas.fyi")
  ) {
    return { chain: "layer", token: "kas-kaspa", symbol: "KAS", detectedLabel: "Kaspa · KAS", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (
    low === "inj" ||
    low === "injective" ||
    low === "inj-injective-protocol" ||
    low.includes("injective.network") ||
    low.includes("injective")
  ) {
    return { chain: "layer", token: "inj-injective-protocol", symbol: "INJ", detectedLabel: "Injective · INJ", isUrl, isEvm, sol, isLayer: !isUrl, ok: true };
  }
  if (low === "arb" || low === "arbitrum" || low === "arb-arbitrum") {
    return { chain: "layer", token: "arb-arbitrum", symbol: "ARB", detectedLabel: "Arbitrum · ARB", isUrl, isEvm, sol, isLayer: true, ok: true };
  }
  if (low === "op" || low === "optimism" || low === "op-optimism") {
    return { chain: "layer", token: "op-optimism", symbol: "OP", detectedLabel: "Optimism · OP", isUrl, isEvm, sol, isLayer: true, ok: true };
  }
  if (low === "tia" || low === "celestia" || low === "tia-celestia") {
    return { chain: "layer", token: "tia-celestia", symbol: "TIA", detectedLabel: "Celestia · TIA", isUrl, isEvm, sol, isLayer: true, ok: true };
  }
  if (low === "sei" || low === "sei-sei") {
    return { chain: "layer", token: "sei-sei", symbol: "SEI", detectedLabel: "Sei · SEI", isUrl, isEvm, sol, isLayer: true, ok: true };
  }

  if (isUrl) {
    const evmMatch = s.match(EVM_EXTRACT_RE);
    let urlNetLabel = "Explorer / DEX";
    if (low.includes("basescan.org") || low.includes("/base/")) urlNetLabel = "Base";
    else if (low.includes("etherscan.io") || low.includes("/ethereum/")) urlNetLabel = "Ethereum";
    else if (low.includes("bscscan.com") || low.includes("/bsc/")) urlNetLabel = "BSC";
    else if (low.includes("arbiscan.io") || low.includes("/arbitrum/")) urlNetLabel = "Arbitrum";
    else if (low.includes("polygonscan.com") || low.includes("/polygon/")) urlNetLabel = "Polygon";
    else if (low.includes("optimistic.etherscan.io") || low.includes("/optimism/")) urlNetLabel = "Optimism";
    else if (low.includes("solscan.io") || low.includes("/solana/")) urlNetLabel = "Solana";
    if (evmMatch) {
      const addr = evmMatch[0].toLowerCase();
      return {
        chain: "layer",
        token: addr,
        symbol: `${addr.slice(0, 4)}…${addr.slice(-4)}`,
        detectedLabel: urlNetLabel,
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
      detectedLabel: `${urlNetLabel} · ${slug}`,
      isUrl: true,
      isEvm: false,
      sol: false,
      isLayer: false,
      ok: true,
    };
  }

  if (isLayer) {
    const sym = s.split("-")[0].toUpperCase().slice(0, 10);
    return { chain: "layer", token: low, symbol: sym, detectedLabel: `${sym} · Layer`, isUrl: false, isEvm: false, sol: false, isLayer: true, ok: true };
  }

  if (sol) {
    return {
      chain: "solana",
      token: s,
      symbol: `${s.slice(0, 4)}…${s.slice(-4)}`,
      detectedLabel: "Solana",
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
      chain: "auto",
      token: addr,
      symbol: `${addr.slice(0, 4)}…${addr.slice(-4)}`,
      detectedLabel: "Auto-Detect EVM",
      isUrl: false,
      isEvm: true,
      sol: false,
      isLayer: false,
      ok: true,
    };
  }

  return { chain: "auto", token: s, isUrl: false, isEvm: false, sol: false, isLayer: false, ok: false };
}

/** A pasted address, Layer 0/1/2 chain id, or Explorer/DEX link: automatically detects the
 *  blockchain from the address and checks its wallet clusters immediately. */
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
  const [detected, setDetected] = useState<{
    forAddress: string;
    chain: string;
    token: string;
    symbol?: string;
    url?: string;
    networkLabel: string;
  } | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  // Automatically probe the backend whenever an EVM 0x address (or any valid address) is entered
  useEffect(() => {
    const trimmed = address.trim();
    if (!ok || !trimmed) {
      setDetected(null);
      setDetecting(false);
      return;
    }
    if (!isEvm) {
      setDetected(null);
      setDetecting(false);
      return;
    }
    let alive = true;
    setDetecting(true);
    const timer = setTimeout(() => {
      api
        .detectClusterChain(trimmed, "auto")
        .then((res) => {
          if (!alive) return;
          const netKey = (res.detected_network || res.chain || "ethereum").toLowerCase();
          const netLabel = CHAIN_LABELS[netKey] || netKey.charAt(0).toUpperCase() + netKey.slice(1);
          setDetected({
            forAddress: trimmed,
            chain: res.chain,
            token: res.token || trimmed.toLowerCase(),
            symbol: res.symbol,
            url: res.url,
            networkLabel: res.symbol && !res.symbol.includes("…") ? `${netLabel} · ${res.symbol}` : netLabel,
          });
        })
        .catch(() => {})
        .finally(() => {
          if (alive) setDetecting(false);
        });
    }, 120);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [address, ok, isEvm]);

  const activeDetected = detected && detected.forAddress === address.trim() ? detected : null;

  const runTarget = async (targetRaw: string, customUrl?: string) => {
    const res = resolveClusterInput(targetRaw);
    if (!res.ok || busy) return;
    const isCurrentEvm = res.isEvm && activeDetected && targetRaw.trim() === address.trim();
    const targetChain = isCurrentEvm ? activeDetected.chain : res.chain;
    const targetToken = isCurrentEvm ? activeDetected.token : res.token;
    const linkUrl = customUrl || (isCurrentEvm ? activeDetected.url : undefined) || (res.isUrl ? targetRaw.trim() : undefined);
    setBusy(true);
    setMsg("");
    onStart?.(targetChain === "auto" ? "ethereum" : targetChain, targetToken, isCurrentEvm ? activeDetected.symbol : res.symbol);
    try {
      const r = await api.askClusterCheck(targetChain, targetToken, linkUrl);
      const outChain = r.chain || (targetChain === "auto" ? "ethereum" : targetChain);
      const outToken = r.token || targetToken;
      const sym =
        r.symbol ||
        (isCurrentEvm ? activeDetected.symbol : undefined) ||
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
  const badge = isEvm
    ? activeDetected
      ? activeDetected.networkLabel
      : detecting
        ? t("Detecting chain…")
        : "Auto-Detect EVM"
    : resolved.detectedLabel || (isUrl ? t("Link analysis") : isLayer ? (resolved.symbol ? `${resolved.symbol} · Layer` : "Layer 0/1/2") : sol ? "Solana" : "Auto");

  return (
    <div className="rounded-[16px] bg-card p-4">
      <div className="flex items-baseline gap-2">
        <b className="flex-1 text-[15px] font-semibold">{t("Check wallet clusters")}</b>
        {ok && (
          <small className="flex items-center gap-1.5 text-[12.5px] font-medium text-up">
            <span className="h-2 w-2 rounded-full bg-up animate-pulse" />
            {detecting ? t("Detecting chain…") : `${t("Detected:")} ${badge}`}
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
            className="h-7 rounded-full border border-line bg-pill px-2.5 text-[12px] font-medium text-text-2 transition-colors hover:border-sage hover:bg-sage hover:text-on-sage active:scale-[0.98] disabled:opacity-40"
          >
            {q.label}
          </button>
        ))}
      </div>

      <button
        type="button"
        disabled={!ok || busy}
        onClick={go}
        className="mt-3 flex h-12 w-full items-center justify-between rounded-full bg-ink px-5 text-[15px] font-semibold text-on-ink transition-opacity disabled:bg-pill disabled:text-text-3"
      >
        <span>{busy ? t("Starting…") : ok ? t("Check clusters") : t("Paste a token address above")}</span>
        {ok && <small className="font-normal opacity-80">{badge}</small>}
      </button>
      {msg && (
        <p role="status" className="mt-2 text-[13px] text-text-2">
          {msg}
        </p>
      )}
    </div>
  );
}
