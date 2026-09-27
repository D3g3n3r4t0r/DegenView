import asyncio

import pandas as pd

from app.trading.onchain import radar


def test_token_chart_is_candles_only_and_cached(monkeypatch):
    calls = []

    async def fetch(self, symbol, interval, size):
        calls.append((symbol, interval, size))
        idx = pd.date_range("2026-09-27", periods=3, freq="5min", tz="UTC")
        return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": [1.0, 1.5, 1.2], "volume": 1.0}, index=idx)

    monkeypatch.setattr(radar.DexScreenerProvider, "fetch_ohlcv", fetch)
    monkeypatch.setattr(radar, "chart_strategies", lambda *a: (_ for _ in ()).throw(AssertionError("no backtests")))
    radar._chart_cache.clear()
    out = asyncio.run(radar.chart_candles("bsc", "0xpool", "FROG", "5m"))
    assert [c["close"] for c in out["candles"]] == [1.0, 1.5, 1.2]
    assert calls[0][2] == radar.CANDLES_LITE < 1000
    asyncio.run(radar.chart_candles("bsc", "0xpool", "FROG", "5m"))
    assert len(calls) == 1          # second look within 30 s: from the cache
