"""Decimali del token BASE, letti dal vero contratto/mint — mai indovinati.
USDC su Solana e' verificato anche con una vera chiamata di rete (6
decimali, noto e documentato pubblicamente); i casi di errore/chain non
supportata sono mockati."""
from __future__ import annotations

import asyncio

import pytest

from app.trading.onchain import rpc_client, token_metadata

USDC_SOLANA_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_caches():
    token_metadata._decimals_cache.clear()
    rpc_client._breaker_state.clear()
    yield
    token_metadata._decimals_cache.clear()
    rpc_client._breaker_state.clear()


def test_solana_decimals_real_network_call():
    decimals = _run(token_metadata.get_token_decimals("solana", USDC_SOLANA_MINT))
    assert decimals == 6


def test_solana_decimals_mocked(monkeypatch):
    async def fake_call_rpc(chain, method, params, timeout=15.0):
        assert chain == "solana"
        assert method == "getTokenSupply"
        assert params == ["MintXYZ"]
        return {"value": {"amount": "1000000", "decimals": 9, "uiAmount": 0.001}}

    monkeypatch.setattr(rpc_client, "call_rpc", fake_call_rpc)
    assert _run(token_metadata.get_token_decimals("solana", "MintXYZ")) == 9


def test_robinhood_decimals_mocked(monkeypatch):
    async def fake_call_rpc(chain, method, params, timeout=15.0):
        assert chain == "robinhood"
        assert params[0]["data"] == "0x313ce567"
        return "0x0000000000000000000000000000000000000000000000000000000000000012"  # 18

    monkeypatch.setattr(rpc_client, "call_rpc", fake_call_rpc)
    assert _run(token_metadata.get_token_decimals("robinhood", "0xTokenAddr")) == 18


def test_unsupported_chain_returns_none():
    assert _run(token_metadata.get_token_decimals("ethereum", "0xabc")) is None


def test_transport_error_returns_none_not_a_guess(monkeypatch):
    async def fake_call_rpc(chain, method, params, timeout=15.0):
        raise RuntimeError("Tutti gli endpoint RPC hanno fallito")

    monkeypatch.setattr(rpc_client, "call_rpc", fake_call_rpc)
    assert _run(token_metadata.get_token_decimals("solana", "TokenChebrokerRPC")) is None


def test_result_is_cached_after_first_lookup(monkeypatch):
    calls = []

    async def fake_call_rpc(chain, method, params, timeout=15.0):
        calls.append(params)
        return {"value": {"decimals": 6}}

    monkeypatch.setattr(rpc_client, "call_rpc", fake_call_rpc)
    first = _run(token_metadata.get_token_decimals("solana", "MintCached"))
    second = _run(token_metadata.get_token_decimals("solana", "MintCached"))
    assert first == second == 6
    assert len(calls) == 1  # la seconda chiamata non ha toccato la rete
