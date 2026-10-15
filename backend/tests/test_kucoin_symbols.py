"""KuCoin, every quote (Lorenzo, 15/10: "nei pair a disposizione sul sito,
quelli relativi a KuCoin non compaiono [...] avere a disposizione anche
tutti i pair presenti su KuCoin"). It was scoped to BTC pairs only: ETHUSDT
became "ETHUSDT-BTC", which does not exist."""

from __future__ import annotations

import asyncio

from app.providers import kucoin
from app.providers.kucoin import KucoinProvider, format_symbol


def test_every_quote_is_kept():
    assert format_symbol("ETHUSDT") == "ETH-USDT"
    assert format_symbol("eth/usdt") == "ETH-USDT"
    assert format_symbol("BTCUSDT") == "BTC-USDT"
    assert format_symbol("SOLUSDC") == "SOL-USDC"
    assert format_symbol("ETHBTC") == "ETH-BTC"
    assert format_symbol("KCS-BTC") == "KCS-BTC"


def test_a_bare_base_still_means_the_btc_pair():
    # symbols saved before (drawings, alerts) keep their chart
    assert format_symbol("ETH") == "ETH-BTC"


def test_search_lists_usdt_pairs_first(monkeypatch):
    rows = [{"symbol": s, "baseCurrency": s.split("-")[0], "quoteCurrency": s.split("-")[1], "enableTrading": True}
            for s in ("ETH-BTC", "ETH-USDC", "ETH-USDT", "ETHFI-USDT", "SOL-USDT")]
    kucoin._symbols_cache["all"] = rows
    try:
        out = asyncio.run(KucoinProvider().search_symbols("ETH"))
        assert [o["symbol"] for o in out][:3] == ["ETH-USDT", "ETH-BTC", "ETH-USDC"]
        assert "ETHFI-USDT" in [o["symbol"] for o in out] and "SOL-USDT" not in [o["symbol"] for o in out]
        assert out[0]["exchange"] == "KuCoin (USDT)"
        assert [o["symbol"] for o in asyncio.run(KucoinProvider().search_symbols("ETHUSDT"))] == ["ETH-USDT"]
    finally:
        kucoin._symbols_cache.clear()


def test_monthly_candles_are_folded_from_the_daily_ones(monkeypatch):
    # 15/10: "time frame 1 month not supported on KuCoin" with 1d selected —
    # the analysis loads the 1M higher timeframe too
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="D", tz="UTC")
    daily = pd.DataFrame({"open": np.arange(len(idx)) + 1.0, "high": np.arange(len(idx)) + 2.0,
                          "low": np.arange(len(idx)) + 0.5, "close": np.arange(len(idx)) + 1.5,
                          "volume": 1.0}, index=idx)
    seen = []

    async def fake(self, symbol, interval, outputsize, since_ms=None, _orig=KucoinProvider.fetch_ohlcv):
        if interval == "1M":
            return await _orig(self, symbol, interval, outputsize, since_ms)
        seen.append(interval)
        return daily
    monkeypatch.setattr(KucoinProvider, "fetch_ohlcv", fake)
    m = asyncio.run(KucoinProvider().fetch_ohlcv("ETHUSDT", "1M", 12))
    assert seen == ["1d"] and len(m) == 3
    assert m["open"].iloc[1] == daily.loc["2024-02-01", "open"]
    assert m["close"].iloc[1] == daily.loc["2024-02-29", "close"]
    assert m["volume"].iloc[0] == 31
