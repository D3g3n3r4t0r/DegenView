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


def test_live_price_for_quote_token_is_always_one(client):
    resp = client.get("/api/onchain/price/solana/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    assert resp.status_code == 200
    assert resp.json()["price_usd"] == 1.0


def test_live_price_reuses_the_swap_quote_for_a_1_unit_amount(client, monkeypatch):
    from app.trading.onchain import quotes as onchain_quotes
    from app.trading.onchain import token_metadata as onchain_token_metadata

    async def _fake_decimals(chain, address):
        return 9

    async def _fake_jupiter_quote(input_mint, output_mint, amount_lamports, slippage_bps):
        assert amount_lamports == 10**9  # 1 unita' intera del token, non un lamport
        return {"in_amount": amount_lamports, "out_amount": 3_500_000, "price_impact_pct": 0.1, "raw": {}}

    monkeypatch.setattr(onchain_token_metadata, "get_token_decimals", _fake_decimals)
    monkeypatch.setattr(onchain_quotes, "jupiter_quote", _fake_jupiter_quote)

    resp = client.get("/api/onchain/price/solana/SomeMint111111111111111111111111111111111")
    assert resp.status_code == 200
    assert resp.json()["price_usd"] == 3.5


def test_live_price_for_native_token_never_calls_get_token_decimals(client, monkeypatch):
    """Visto in produzione: decimals() sull'indirizzo nativo di Robinhood
    Chain puo' tornare None (non e' garantito un ERC20 vero), e
    "10 ** None" mandava in errore l'endpoint. I decimali del nativo sono
    hardcoded (come nel frontend), mai chiesti al contratto."""
    from app.trading.onchain import quotes as onchain_quotes
    from app.trading.onchain import token_metadata as onchain_token_metadata

    async def _boom(chain, address):
        raise AssertionError("non deve mai chiedere i decimali del nativo al contratto")

    async def _fake_uniswap_quote(token_in, token_out, fee, amount_in):
        assert amount_in == 10**18  # 1 unita' intera di ETH (18 decimali), non un wei
        return {"amount_out": 3_500_000, "price_impact_pct": 0.1}

    async def _fake_get_pool(token_in, token_out, fee):
        return {"address": "pool"}

    monkeypatch.setattr(onchain_token_metadata, "get_token_decimals", _boom)
    monkeypatch.setattr(onchain_quotes, "uniswap_v3_quote", _fake_uniswap_quote)
    monkeypatch.setattr(onchain_quotes, "get_pool", _fake_get_pool)

    resp = client.get("/api/onchain/price/robinhood/0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73")
    assert resp.status_code == 200
    assert resp.json()["price_usd"] == 3.5
