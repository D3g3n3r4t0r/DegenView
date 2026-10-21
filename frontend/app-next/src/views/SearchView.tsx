import { useMemo, useState } from "react";
import type { Entry, Top } from "../types";
import { TokenRow } from "../components/TokenRow";

export function SearchView({ top, onOpen }: { top: Top; onOpen: (e: Entry) => void }) {
  const [q, setQ] = useState("");
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase();
    const all = [...top.entries, ...top.early];
    const seen = new Set<string>();
    return all.filter((e) => {
      const id = e.chain + e.token_address;
      if (seen.has(id)) return false;
      seen.add(id);
      return !s || e.symbol.toLowerCase().includes(s) || (e.name ?? "").toLowerCase().includes(s) || e.token_address.toLowerCase() === s;
    });
  }, [q, top]);
  return (
    <>
      <input autoFocus value={q} onChange={(ev) => setQ(ev.target.value)} placeholder="Ticker, name or address"
        className="mb-3 w-full rounded-xl border border-line bg-panel px-4 py-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-ink-faint" />
      <ul>{hits.map((e, i) => <TokenRow key={e.chain + e.token_address} e={e} rank={i + 1} i={i} onOpen={onOpen} />)}</ul>
    </>
  );
}
