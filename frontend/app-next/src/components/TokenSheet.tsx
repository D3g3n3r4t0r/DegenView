import { AnimatePresence, motion } from "motion/react";
import type { Entry } from "../types";
import { age, chainTag, usd } from "../format";
import { TokenLogo } from "./TokenLogo";
import { ScoreRing } from "./ScoreRing";
import { Change } from "./Change";

// Token as a bottom sheet (direction A): drag down or tap outside to close.
export function TokenSheet({ e, onClose }: { e: Entry | null; onClose: () => void }) {
  return (
    <AnimatePresence>
      {e && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/60" onClick={onClose}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
          <motion.section role="dialog" aria-label={e.symbol}
            className="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-lg rounded-t-3xl border border-b-0 border-line bg-panel px-5 pb-[max(24px,env(safe-area-inset-bottom))] pt-3"
            initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 38 }}
            drag="y" dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_, i) => { if (i.offset.y > 100 || i.velocity.y > 600) onClose(); }}>
            <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-line" />
            <div className="flex items-center gap-3">
              <TokenLogo src={e.image} symbol={e.symbol} size={48} />
              <div className="min-w-0 flex-1">
                <div className="text-[20px] font-semibold">{e.symbol}</div>
                <div className="truncate text-[13px] text-ink-dim">{e.name} · {chainTag(e.chain)}{age(e.launched_at) && ` · ${age(e.launched_at)}`}</div>
              </div>
              {e.score != null && <ScoreRing score={e.score} size={52} />}
            </div>
            <dl className="mt-5 grid grid-cols-3 gap-2">
              {[["Mcap", usd(e.market_cap)], ["FDV", usd(e.fdv)], ["Liquidity", usd(e.liquidity_usd)]].map(([k, v]) => (
                <div key={k} className="rounded-xl bg-raised p-3">
                  <dt className="text-[11px] text-ink-faint">{k}</dt>
                  <dd className="num mt-0.5 text-[15px]">{v}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-3 flex items-center justify-between rounded-xl bg-raised p-3 text-[13px]">
              <span className="text-ink-dim">24h</span><Change v={e.change_24h} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <a href={`/onchain-app.html#gems&token=${encodeURIComponent(e.chain)}:${encodeURIComponent(e.token_address)}`}
                className="rounded-xl bg-ink py-3 text-center text-[14px] font-semibold text-bg">Full dossier</a>
              {e.pair_url
                ? <a href={e.pair_url} target="_blank" rel="noreferrer" className="rounded-xl border border-line py-3 text-center text-[14px]">Chart ↗</a>
                : <button onClick={onClose} className="rounded-xl border border-line py-3 text-[14px]">Close</button>}
            </div>
          </motion.section>
        </>
      )}
    </AnimatePresence>
  );
}
