"""Preventivi pre-trade. jupiter_quote() e' verificato anche con una vera
chiamata di rete (Jupiter e' pubblico, nessuna chiave) — non solo un
trasporto finto: e' il tipo di errore che un mock non avrebbe mai trovato
(un campo rinominato dall'API reale, per esempio)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.trading.onchain import quotes

_RealAsyncClient = httpx.AsyncClient
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _client_factory(handler):
    def factory(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        kwargs.pop("proxies", None)
        return _RealAsyncClient(*args, transport=transport, **kwargs)
    return factory


def _run(coro):
    return asyncio.run(coro)


def test_jupiter_quote_real_network_call():
    result = _run(quotes.jupiter_quote(SOL_MINT, USDC_MINT, 10_000_000, slippage_bps=50))
    assert result["in_amount"] == 10_000_000
    assert result["out_amount"] > 0
    assert 0 <= result["price_impact_pct"] < 5  # SOL/USDC e' profondissimo, l'impatto deve essere minuscolo


def test_jupiter_quote_parses_mocked_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "inAmount": "10000000", "outAmount": "1133425", "priceImpactPct": "0.0004738",
        })

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    result = _run(quotes.jupiter_quote(SOL_MINT, USDC_MINT, 10_000_000))
    assert result["in_amount"] == 10_000_000
    assert result["out_amount"] == 1133425
    assert result["price_impact_pct"] == pytest.approx(0.04738)


def test_jupiter_quote_raises_on_error_payload(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "no route found"})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    with pytest.raises(RuntimeError, match="no route found"):
        _run(quotes.jupiter_quote(SOL_MINT, USDC_MINT, 10_000_000))


def _reserves_response(reserve0: int, reserve1: int) -> str:
    return "0x" + format(reserve0, "064x") + format(reserve1, "064x") + format(0, "016x")


def test_uniswap_v2_price_impact_buy_token1_with_token0(monkeypatch):
    pool = "0xPool"
    token0 = "0x000000000000000000000000000000000000AAAA"
    reserve0, reserve1 = 1_000_000, 500_000  # spot price = 0.5 token1 per token0

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "0x0902f1ac" in body:  # getReserves()
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": _reserves_response(reserve0, reserve1)})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 24 + token0[2:]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    result = _run(quotes.uniswap_v2_price_impact(pool, token0, 10_000))
    # amount_out = 10000*500000 / (1000000+10000) = 4950.49...
    assert result["amount_out"] == 4950
    assert result["price_impact_pct"] > 0
    assert result["price_impact_pct"] < 5  # 1% del pool, impatto piccolo


def test_uniswap_v2_price_impact_scales_with_trade_size(monkeypatch):
    pool = "0xPool"
    token0 = "0x000000000000000000000000000000000000AAAA"
    reserve0, reserve1 = 1_000_000, 500_000

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "0x0902f1ac" in body:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": _reserves_response(reserve0, reserve1)})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 24 + token0[2:]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    small = _run(quotes.uniswap_v2_price_impact(pool, token0, 1_000))
    large = _run(quotes.uniswap_v2_price_impact(pool, token0, 500_000))
    assert large["price_impact_pct"] > small["price_impact_pct"]


def test_uniswap_v2_price_impact_raises_on_empty_pool(monkeypatch):
    pool = "0xPool"
    token0 = "0x000000000000000000000000000000000000AAAA"

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "0x0902f1ac" in body:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": _reserves_response(0, 0)})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 24 + token0[2:]})

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))
    with pytest.raises(RuntimeError, match="senza liquidita"):
        _run(quotes.uniswap_v2_price_impact(pool, token0, 1_000))
