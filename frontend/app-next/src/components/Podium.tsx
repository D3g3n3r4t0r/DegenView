import { motion } from "motion/react";
import type { Entry } from "../types";
import { TokenLogo } from "./TokenLogo";
import { AnimatedNumber } from "./AnimatedNumber";

const ORDER = [1, 0, 2]; // silver, gold, bronze
const HEIGHT = ["h-24", "h-16", "h-12"];
const RING = ["ring-amber", "ring-ink-dim", "ring-[#c8824a]"];
const int = (v: number) => String(Math.round(v));

// The Top's best three, pound for pound across sectors.
export function Podium({ top, onOpen }: { top: Entry[]; onOpen: (e: Entry) => void }) {
  if (top.length < 3) return null;
  return (
    <div className="grid grid-cols-3 items-end gap-2 px-1 pt-2">
      {ORDER.map((p) => {
        const e = top[p];
        return (
          <motion.button key={e.token_address} onClick={() => onOpen(e)} className="flex flex-col items-center gap-2"
            initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.08 * (p + 1), type: "spring", stiffness: 260, damping: 24 }}>
            <div className={`rounded-full ring-2 ring-offset-2 ring-offset-bg ${RING[p]}`}>
              <TokenLogo src={e.image} symbol={e.symbol} size={p === 0 ? 52 : 42} />
            </div>
            <span className="max-w-full truncate text-[13px] font-semibold">{e.symbol}</span>
            <div className={`flex w-full flex-col items-center justify-start rounded-t-xl border border-b-0 border-line bg-gradient-to-b from-raised to-bg pt-2 ${HEIGHT[p]}`}>
              <span className="text-[18px] font-semibold"><AnimatedNumber value={e.score ?? 0} format={int} /></span>
              <span className="text-[10px] uppercase tracking-wider text-ink-faint">{e.arena_label ?? "score"}</span>
            </div>
          </motion.button>
        );
      })}
    </div>
  );
}
