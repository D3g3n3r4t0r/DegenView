import type { Arena, Entry, Top } from "./types";

const rows: [string, string, string, number, number, number][] = [
  ["ZEPH", "Zephyr Protocol", "ai", 91, 8.4e6, 12.6], ["VOLT", "Volt Compute", "depin", 88, 4.1e6, -3.2],
  ["PATH", "Pathfinder", "ai", 86, 2.7e6, 5.1], ["VEIL", "Veil Finance", "defi", 84, 6.9e6, 21.4],
  ["BRIX", "Brix Labs", "rwa", 82, 1.2e6, -8.7], ["TIDE", "Tidewater", "defi", 79, 3.3e6, 1.9],
  ["NOVA", "Nova Layer", "layer", 77, 9.1e6, -0.6], ["KYRA", "Kyra AI", "ai", 75, 0.9e6, 34.2],
  ["MESH", "Meshwave", "depin", 73, 2.2e6, -12.1], ["ORBT", "Orbit RWA", "rwa", 71, 5.5e6, 4.4],
  ["HUSH", "Hush Network", "priv", 80, 3.9e6, 6.2], ["MASK", "Maskline", "priv", 74, 1.7e6, 2.4], ["PAYD", "Payday", "pay", 70, 2.9e6, -1.1], ["QUST", "Questfall", "game", 68, 0.8e6, -4.6],
];
const LABEL: Record<string, string> = { ai: "AI Agents", depin: "DePIN Compute", defi: "Perps & Derivatives", rwa: "RWA", layer: "Chains L0/L1/L2", priv: "Privacy", pay: "Stablecoin Payments", game: "Gaming" };
const CHAINS = ["solana", "base", "ethereum", "bsc", "robinhood"];

export function mockTop(): Promise<Top> {
  const entries: Entry[] = rows.map(([symbol, name, arena, score, mc, ch], i) => ({
    chain: CHAINS[i % CHAINS.length], token_address: `mock${i}`, symbol, name, score, market_cap: mc,
    fdv: mc * 1.4, liquidity_usd: mc * 0.08, change_24h: ch, launched_at: Date.now() / 1000 - (20 + i * 31) * 864e2,
    arena, arena_label: LABEL[arena],
  }));
  const arenas: Arena[] = Object.entries(LABEL).map(([key, label], i) => {
    const e = entries.filter((x) => x.arena === key);
    return { key, label, heat: 5 - i, size: e.length, entries: e };
  });
  return Promise.resolve({ entries, early: entries.slice(7).map((e) => ({ ...e, early: true })), arenas, p4p: entries.slice(0, 3).map((e, i) => ({ ...e, z: 2.4 - i * 0.5 })) });
}
