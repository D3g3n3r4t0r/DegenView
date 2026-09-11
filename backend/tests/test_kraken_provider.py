"""Kraken (dati spot pubblici) — mai una vera chiamata di rete: ogni test
sostituisce httpx.AsyncClient con un trasporto finto (httpx.MockTransport).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.providers import kraken
from app.providers.base import ProviderError
from app.providers.kraken import KrakenProvider, format_symbol

_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*, timeout):
        transport = httpx.MockTransport(handler)
        return _RealAsyncClient(timeout=timeout, transport=transport)
    return factory


def _run(coro):
    return asyncio.run(coro)


def test_format_symbol_maps_btc_to_xbt():
    assert format_symbol("BTCUSDT") == "XBTUSDT"
    assert format_symbol("btc/eur") == "XBTEUR"
    assert format_symbol("ETH") == "ETHUSD"


def test_fetch_ohlcv_parses_result_and_caps_at_720(monkeypatch):
    rows = [[1700000000 + i * 86400, "100", "110", "90", "105", "100", "1.5", 10] for i in range(800)]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/0/public/OHLC"
        return httpx.Response(200, json={"error": [], "result": {"XXBTZUSD": rows, "last": 1}})

    monkeypatch.setattr(kraken.httpx, "AsyncClient", _client_factory(handler))
    provider = KrakenProvider()
    df = _run(provider.fetch_ohlcv("BTCUSD", "1d", 5000))
    assert len(df) == 720
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_fetch_ohlcv_raises_on_kraken_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})

    monkeypatch.setattr(kraken.httpx, "AsyncClient", _client_factory(handler))
    provider = KrakenProvider()
    with pytest.raises(ProviderError):
        _run(provider.fetch_ohlcv("NOTAREALPAIR", "1d", 10))


def test_search_symbols_maps_xbt_back_to_btc_for_display(monkeypatch):
    payload = {
        "result": {
            "XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD", "base": "XXBT", "quote": "ZUSD", "status": "online"},
            "XETHZUSD": {"altname": "ETHUSD", "wsname": "ETH/USD", "base": "XETH", "quote": "ZUSD", "status": "online"},
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload))

    monkeypatch.setattr(kraken.httpx, "AsyncClient", _client_factory(handler))
    provider = KrakenProvider()
    results = _run(provider.search_symbols("BTC"))
    assert results
    assert results[0]["symbol"] == "XBTUSD"
    assert "USD" in results[0]["exchange"]


def test_search_symbols_empty_query_returns_nothing():
    provider = KrakenProvider()
    assert _run(provider.search_symbols("  ")) == []
