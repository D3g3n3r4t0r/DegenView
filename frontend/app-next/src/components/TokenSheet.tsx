import { AnimatePresence, motion } from "motion/react";
import type { Entry } from "../types";
import { age, chainTag, usd } from "../format";
import { TokenLogo } from "./TokenLogo";
import { Change } from "./Change";

// Token as a bottom sheet (direction A): drag down or tap outside to close.
export function TokenSheet({ e, onClose }: { e: Entry | null; onClose: () => void }) {
  return (
    <AnimatePresence>
      {e && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-ink/30" onClick={onClose}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
          <motion.section role="dialog" aria-label={e.symbol}
            className="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-lg rounded-t-[28px] bg-card px-5 pb-[max(24px,env(safe-area-inset-bottom))] pt-3"
            initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 38 }}
            drag="y" dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_, i) => { if (i.offset.y > 100 || i.velocity.y > 600) onClose(); }}>
            <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-ink-4" />
            <div className="flex items-center gap-3">
              <TokenLogo src={e.image} symbol={e.symbol} size={48} />
              <div className="min-w-0 flex-1">
                <div className="text-[20px] font-semibold">{e.symbol}</div>
                <div className="truncate text-[13px] text-ink-2">{e.name} · {chainTag(e.chain)}{age(e.launched_at) && ` · ${age(e.launched_at)}`}</div>
              </div>
              {e.score != null && <span className="num rounded-full bg-pill px-3 py-1 text-[15px] font-semibold">{Math.round(e.score)}</span>}
            </div>
            <dl className="mt-5 grid grid-cols-3 gap-2">
              {[["Mcap", usd(e.market_cap)], ["FDV", usd(e.fdv)], ["Liquidity", usd(e.liquidity_usd)]].map(([k, v]) => (
                <div key={k} className="rounded-2xl bg-pill p-3">
                  <dt className="text-[11px] text-ink-3">{k}</dt>
                  <dd className="num mt-0.5 text-[15px] font-semibold">{v}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-3 flex items-center justify-between rounded-2xl bg-pill p-3 text-[13px]">
              <span className="text-ink-2">24h</span><Change v={e.change_24h} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <a href={`/onchain-app.html#gems&token=${encodeURIComponent(e.chain)}:${encodeURIComponent(e.token_address)}`}
                className="rounded-full bg-ink py-3.5 text-center text-[15px] font-medium text-on-ink">Full dossier</a>
              {e.pair_url
                ? <a href={e.pair_url} target="_blank" rel="noreferrer" className="rounded-full bg-pill py-3.5 text-center text-[15px] font-medium">Chart ↗</a>
                : <button onClick={onClose} className="rounded-full bg-pill py-3.5 text-[15px] font-medium">Close</button>}
            </div>
          </motion.section>
        </>
      )}
    </AnimatePresence>
  );
}
