import { motion } from "motion/react";
import type { Entry } from "../types";
import { age, chainTag, usd } from "../format";
import { TokenLogo } from "./TokenLogo";
import { ScoreRing } from "./ScoreRing";
import { Change } from "./Change";

export function TokenRow({ e, rank, i, onOpen }: { e: Entry; rank: number; i: number; onOpen: (e: Entry) => void }) {
  return (
    <motion.li layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(i, 12) * 0.03, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}>
      <button onClick={() => onOpen(e)}
        className="flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-white/5 active:scale-[0.99]">
        <span className="num w-5 text-right text-[12px] text-ink-faint">{rank}</span>
        <TokenLogo src={e.image} symbol={e.symbol} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-semibold">{e.symbol}</span>
            <span className="rounded bg-raised px-1 text-[10px] text-ink-dim">{chainTag(e.chain)}</span>
          </div>
          <div className="truncate text-[12px] text-ink-dim">
            {e.arena_label ?? e.name}{age(e.launched_at) && <> · {age(e.launched_at)}</>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <span className="num text-[13px]">{usd(e.market_cap)}</span>
          <Change v={e.change_24h} />
        </div>
        {e.score != null && <ScoreRing score={e.score} />}
      </button>
    </motion.li>
  );
}
