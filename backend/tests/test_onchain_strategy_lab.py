"""Backtest H24 dei token della schermata Strategie."""
from __future__ import annotations

import asyncio

import httpx
import numpy as np
import pytest

from app.notify import deepseek_desk
from app.trading.onchain import strategy_lab as lab


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_STORE_FILE", tmp_path / "lab.json")
    monkeypatch.setattr(deepseek_desk, "_STORE_FILE", tmp_path / "desk.json")
    lab.reset_for_tests()
    deepseek_desk.reset_for_tests()
    yield
    lab.reset_for_tests()


def _e(token, chain="solana", pair="Pair"):
    return {"chain": chain, "token_address": token, "pair_address": pair, "symbol": token.upper()}


def _bars(n=600, t0=1_790_000_000):
    rng = np.random.default_rng(1)
    closes = np.cumprod(1 + rng.normal(0.002, 0.02, n))
    return [[t0 + i * 300, c, c * 1.01, c * 0.99, c, 1000.0] for i, c in enumerate(closes)]


def test_next_due_takes_new_tokens_first_then_the_oldest():
    now = 1_800_000_000
    lab._results.update({"solana:a": {"at": now - 10}, "solana:b": {"at": now - 2 * lab.REFRESH_S},
                         "solana:c": {"at": now - 3 * lab.REFRESH_S}})
    entries = [_e("a"), _e("b"), _e("c"), _e("d"), _e("x", chain="nochain")]
    assert lab.next_due(entries, now)["token_address"] == "d"
    lab._results["solana:d"] = {"at": now}
    assert lab.next_due(entries, now)["token_address"] == "c"
    lab._results["solana:c"] = {"at": now}
    lab._results["solana:b"] = {"at": now}
    assert lab.next_due(entries, now) is None


def test_every_top_token_gets_every_strategy_and_the_agent_says_so(monkeypatch):
    async def candles(client, net, pool, tf, agg, before, limit, token=""):
        assert (net, pool, tf, agg) == ("solana", "Pair", "minute", 5)
        return list(reversed(_bars()))
    monkeypatch.setattr(lab.alert_track, "_candles", candles)
    out = asyncio.run(lab.tick([_e("tok")], now=1_800_000_000))
    bt = out["backtests"]
    assert bt["bars"] == 600 and {r["label"] for r in bt["rows"]} >= {"Trend EMA", "RSI+BB"}
    assert lab.get("solana", "tok") is bt
    assert lab.status([_e("tok"), _e("other")], now=1_800_000_000)["ready"] == 1
    line = deepseek_desk.log(1)[0]
    assert line["kind"] == "backtest" and "TOK" in line["text"]


def _daily_bars(n=200, t0=1_790_000_000):
    rng = np.random.default_rng(2)
    closes = np.cumprod(1 + rng.normal(0.003, 0.03, n))
    return [[t0 + i * 86400, c, c * 1.02, c * 0.98, c, 5000.0 + i] for i, c in enumerate(closes)]


def test_daily_backtest_runs_only_the_trend_follower(monkeypatch):
    async def candles(client, net, pool, tf, agg, before, limit, token=""):
        if (tf, agg) == ("day", 1):
            return _daily_bars()
        return _bars()
    monkeypatch.setattr(lab.alert_track, "_candles", candles)
    out = asyncio.run(lab.tick([_e("tok")], now=1_800_000_000))
    daily = out["daily"]
    assert daily["interval"] == "1d" and daily["bars"] == 200
    assert [r["label"] for r in daily["rows"]] == ["Trend EMA"]


def test_daily_falls_back_to_8h_when_the_daily_is_short(monkeypatch):
    async def candles(client, net, pool, tf, agg, before, limit, token=""):
        if (tf, agg) == ("day", 1):
            return _daily_bars(30)
        if (tf, agg) == ("hour", 4):
            return _bars(400)
        return _bars()
    monkeypatch.setattr(lab.alert_track, "_candles", candles)
    out = asyncio.run(lab.tick([_e("tok")], now=1_800_000_000))
    daily = out["daily"]
    assert daily["interval"] == "8h"
    assert all(b[0] % 28800 == 0 for b in lab._merge_8h(_bars(400)))


def test_daily_too_few_candles_is_an_error_and_does_not_drop_the_5m(monkeypatch):
    async def candles(client, net, pool, tf, agg, before, limit, token=""):
        if (tf, agg) == ("day", 1):
            return _daily_bars(10)
        if (tf, agg) == ("hour", 4):
            return _bars(10)
        return _bars()
    monkeypatch.setattr(lab.alert_track, "_candles", candles)
    out = asyncio.run(lab.tick([_e("tok")], now=1_800_000_000))
    assert out["daily"] == {"interval": "8h", "bars": 1, "error": "too few candles"}
    assert out["backtests"]["bars"] == 600


def test_daily_fetch_failure_keeps_the_5m_result(monkeypatch):
    async def candles(client, net, pool, tf, agg, before, limit, token=""):
        if (tf, agg) == ("day", 1):
            return None
        return _bars()
    monkeypatch.setattr(lab.alert_track, "_candles", candles)
    out = asyncio.run(lab.tick([_e("tok")], now=1_800_000_000))
    assert "daily" not in out and out["backtests"]["bars"] == 600


def test_gecko_busy_retries_next_tick_and_a_missing_pool_is_resolved(monkeypatch):
    async def busy(*a, **k):
        return None
    monkeypatch.setattr(lab.alert_track, "_candles", busy)
    assert asyncio.run(lab.tick([_e("tok")], now=1_800_000_000)) is None
    assert lab.next_due([_e("tok")], 1_800_000_000) is not None

    seen = {}

    async def candles(client, net, pool, *a):
        seen["pool"] = pool
        return _bars(50)
    monkeypatch.setattr(lab.alert_track, "_candles", candles)

    def handler(req):
        return httpx.Response(200, json=[{"chainId": "solana", "pairAddress": "Thin", "liquidity": {"usd": 5}},
                                         {"chainId": "solana", "pairAddress": "Deep", "liquidity": {"usd": 900}}])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await lab.run_one(c, _e("tok", pair=None), 1_800_000_000)
    assert asyncio.run(go())["pair"] == "Deep" and seen["pool"] == "Deep"


def test_backtest_one_returns_only_the_trend_follower():
    from app.trading.onchain import system
    bt = system.backtest_one(_bars(600))
    assert [r["label"] for r in bt["rows"]] == ["Trend EMA"]
    assert bt["bars"] == 600 and bt["best"] is not None
