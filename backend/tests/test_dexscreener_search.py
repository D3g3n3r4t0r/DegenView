"""La ricerca DexScreener deve portare l'indirizzo del token BASE, non solo
quello del pool — prima scartato (usato solo per symbol/name), ora e' il
pezzo che sblocca Fase 4 (vedi test_onchain_watchlist_autotrade.py)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.providers.dexscreener import DexScreenerProvider

_PAYLOAD = {"pairs": [{
    "chainId": "solana", "pairAddress": "Pxxx1111111111111111111111",
    "baseToken": {"symbol": "PEPE", "name": "Pepe", "address": "TokenMintAddr222"},
    "quoteToken": {"symbol": "USDC"},
    "dexId": "raydium", "liquidity": {"usd": 1000},
}]}


class _FakeResp:
    def json(self):
        return _PAYLOAD


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **kw):
        return _FakeResp()


def test_search_symbols_carries_base_token_address():
    with patch("httpx.AsyncClient", return_value=_FakeClient()):
        provider = DexScreenerProvider()
        out = asyncio.run(provider.search_symbols("pepe"))
    assert out[0]["base_token_address"] == "TokenMintAddr222"
    assert out[0]["symbol"] == "PEPE@solana:Pxxx1111111111111111111111"


def test_search_symbols_none_when_address_missing():
    payload = {"pairs": [{
        "chainId": "solana", "pairAddress": "Pxxx1111111111111111111111",
        "baseToken": {"symbol": "PEPE", "name": "Pepe"},  # niente "address"
        "quoteToken": {"symbol": "USDC"}, "dexId": "raydium", "liquidity": {"usd": 1000},
    }]}

    class _FakeResp2:
        def json(self):
            return payload

    class _FakeClient2(_FakeClient):
        async def get(self, *a, **kw):
            return _FakeResp2()

    with patch("httpx.AsyncClient", return_value=_FakeClient2()):
        provider = DexScreenerProvider()
        # Query diversa dall'altro test: la cache dei risultati e' condivisa
        # a livello di modulo per query, e riusare "pepe" avrebbe letto la
        # risposta gia' in cache dall'altro caso invece di questo fake.
        out = asyncio.run(provider.search_symbols("pepe-no-address"))
    assert out[0]["base_token_address"] is None
