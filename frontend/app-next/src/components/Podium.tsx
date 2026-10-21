import { motion } from "motion/react";
import type { Entry } from "../types";
import { TokenLogo } from "./TokenLogo";

const sigma = (z?: number) => (z == null ? "" : `${z >= 0 ? "+" : "−"}${Math.abs(z).toFixed(1)}σ `);

// Pound for pound: the projects leading their own arena by the most. Three soft cards, big grey numbers.
export function Podium({ top, onOpen }: { top: Entry[]; onOpen: (e: Entry) => void }) {
  if (!top.length) return null;
  return (
    <div className="my-3 grid grid-cols-3 gap-2.5">
      {top.slice(0, 3).map((e, i) => (
        <motion.button key={e.chain + e.token_address} onClick={() => onOpen(e)}
          initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} whileTap={{ scale: 0.97 }}
          transition={{ delay: i * 0.05, duration: 0.26 }}
          className="relative grid min-h-[132px] content-end justify-items-start gap-0.5 rounded-[20px] bg-card p-3.5 text-left">
          <span className="num absolute right-3.5 top-2.5 text-[30px] leading-none tracking-tight text-ink-3 max-[374px]:text-[24px]">0{i + 1}</span>
          <span className="mb-auto"><TokenLogo src={e.image} symbol={e.symbol} size={44} /></span>
          <span className="mt-3.5 max-w-full truncate text-[15px] font-semibold">{e.symbol}</span>
          <span className="max-w-full truncate text-[13px] text-ink-2">{sigma(e.z)}{e.arena_label ?? ""}</span>
        </motion.button>
      ))}
    </div>
  );
}
