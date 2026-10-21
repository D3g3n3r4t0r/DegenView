import type { Entry } from "../types";
import { TokenRow } from "../components/TokenRow";

export function ListView({ rows, intro, empty, onOpen }: { rows: Entry[]; intro?: string; empty: string; onOpen: (e: Entry) => void }) {
  return (
    <>
      {intro && <p className="mx-0.5 mb-2 text-[15px] leading-snug text-ink-2">{intro}</p>}
      {rows.length
        ? <ol>{rows.map((e, i) => <TokenRow key={e.chain + e.token_address} e={e} rank={i + 1} i={i} onOpen={onOpen} />)}</ol>
        : <p className="py-8 text-center text-[14px] text-ink-2">{empty}</p>}
    </>
  );
}
