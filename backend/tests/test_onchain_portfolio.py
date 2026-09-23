"""Piano ecosistema DEX: /api/onchain/portfolio, cosa detiene DAVVERO il
wallet (RPC vera), non solo le posizioni tracciate dal ledger."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.trading.onchain import balances as onchain_balances
from app.trading.onchain import ledger as onchain_ledger
from app.trading.onchain import token_metadata as onchain_token_metadata


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(onchain_ledger, "_DB_FILE", tmp_path / "ledger.db")
    onchain_ledger._init_db()
    auth._users.clear()
    user = auth.create_user("trader@example.com", "correct-horse-battery-9")
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.get_user(user.id)
    with TestClient(main.app) as c:
        c.owner_id = user.id
        yield c
    main.app.dependency_overrides.clear()


def test_portfolio_requires_a_wallet(client):
    resp = client.get("/api/onchain/portfolio/solana")
    assert resp.status_code == 400


def test_portfolio_lists_real_solana_token_balances(client, monkeypatch):
    client.post("/api/onchain/wallets", json={"chain": "solana"})

    async def _fake_balances(chain, address, known_evm_tokens=None):
        return [{"address": "SomeMint111111111111111111111111111111111", "amount": 42.5, "decimals": 9}]

    async def _fake_meta(chain, address):
        return {"address": address, "decimals": 9, "symbol": "FAKE", "price_usd": 2.0}

    monkeypatch.setattr(onchain_balances, "all_token_balances", _fake_balances)
    monkeypatch.setattr(main, "_onchain_token_meta", _fake_meta)

    resp = client.get("/api/onchain/portfolio/solana")
    assert resp.status_code == 200
    body = resp.json()
    assert body["partial"] is False
    assert body["holdings"] == [{
        "address": "SomeMint111111111111111111111111111111111", "symbol": "FAKE",
        "amount": 42.5, "price_usd": 2.0, "value_usd": 85.0,
    }]


def test_portfolio_on_robinhood_is_marked_partial(client, monkeypatch):
    client.post("/api/onchain/wallets", json={"chain": "robinhood"})

    async def _fake_balances(chain, address, known_evm_tokens=None):
        return []

    monkeypatch.setattr(onchain_balances, "all_token_balances", _fake_balances)

    resp = client.get("/api/onchain/portfolio/robinhood")
    assert resp.status_code == 200
    assert resp.json()["partial"] is True


def test_onchain_token_meta_never_guesses_decimals(monkeypatch):
    async def _boom(chain, address):
        raise RuntimeError("RPC giu'")

    monkeypatch.setattr(onchain_token_metadata, "get_token_decimals", _boom)
    with pytest.raises(RuntimeError):
        import asyncio
        asyncio.run(main._onchain_token_meta("solana", "x"))


def test_chart_endpoint_finds_pool_and_returns_candles(client, monkeypatch):
    import pandas as pd

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"pairs": [{
                "chainId": "solana", "pairAddress": "PoolAddr111", "dexId": "raydium",
                "baseToken": {"symbol": "FAKE", "address": "MintAddr111"},
                "quoteToken": {"symbol": "USDC"},
                "liquidity": {"usd": 50000},
            }]}

    class _FakeAsyncClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _FakeResponse()

    async def _fake_fetch_ohlcv(self, symbol, interval, outputsize, since_ms=None):
        idx = pd.to_datetime([1_700_000_000, 1_700_000_900], unit="s", utc=True)
        return pd.DataFrame(
            {"open": [1.0, 1.1], "high": [1.2, 1.3], "low": [0.9, 1.0], "close": [1.1, 1.2], "volume": [10, 20]},
            index=idx,
        )

    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(main.dexscreener_provider.__class__, "fetch_ohlcv", _fake_fetch_ohlcv)

    resp = client.get("/api/onchain/chart/solana/MintAddr111")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "FAKE@solana:PoolAddr111"
    assert len(body["candles"]) == 2
    assert body["candles"][0]["close"] == 1.1
