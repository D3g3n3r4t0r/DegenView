"""Diagnosi (test di connessione + saldo) — mai una vera chiamata di rete:
ogni test sostituisce httpx.AsyncClient con un trasporto finto."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import diagnostics
from app.trading import binance_exec, bitstamp_exec, coinbase_exec, kraken_exec, kucoin_exec

_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        kwargs.pop("proxies", None)
        return _RealAsyncClient(*args, transport=transport, **kwargs)
    return factory


def _run(coro):
    return asyncio.run(coro)


def test_spot_connection_rejects_missing_keys():
    with pytest.raises(diagnostics.DiagnosticsError):
        _run(diagnostics.test_spot_connection("mexc", "", ""))


def test_mexc_binance_balances_parsed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"balances": [
            {"asset": "USDT", "free": "123.45", "locked": "0"},
            {"asset": "BTC", "free": "0", "locked": "0"},
        ]})

    monkeypatch.setattr(binance_exec.httpx, "AsyncClient", _client_factory(handler))
    result = _run(diagnostics.test_spot_connection("mexc", "key", "secret"))
    assert result == [{"asset": "USDT", "free": 123.45}]


def test_mexc_binance_balances_surfaces_explained_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"code":-2015,"msg":"Invalid API-key"}')

    monkeypatch.setattr(binance_exec.httpx, "AsyncClient", _client_factory(handler))
    with pytest.raises(diagnostics.DiagnosticsError):
        _run(diagnostics.test_spot_connection("binance", "key", "secret"))


def test_kucoin_requires_passphrase():
    with pytest.raises(diagnostics.DiagnosticsError):
        _run(diagnostics.test_spot_connection("kucoin", "key", "secret", ""))


def test_kucoin_balances_parsed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "200000", "data": [
            {"currency": "USDT", "available": "50.5"},
            {"currency": "USDT", "available": "1.5"},
            {"currency": "BTC", "available": "0"},
        ]})

    monkeypatch.setattr(kucoin_exec.httpx, "AsyncClient", _client_factory(handler))
    result = _run(diagnostics.test_spot_connection("kucoin", "key", "secret", "pass"))
    assert result == [{"asset": "USDT", "free": 52.0}]


def test_kraken_balances_parsed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": [], "result": {"ZUSD": "10.0", "XXBT": "0.0"}})

    monkeypatch.setattr(kraken_exec.httpx, "AsyncClient", _client_factory(handler))
    result = _run(diagnostics.test_spot_connection("kraken", "key", "c2VjcmV0"))
    assert result == [{"asset": "ZUSD", "free": 10.0}]


def test_coinbase_balances_parsed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accounts": [
            {"currency": "USD", "available_balance": {"value": "42.0"}},
            {"currency": "BTC", "available_balance": {"value": "0"}},
        ]})

    monkeypatch.setattr(coinbase_exec.httpx, "AsyncClient", _client_factory(handler))
    result = _run(diagnostics.test_spot_connection("coinbase", "key", "secret"))
    assert result == [{"asset": "USD", "free": 42.0}]


def test_bitstamp_balance_parsed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usdt_available": "7.5", "btc_available": "0"})

    monkeypatch.setattr(bitstamp_exec.httpx, "AsyncClient", _client_factory(handler))
    result = _run(diagnostics.test_spot_connection("bitstamp", "key", "secret"))
    assert result == [{"asset": "USDT", "free": 7.5}]


def test_futures_connection_uses_adapter(monkeypatch):
    from app.trading.futures import registry as futures_registry

    class _FakeAdapter:
        slug = "fake"
        name = "Fake"
        needs_passphrase = False

        async def available_margin(self, creds):
            assert creds.api_key == "key"
            return 99.9

    monkeypatch.setattr(futures_registry, "SUPPORTED_FUTURES_EXCHANGES", ("fake",))
    monkeypatch.setattr(futures_registry, "get", lambda slug: _FakeAdapter())
    margin = _run(diagnostics.test_futures_connection("fake", "key", "secret"))
    assert margin == 99.9


def test_futures_connection_unsupported_exchange():
    with pytest.raises(diagnostics.DiagnosticsError):
        _run(diagnostics.test_futures_connection("not-a-real-exchange", "key", "secret"))
