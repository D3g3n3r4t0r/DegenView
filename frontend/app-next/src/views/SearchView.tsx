import { useMemo } from "react";
import type { Entry, Top } from "../types";
import { ScanField } from "../components/ScanField";
import { ListView } from "./ListView";

export function SearchView({ top, q, onScan, onOpen }: { top: Top; q: string; onScan: (q: string) => void; onOpen: (e: Entry) => void }) {
  const hits = useMemo(() => {
    const s = q.toLowerCase();
    const seen = new Set<string>();
    return [...top.entries, ...top.early, ...top.arenas.flatMap((a) => a.entries)].filter((e) => {
      const id = e.chain + e.token_address;
      if (seen.has(id)) return false;
      seen.add(id);
      return !!s && (e.symbol.toLowerCase().includes(s) || (e.name ?? "").toLowerCase().includes(s) || e.token_address.toLowerCase() === s);
    });
  }, [q, top]);
  return (
    <>
      <ScanField onScan={onScan} autoFocus />
      <div className="mt-4">
        <ListView rows={hits} onOpen={onOpen}
          empty={q ? `Nothing called "${q}" among the projects we follow.` : "Type a ticker, a name or an address."} />
      </div>
    </>
  );
}
