"""Listing appena usciti con liquidita': Lorenzo li vuole "quasi istantanei"."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.trading.onchain import listings as L


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "_STORE_FILE", tmp_path / "listings.json")
    monkeypatch.setattr(L, "_callbacks", [])
    L.reset_for_tests()
    yield
    L.reset_for_tests()


def _pair(pool="P1", symbol="NEW", liq=50_000, cap=400_000, age_s=120, chain="solana"):
    return {"chainId": chain, "pairAddress": pool, "dexId": "pumpswap", "url": f"https://dexscreener.com/{chain}/{pool}",
            "baseToken": {"address": f"T{pool}", "symbol": symbol, "name": symbol},
            "liquidity": {"usd": liq}, "marketCap": cap, "pairCreatedAt": (time.time() - age_s) * 1000}


def test_pool_address_from_v3_and_v2_creation_logs():
    v3 = {"topics": [L.POOL_CREATED_V3], "data": "0x" + "0" * 63 + "a" + "0" * 24 + "ab" * 20}
    v2 = {"topics": [L.PAIR_CREATED_V2], "data": "0x" + "0" * 24 + "cd" * 20 + "0" * 63 + "1"}
    other = {"topics": ["0xdead"], "data": "0x" + "0" * 128}
    assert L.pools_from_logs([v3, v2, other]) == ["0x" + "ab" * 20, "0x" + "cd" * 20]


def test_pumpfun_only_young_graduates():
    now = time.time()
    coins = [
        {"complete": True, "created_timestamp": (now - 600) * 1000, "pump_swap_pool": "Fresh"},
        {"complete": False, "created_timestamp": (now - 60) * 1000, "pump_swap_pool": "Curve"},
        {"complete": True, "created_timestamp": (now - 10 * 3600) * 1000, "pump_swap_pool": "Old"},
    ]
    assert L.pools_from_pumpfun(coins, now) == ["Fresh"]


@pytest.mark.parametrize("kw, ok", [
    ({}, True),
    ({"liq": 5_000}, False),
    ({"cap": 90_000_000}, False),
    ({"liq": 21_000, "cap": 1_000_000}, False),   # 2% della cap
    ({"age_s": 8 * 3600}, False),
    ({"symbol": "WETH"}, False),
])
def test_thresholds(kw, ok):
    assert (L.evaluate_pair(_pair(**kw)) is not None) is ok


def test_one_alert_per_ticker_and_waits_for_liquidity():
    L.add_pending("solana", "P1", "pumpfun")
    L.add_pending("solana", "P2", "gecko")
    assert asyncio.run(L.accept_pairs([_pair("P1", liq=100)])) == []   # ancora senza liquidita'
    assert "solana:P1" in L._pending
    got = asyncio.run(L.accept_pairs([_pair("P1"), _pair("P2", symbol="new")]))
    assert [g["pair_address"] for g in got] == ["P1"]
    assert got[0]["source"] == "pumpfun" and got[0]["latency_s"] >= 119
    assert L.recent()[0]["symbol"] == "NEW"
    assert not L.add_pending("solana", "P1", "gecko")  # gia' chiuso


def test_subscribers_get_every_listing_but_telegram_only_fresh_ones():
    seen = []

    async def cb(item):
        seen.append(item["symbol"])
    L.on_listing(cb)
    q = L.subscribe()
    L.add_pending("solana", "A", "gecko")
    L.add_pending("solana", "B", "gecko")
    asyncio.run(L.accept_pairs([_pair("A", symbol="FRESH", age_s=60), _pair("B", symbol="LATE", age_s=3 * 3600)]))
    assert seen == ["FRESH"]
    assert q.qsize() == 2


def test_full_pending_drops_the_oldest_never_the_new(monkeypatch):
    monkeypatch.setattr(L, "MAX_PENDING", 2)
    L.add_pending("robinhood", "0x1", "chain")
    L.add_pending("robinhood", "0x2", "chain")
    assert L.add_pending("robinhood", "0x3", "chain")
    assert set(L._pending) == {"robinhood:0x2", "robinhood:0x3"}


def test_pending_expires():
    L.add_pending("solana", "Z", "gecko")
    L._pending["solana:Z"].detected_at -= L.PENDING_TTL_S + 1
    asyncio.run(L.accept_pairs([]))
    assert not L._pending
