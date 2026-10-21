export type Entry = {
  chain: string;
  token_address: string;
  symbol: string;
  name?: string;
  image?: string;
  score?: number;
  market_cap?: number;
  fdv?: number;
  liquidity_usd?: number;
  change_24h?: number;
  launched_at?: number | string;
  pair_url?: string;
  arena?: string;
  arena_label?: string;
};

export type Arena = { key: string; label: string; heat: number; size: number; entries: Entry[] };

export type Top = { entries: Entry[]; early: Entry[]; arenas: Arena[]; p4p: Entry[] };
