"""Ponte sniper -> watchlist -> wallet: Lorenzo, "la strategia trend
follower [...] inglobata sul wallet, così da usarla automaticamente su
dei ticker on chain sfruttando la logica dello sniper". Il ponte fa solo
l'upsert in watchlist con la strategia di Lorenzo attiva — l'esecuzione
resta quella gia' testata altrove (_run_onchain_auto_trade)."""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import auth, main, watchlist as watchlist_store
from app.trading.onchain import ledger as onchain_ledger


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(watchlist_store, "_STORE_FILE", tmp_path / "watchlist.json")
    monkeypatch.setattr(onchain_ledger, "_DB_FILE", tmp_path / "ledger.db")
    monkeypatch.setattr(main.onchain_listings, "recent", lambda: [])

    async def _vet_ok(candidate):
        return {"status": "ok", "reason": "", "checks": []}
    monkeypatch.setattr(main, "_pilot_vet", _vet_ok)
    onchain_ledger._init_db()
    auth._users.clear()
    watchlist_store._entries.clear()
    user = auth.create_user("trader@example.com", "correct-horse-battery-9")
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.get_user(user.id)
    with TestClient(main.app) as c:
        c.owner_id = user.id
        yield c
    main.app.dependency_overrides.clear()
    watchlist_store._entries.clear()


def _fake_candidate(**overrides):
    from app.sniper.cache import Candidate
    defaults = dict(
        chain_id="solana", token_address="MintAddr111111111111111111111111111",
        pair_address="PoolAddr222222222222222222222222", symbol="NEWCOIN", name="New Coin",
        dex_id="raydium", pair_url="https://dexscreener.com/x", price_usd=0.01,
        market_cap=100_000, liquidity_usd=5000.0, volume_h24=1000, volume_h1=100,
        age_hours=2.0, buy_sell_ratio=1.2, website=None,
    )
    defaults.update(overrides)
    return Candidate(**defaults)


def test_autotrade_toggle_requires_a_wallet(client):
    resp = client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": True})
    assert resp.status_code == 400


def test_autotrade_toggle_persists(client):
    client.post("/api/onchain/wallets", json={"chain": "solana"})
    resp = client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["chains"] == ["solana"]

    resp = client.get("/api/onchain/sniper-autotrade")
    assert resp.json()["chains"] == ["solana"]

    resp = client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": False})
    assert resp.json()["chains"] == []


def test_bridge_adds_qualifying_candidate_with_lorenzo_strategy(client, monkeypatch):
    client.post("/api/onchain/wallets", json={"chain": "solana"})
    client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": True})
    monkeypatch.setattr(main.settings, "sniper_enabled", True)

    candidate = _fake_candidate()

    async def _fake_get_candidates():
        return [candidate]

    async def _fake_fetch_ohlcv(self, symbol, interval, outputsize, since_ms=None):
        return pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})

    monkeypatch.setattr("app.sniper.cache.get_candidates", lambda: [candidate])
    monkeypatch.setattr(main.dexscreener_provider.__class__, "fetch_ohlcv", _fake_fetch_ohlcv)

    _run(main._sniper_onchain_bridge_tick())

    owner_id = client.owner_id
    entries = watchlist_store.list_entries(owner_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.symbol == f"NEWCOIN@solana:{candidate.pair_address}"
    assert entry.base_token_address == candidate.token_address
    assert main._SNIPER_ONCHAIN_STRATEGY in entry.strategies
    assert entry.auto_trade.get(main._SNIPER_ONCHAIN_STRATEGY) is True


def test_bridge_skips_low_liquidity_candidate(client, monkeypatch):
    client.post("/api/onchain/wallets", json={"chain": "solana"})
    client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": True})
    monkeypatch.setattr(main.settings, "sniper_enabled", True)

    candidate = _fake_candidate(liquidity_usd=100.0)
    monkeypatch.setattr("app.sniper.cache.get_candidates", lambda: [candidate])

    _run(main._sniper_onchain_bridge_tick())

    assert watchlist_store.list_entries(client.owner_id) == []


def test_bridge_never_hands_the_pilot_a_token_that_fails_the_filter(client, monkeypatch):
    client.post("/api/onchain/wallets", json={"chain": "solana"})
    client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": True})
    monkeypatch.setattr(main.settings, "sniper_enabled", True)

    async def _vet_fail(candidate):
        return {"status": "fail", "reason": "RugCheck: Mint authority", "checks": []}
    monkeypatch.setattr(main, "_pilot_vet", _vet_fail)
    big = _fake_candidate(symbol="BIG", token_address="Big1", pair_address="BigPool", market_cap=900_000)
    monkeypatch.setattr("app.sniper.cache.get_candidates", lambda: [_fake_candidate(), big])

    _run(main._sniper_onchain_bridge_tick())

    assert watchlist_store.list_entries(client.owner_id) == []


def test_bridge_takes_vetted_listings_on_an_interval_that_fits_their_age(client, monkeypatch):
    import time as _t
    client.post("/api/onchain/wallets", json={"chain": "solana"})
    client.patch("/api/onchain/sniper-autotrade/solana", json={"enabled": True})
    monkeypatch.setattr(main.settings, "sniper_enabled", True)
    listing = {"chain": "solana", "symbol": "ACME", "name": "Acme", "token_address": "AcmeMint",
               "pair_address": "AcmePool", "liquidity_usd": 20_000, "market_cap": 80_000,
               "created_at": _t.time() - 1800, "website": "https://acme.io"}
    monkeypatch.setattr(main.onchain_listings, "recent", lambda: [listing])
    monkeypatch.setattr("app.sniper.cache.get_candidates", lambda: [])

    async def _vet_never(candidate):
        raise AssertionError("un listing e' gia' verificato")
    monkeypatch.setattr(main, "_pilot_vet", _vet_never)

    async def _fake_fetch_ohlcv(self, symbol, interval, outputsize, since_ms=None):
        return pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
    monkeypatch.setattr(main.dexscreener_provider.__class__, "fetch_ohlcv", _fake_fetch_ohlcv)

    _run(main._sniper_onchain_bridge_tick())

    entry = watchlist_store.list_entries(client.owner_id)[0]
    assert entry.symbol == "ACME@solana:AcmePool" and entry.interval == "1m"
