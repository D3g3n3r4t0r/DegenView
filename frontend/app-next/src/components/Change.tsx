// The 24h move as the current app shows it: an arrow and the percentage, coloured only by sign.
export function Change({ v }: { v?: number }) {
  if (v == null || !isFinite(v)) return <em className="num not-italic text-[13px] text-ink-3">—</em>;
  const p = Math.abs(v);
  const txt = p >= 1000 ? Math.round(p).toLocaleString("en-US") : p >= 10 ? Math.round(p) : p.toFixed(1);
  return <em className={`num not-italic text-[13px] font-medium ${v >= 0 ? "text-up" : "text-down"}`}>{v >= 0 ? "↑" : "↓"} {txt}%</em>;
}
