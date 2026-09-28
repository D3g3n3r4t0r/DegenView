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
