import type { Entry, Top } from "../types";
import { Podium } from "../components/Podium";
import { TokenRow } from "../components/TokenRow";
import { AnimatedNumber } from "../components/AnimatedNumber";

const int = (v: number) => String(Math.round(v));

export function TodayView({ top, onOpen }: { top: Top; onOpen: (e: Entry) => void }) {
  const podium = top.p4p.length >= 3 ? top.p4p : top.entries;
  const sectors = top.arenas.filter((a) => a.entries.length).length;
  const ups = top.entries.filter((e) => (e.change_24h ?? 0) > 0).length;
  return (
    <>
      <div className="grid grid-cols-3 gap-2">
        {[["Gems", top.entries.length], ["Sectors", sectors], ["Up 24h", ups]].map(([k, v]) => (
          <div key={k} className="rounded-2xl border border-line bg-panel p-3">
            <div className="text-[11px] text-ink-faint">{k}</div>
            <div className="text-[22px] font-semibold"><AnimatedNumber value={v as number} format={int} /></div>
          </div>
        ))}
      </div>
      <Podium top={podium} onOpen={onOpen} />
      <h2 className="mb-1 mt-5 px-2 text-[12px] font-medium uppercase tracking-wider text-ink-faint">Top</h2>
      <ul>{top.entries.map((e, i) => <TokenRow key={e.chain + e.token_address} e={e} rank={i + 1} i={i} onOpen={onOpen} />)}</ul>
    </>
  );
}
