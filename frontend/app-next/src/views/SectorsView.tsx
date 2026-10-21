import { useState } from "react";
import { motion } from "motion/react";
import type { Entry, Top } from "../types";
import { TokenRow } from "../components/TokenRow";

export function SectorsView({ top, onOpen }: { top: Top; onOpen: (e: Entry) => void }) {
  const arenas = top.arenas.filter((a) => a.entries.length);
  const [key, setKey] = useState(arenas[0]?.key);
  const arena = arenas.find((a) => a.key === key) ?? arenas[0];
  if (!arena) return <p className="p-6 text-center text-ink-dim">The sectors are filling up.</p>;
  return (
    <>
      <div className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-3">
        {arenas.map((a) => (
          <button key={a.key} onClick={() => setKey(a.key)}
            className={`relative shrink-0 rounded-full px-3.5 py-1.5 text-[13px] transition-colors ${a.key === arena.key ? "text-bg" : "text-ink-dim"}`}>
            {a.key === arena.key && <motion.span layoutId="sector-pill" className="absolute inset-0 rounded-full bg-ink"
              transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
            <span className="relative">{a.label} <span className="num opacity-60">{a.entries.length}</span></span>
          </button>
        ))}
      </div>
      <ul key={arena.key}>{arena.entries.map((e, i) => <TokenRow key={e.chain + e.token_address} e={e} rank={i + 1} i={i} onOpen={onOpen} />)}</ul>
    </>
  );
}
