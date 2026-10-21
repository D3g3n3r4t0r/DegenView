import { useState } from "react";
import { motion } from "motion/react";
import type { Entry, Top } from "../types";
import { Podium } from "../components/Podium";
import { Mosaic } from "../components/Mosaic";
import { ScanField } from "../components/ScanField";

type Sub = "arenas" | "database";

export function GemsView({ top, onOpen, onScan }: { top: Top; onOpen: (e: Entry) => void; onScan: (q: string) => void }) {
  const [sub, setSub] = useState<Sub>("arenas");
  const [open, setOpen] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  return (
    <>
      <div className="flex gap-2">
        {(["arenas", "database"] as Sub[]).map((s) => (
          <button key={s} onClick={() => setSub(s)} aria-pressed={sub === s}
            className={`relative h-10 rounded-full px-[18px] text-[15px] font-medium capitalize transition-colors duration-200 ${sub === s ? "text-on-ink" : "bg-pill text-ink-2"}`}>
            {sub === s && <motion.span layoutId="gems-sub" className="absolute inset-0 rounded-full bg-ink" transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
            <span className="relative">{s}</span>
          </button>
        ))}
      </div>
      <ScanField onScan={onScan} />
      {sub === "arenas" ? (
        <>
          <Podium top={top.p4p} onOpen={onOpen} />
          <Mosaic arenas={top.arenas} open={open} onPick={setOpen} all={all} onAll={() => setAll(true)} onOpen={onOpen} />
        </>
      ) : (
        <p className="py-8 text-center text-[14px] text-ink-2">
          The project database moves here in the next step. Until then it is in the <a className="underline" href="/onchain-app.html#gems">current app</a>.
        </p>
      )}
    </>
  );
}
