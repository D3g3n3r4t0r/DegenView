"""DEX candles come page by page, so the classic site backtests the whole
chart instead of the last 1000 candles (Lorenzo, 12/10)."""
import asyncio

from app.providers import dexscreener as ds

DAY = 86400
NOW = 1_800_000_000
TOTAL = 2500  # candles the pool really has


def _fake_gecko(calls):
    async def fake(url, params=None, caller=None):
        calls.append(dict(params or {}))
        before = params.get("before_timestamp", NOW + DAY)
        limit = params["limit"]
        stamps = [t for t in (NOW - i * DAY for i in range(TOTAL)) if t < before][:limit]
        return {"data": {"attributes": {"ohlcv_list": [[t, 1, 2, 0.5, 1.5, 10] for t in stamps]}}}
    return fake


def _symbol():
    return "TOK@solana:So11111111111111111111111111111111111111112"


def test_pages_until_the_history_ends(monkeypatch):
    calls = []
    monkeypatch.setattr(ds, "gecko_get", _fake_gecko(calls))
    df = asyncio.run(ds.DexScreenerProvider().fetch_ohlcv(_symbol(), "1d", 5000))
    assert len(df) == TOTAL
    assert len(calls) == 3
    assert "before_timestamp" not in calls[0]
    assert calls[1]["before_timestamp"] == NOW - 999 * DAY
    assert df.index.is_monotonic_increasing


def test_small_request_is_one_page(monkeypatch):
    calls = []
    monkeypatch.setattr(ds, "gecko_get", _fake_gecko(calls))
    df = asyncio.run(ds.DexScreenerProvider().fetch_ohlcv(_symbol(), "1d", 200))
    assert len(df) == 200 and len(calls) == 1 and calls[0]["limit"] == 200


def test_since_stops_at_the_start(monkeypatch):
    calls = []
    monkeypatch.setattr(ds, "gecko_get", _fake_gecko(calls))
    since = (NOW - 1200 * DAY) * 1000
    df = asyncio.run(ds.DexScreenerProvider().fetch_ohlcv(_symbol(), "1d", 0, since_ms=since))
    assert len(df) == 1201
    assert len(calls) == 2
