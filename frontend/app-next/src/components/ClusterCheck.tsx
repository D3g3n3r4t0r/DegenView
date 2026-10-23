import { useState } from "react";
import * as api from "../lib/api";
import type { Gem } from "../lib/types";
import { t } from "../lib/i18n";

const EVM_RE = /^0x[0-9a-fA-F]{40}$/;
const SOL_RE = /^[1-9A-HJ-NP-Za-km-z]{32,48}$/;
const LAYER_RE = /^(kas-kaspa|kaspa|kas|inj-injective-protocol|injective|inj|arb-arbitrum|arbitrum|arb|op-optimism|optimism|op|tia-celestia|celestia|tia|sei-sei|sei|zro-layerzero|layerzero|zro|mnt-mantle|mantle|mnt|metis-metisdao|metis|zk-zksync|zksync|zk|zeta-zetachain|zetachain|zeta|axl-axelar|axelar|axl|w-wormhole|wormhole|[a-z0-9]{2,12}-[a-z0-9-]{2,40})$/i;
export const ADDRESS = /^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,48}|(kas-kaspa|kaspa|kas|inj-injective-protocol|injective|inj|arb-arbitrum|arbitrum|arb|op-optimism|optimism|op|tia-celestia|celestia|tia|sei-sei|sei|zro-layerzero|layerzero|zro|mnt-mantle|mantle|mnt|metis-metisdao|metis|zk-zksync|zksync|zk|zeta-zetachain|zetachain|zeta|axl-axelar|axelar|axl|w-wormhole|wormhole|[a-z0-9]{2,12}-[a-z0-9-]{2,40}))$/i;
const EVM = [["robinhood", "Robinhood"], ["ethereum", "Ethereum"], ["base", "Base"], ["bsc", "BSC"]] as const;

/** A pasted address or Layer 0/1/2 chain id: check its wallet clusters now
 *  (Lorenzo, 22-23/10: also covers Layer 0/1/2 chains like Kaspa and Injective). */
export function ClusterCheck({ address, onOpen, onStart, onFail }: { address: string; onOpen: (e: Gem) => void; onStart?: (chain: string) => void; onFail?: () => void }) {
  const isEvm = EVM_RE.test(address);
  const sol = !isEvm && SOL_RE.test(address);
  const isLayer = !isEvm && !sol && LAYER_RE.test(address);
  const ok = isEvm || sol || isLayer;
  const [pick, setPick] = useState("robinhood");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const chain = isLayer ? "layer" : sol ? "solana" : pick;
  const go = async () => {
    if (!ok || busy) return;
    setBusy(true); setMsg("");
    onStart?.(chain);
    try {
      const r = await api.askClusterCheck(chain, address);
      const sym = isLayer ? address.toUpperCase().slice(0, 10) : `${address.slice(0, 4)}…${address.slice(-4)}`;
      onOpen({ chain, token_address: address, symbol: sym } as Gem);
      if (r.error) setMsg(r.error);
    } catch (e) {
      setMsg((e as Error).message || t("Not started, try again."));
      onFail?.();
    } finally { setBusy(false); }
  };
  return (
    <div className="rounded-[16px] bg-card p-4">
      <div className="flex items-baseline gap-2">
        <b className="flex-1 text-[15px] font-semibold">{t("Check wallet clusters")}</b>
        {ok && <small className="text-[12.5px] text-text-3">{isLayer ? "Layer 0/1/2" : sol ? t("Detected: Solana") : t("Pick the chain")}</small>}
      </div>
      <small className="mt-0.5 block text-[13px] text-text-3">{t("Who holds this token together, and whether they sell together.")}</small>
      {isEvm && (
        <div className="mt-3 flex flex-wrap gap-1.5" role="radiogroup" aria-label="Chain">
          {EVM.map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={pick === k} onClick={() => setPick(k)}
              className={`h-8 rounded-full px-3 text-[13px] ${pick === k ? "bg-pill font-semibold text-ink shadow-[inset_0_0_0_1.5px_var(--c-ink)]" : "bg-pill text-text-2"}`}>{label}</button>
          ))}
        </div>
      )}
      <button type="button" disabled={!ok || busy} onClick={go}
        className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-full bg-ink text-[15.5px] font-semibold text-on-ink transition-opacity disabled:opacity-40">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="7" cy="8" r="3" /><circle cx="17" cy="7" r="2.2" /><circle cx="14" cy="17" r="3.5" /><path d="m9.6 9.6 2.3 4.4M9.9 7.7l4.9-.5M16.6 9.2l-1.6 4.3" />
        </svg>
        {busy ? t("Starting…") : ok ? `${t("Start cluster check")} · ${isLayer ? "Layer 0/1/2" : sol ? "Solana" : EVM.find(([k]) => k === pick)![1]}` : t("Start cluster check")}
      </button>
      {!ok && address && <p className="mt-2 text-[13px] text-down">{t("Not a token address: 0x… (40 characters), a Solana mint, or a Layer 0/1/2 chain (e.g. kaspa, injective).")}</p>}
      {!address && <p className="mt-2 text-[13px] text-text-3">{t("Paste a token address above.")}</p>}
      {msg && <p className="mt-2 text-[13px] text-down">{msg}</p>}
    </div>
  );
}
