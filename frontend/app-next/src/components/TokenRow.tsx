import { motion } from "motion/react";
import type { Entry } from "../types";
import { age, usd } from "../format";
import { TokenLogo } from "./TokenLogo";
import { Change } from "./Change";

const CALM = [0.25, 0.1, 0.25, 1] as const;

export function TokenRow({ e, rank, i, onOpen }: { e: Entry; rank?: number; i: number; onOpen: (e: Entry) => void }) {
  return (
    <motion.li initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 10) * 0.03, duration: 0.26, ease: CALM }}>
      <button onClick={() => onOpen(e)} className="flex w-full items-center gap-3.5 rounded-2xl py-2.5 text-left transition-colors duration-150 active:bg-pill">
        <TokenLogo src={e.image} symbol={e.symbol} />
        <span className="min-w-0 flex-1">
          <b className="block truncate text-[16px] font-medium leading-tight">
            {rank != null && `${rank}. `}{e.name || e.symbol}
            {e.early && <em className="ml-1.5 rounded-full bg-sage px-1.5 text-[10px] font-semibold not-italic">EARLY</em>}
          </b>
          <small className="mt-1 flex items-center gap-2 text-[13.5px] text-ink-2">
            {e.score != null && <span className="num rounded-full bg-pill px-2 text-[12px] font-semibold leading-normal text-ink">{Math.round(e.score)}</span>}
            <span className="truncate">{e.symbol}</span>
            {age(e.launched_at) && <span className="flex items-center gap-0.5 text-ink-3"><svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round"><path d="M8 14V7M8 9c0-3 2-4.5 5-4.5 0 3-2 4.5-5 4.5ZM8 8C8 5.5 6.3 4 3.5 4c0 2.6 1.7 4 4.5 4Z" /></svg>{age(e.launched_at)}</span>}
          </small>
        </span>
        <span className="flex flex-col items-end gap-1">
          <b className="num text-[16px] font-semibold leading-none">{usd(e.market_cap)}</b>
          <Change v={e.change_24h} />
        </span>
      </button>
    </motion.li>
  );
}
