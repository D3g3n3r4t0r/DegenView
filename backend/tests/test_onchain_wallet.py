"""Wallet on-chain, Fase 1: generazione chiave (mai in rete) e saldo
(via httpx finto, come test_diagnostics.py). Nessuna firma qui — quella
non esiste ancora, ed e' apposta."""

from __future__ import annotations

import asyncio

import base58
import httpx
import pytest

from app.trading.onchain import balances as onchain_balances
from app.trading.onchain import keys as onchain_keys

_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        kwargs.pop("proxies", None)
        return _RealAsyncClient(*args, transport=transport, **kwargs)
    return factory


def _run(coro):
    return asyncio.run(coro)


def test_generate_solana_roundtrips_through_address_from_private_key():
    key = onchain_keys.generate("solana")
    assert key.address
    assert onchain_keys.address_from_private_key("solana", key.private_key_hex) == key.address


def test_generate_robinhood_roundtrips_through_address_from_private_key():
    key = onchain_keys.generate("robinhood")
    assert key.address.startswith("0x")
    assert onchain_keys.address_from_private_key("robinhood", key.private_key_hex) == key.address


def test_generate_two_solana_keys_differ():
    a = onchain_keys.generate("solana")
    b = onchain_keys.generate("solana")
    assert a.address != b.address
    assert a.private_key_hex != b.private_key_hex


def test_generate_unsupported_chain_raises():
    with pytest.raises(ValueError):
        onchain_keys.generate("bsc")  # type: ignore[arg-type]


def test_solana_import_format_is_base58_of_the_same_key():
    key = onchain_keys.generate("solana")
    imported = onchain_keys.to_import_format("solana", key.private_key_hex)
    # Un wallet vero (Phantom/Solflare) decodifica esattamente questo
    # formato e deve ritrovare lo stesso indirizzo — qui lo verifichiamo
    # senza un wallet vero, rifacendo lo stesso giro con la libreria.
    assert onchain_keys.address_from_private_key(
        "solana", base58.b58decode(imported).hex()
    ) == key.address


def test_robinhood_import_format_is_0x_prefixed_hex():
    key = onchain_keys.generate("robinhood")
    imported = onchain_keys.to_import_format("robinhood", key.private_key_hex)
    assert imported == f"0x{key.private_key_hex}"
    assert onchain_keys.address_from_private_key("robinhood", imported) == key.address


def test_solana_balance_parses_lamports(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": 1_500_000_000}})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    balance = _run(onchain_balances.native_balance("solana", "Fake11111111111111111111111111111111111111"))
    assert balance == pytest.approx(1.5)


def test_robinhood_balance_parses_hex_wei(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xde0b6b3a7640000"})  # 1e18

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    balance = _run(onchain_balances.native_balance("robinhood", "0x0000000000000000000000000000000000dEaD"))
    assert balance == pytest.approx(1.0)


def test_rpc_error_response_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad address"}})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    with pytest.raises(RuntimeError):
        _run(onchain_balances.native_balance("solana", "not-a-real-address"))
