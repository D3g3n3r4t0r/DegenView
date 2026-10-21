import { pct } from "../format";

export function Change({ v }: { v?: number }) {
  const up = (v ?? 0) >= 0;
  return (
    <span className={`num rounded-md px-1.5 py-0.5 text-[12px] ${v == null ? "text-ink-faint" : up ? "bg-up/15 text-up" : "bg-down/15 text-down"}`}>
      {pct(v)}
    </span>
  );
}
