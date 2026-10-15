"""Live check of a crypto provider from CI (the sandbox cannot reach the
exchanges): search, symbol form and candle depth, as ::notice:: lines.

    cd backend && PYTHONPATH=. python ../scripts/provider_check.py kucoin ETH ETHUSDT SOLUSDT ETHBTC
"""
from __future__ import annotations

import asyncio
import sys


async def main(name: str, query: str, symbols: list[str]) -> int:
    from app.providers.kucoin import KucoinProvider, format_symbol
    prov = {"kucoin": KucoinProvider}[name]()
    try:
        found = await prov.search_symbols(query)
        print(f"::notice title={name} search {query}::{len(found)} results: "
              + ", ".join(f"{f['symbol']} ({f['exchange']})" for f in found[:12]))
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={name} search::{type(exc).__name__}: {exc}")
    for sym in symbols:
        for tf in ("4h", "1d"):
            try:
                df = await prov.fetch_ohlcv(sym, tf, 20000)
                print(f"::notice title={name} {sym} {tf}::{format_symbol(sym)}: {len(df)} candles "
                      f"{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}")
            except Exception as exc:  # noqa: BLE001
                print(f"::warning title={name} {sym} {tf}::{format_symbol(sym)}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3:])))
