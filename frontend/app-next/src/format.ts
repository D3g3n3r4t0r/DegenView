export function usd(v?: number): string {
  if (v == null || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

export function pct(v?: number): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

const CHAINS: Record<string, string> = { solana: "SOL", bsc: "BSC", ethereum: "ETH", base: "BASE", robinhood: "HOOD" };
export const chainTag = (c: string) => CHAINS[c] ?? c.slice(0, 4).toUpperCase();

export function age(t?: number | string): string {
  if (t == null) return "";
  const ms = typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : Date.parse(t);
  if (!isFinite(ms)) return "";
  const d = Math.floor((Date.now() - ms) / 864e5);
  return d < 1 ? "today" : d < 60 ? `${d}d` : `${Math.round(d / 30)}mo`;
}
