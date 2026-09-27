import asyncio

import pandas as pd

from app.trading.onchain import radar


def _setup(monkeypatch, calls, fail=False):
    async def fetch(self, symbol, interval, size):
        calls.append((symbol, interval, size))
        if fail:
            raise RuntimeError("429")
        idx = pd.date_range("2026-09-27", periods=3, freq="5min", tz="UTC")
        return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": [1.0, 1.5, 1.2], "volume": 1.0}, index=idx)

    monkeypatch.setattr(radar.DexScreenerProvider, "fetch_ohlcv", fetch)
    monkeypatch.setattr(radar, "chart_strategies", lambda *a: (_ for _ in ()).throw(AssertionError("no backtests")))


def test_token_chart_is_candles_only_and_cached(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    radar._lite_cache.clear()
    out = asyncio.run(radar.chart_candles("bsc", "0xpool", "FROG", "5m"))
    assert [c["close"] for c in out["candles"]] == [1.0, 1.5, 1.2]
    assert calls[0][2] == radar.CANDLES_LITE < 1000
    asyncio.run(radar.chart_candles("bsc", "0xpool", "FROG", "5m"))
    assert len(calls) == 1          # second look within 30 s: from the cache


def test_older_copy_is_served_at_once(monkeypatch):
    # "il grafico impiega almeno 10 secondi ad aprirsi": never wait when a copy exists
    calls = []
    _setup(monkeypatch, calls, fail=True)
    radar._lite_cache.clear()
    radar._lite_cache[("solana", "P", "5m")] = (radar.time.time() - 600, [{"time": 1, "close": 2.0}])
    out = asyncio.run(radar.chart_candles("solana", "P", "X", "5m"))
    assert out["candles"] == [{"time": 1, "close": 2.0}]


def test_warm_fetches_what_is_on_screen_once(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    radar._lite_cache.clear()
    targets = [("solana", "P1", "A", "5m"), ("bsc", "P2", "B", "1h"), ("", "P3", "C", "5m")]
    assert asyncio.run(radar.warm_charts(targets, gap_s=0)) == 2
    assert asyncio.run(radar.warm_charts(targets, gap_s=0)) == 0     # fresh: not fetched again
    assert ("bsc", "P2", "1h") in radar._lite_cache


def test_peek_never_calls_geckoterminal(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    radar._lite_cache.clear()
    assert radar.chart_peek("solana", "P", "5m")["candles"] == []
    radar._lite_cache[("solana", "P", "5m")] = (radar.time.time() - 60, [{"time": 1, "close": 2.0}])
    assert radar.chart_peek("solana", "P", "5m")["candles"] == [{"time": 1, "close": 2.0}]
    assert calls == []
