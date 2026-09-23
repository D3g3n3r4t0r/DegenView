"""Preventivi fuori da Uniswap v3: MYCE si scambia solo su Pons e v4, e il
prezzo deve arrivare lo stesso, da KyberSwap o, se non risponde, da LI.FI."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import auth, main
from app.trading.onchain import aggregator

WETH = aggregator.ROBINHOOD_WETH
MYCE = "0xf1d03fe50cc3c1d35f11ae8783bb3f2a8158ca6e"


def test_falls_back_to_lifi_and_measures_impact(monkeypatch):
    calls = []

    async def kyber(token_in, token_out, amount_in):
        calls.append("kyber")
        raise aggregator.AggregatorError("KyberSwap: service temporarily overloaded")

    async def lifi(token_in, token_out, amount_in):
        calls.append("lifi")
        # il riferimento (1/1000) rende 1000 per unita', l'importo pieno 980
        return amount_in * 980 if amount_in > 1000 else amount_in * 1000

    monkeypatch.setattr(aggregator, "_kyber", kyber)
    monkeypatch.setattr(aggregator, "_lifi", lifi)
    out = asyncio.run(aggregator.quote(WETH, MYCE, 10**6))
    assert out["source"] == "LI.FI"
    assert out["amount_out"] == 980 * 10**6
    assert round(out["price_impact_pct"], 6) == 2.0
    assert calls == ["kyber", "lifi", "kyber", "lifi"]


def test_native_eth_is_sent_as_the_aggregator_placeholder(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"code": 0, "data": {"routeSummary": {"amountOut": "5"}}}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            seen.update(params)
            return FakeResponse()

    monkeypatch.setattr(aggregator.httpx, "AsyncClient", FakeClient)
    assert asyncio.run(aggregator._kyber(WETH, MYCE, 100)) == 5
    assert seen["tokenIn"] == aggregator._KYBER_NATIVE
    assert seen["tokenOut"] == MYCE


def test_quote_endpoint_uses_the_aggregator_when_v3_has_no_pool(monkeypatch):
    async def no_pool(token_in, token_out, preferred_fee=None):
        return None

    async def agg_quote(token_in, token_out, amount_in):
        return {"amount_out": 1234, "price_impact_pct": 0.4, "source": "KyberSwap"}

    monkeypatch.setattr(main.onchain_quotes, "find_pool_and_fee", no_pool)
    monkeypatch.setattr(main.onchain_aggregator, "quote", agg_quote)
    monkeypatch.setattr(main, "_require_onchain_enabled", lambda: None)
    main.app.dependency_overrides[auth.get_current_user] = lambda: object()
    try:
        resp = TestClient(main.app).post("/api/onchain/quote/robinhood", json={
            "token_in": WETH, "token_out": MYCE, "amount_in": 10**15,
        })
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "aggregator" and body["out_amount"] == 1234 and body["pool"] is None


def test_quote_endpoint_says_no_market_without_raw_ids(monkeypatch):
    async def no_pool(token_in, token_out, preferred_fee=None):
        return None

    async def agg_fails(token_in, token_out, amount_in):
        raise aggregator.AggregatorError("KyberSwap: 404; LI.FI: 404")

    monkeypatch.setattr(main.onchain_quotes, "find_pool_and_fee", no_pool)
    monkeypatch.setattr(main.onchain_aggregator, "quote", agg_fails)
    monkeypatch.setattr(main, "_require_onchain_enabled", lambda: None)
    main.app.dependency_overrides[auth.get_current_user] = lambda: object()
    try:
        resp = TestClient(main.app).post("/api/onchain/quote/robinhood", json={
            "token_in": WETH, "token_out": MYCE, "amount_in": 10**15,
        })
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert "0x" not in resp.json()["detail"]


def test_pair_price_for_a_token_on_the_quote_side():
    pair = {"baseToken": {"address": "0xSHROOM", "symbol": "SHROOM"},
            "quoteToken": {"address": "0xMYCE", "symbol": "MYCE"},
            "priceUsd": "0.02", "priceNative": "4"}
    assert main._pair_price_usd(pair, "0xmyce") == 0.005
    assert main._pair_price_usd(pair, "0xshroom") == 0.02
    assert main._pair_sides(pair, "0xMYCE")[0]["symbol"] == "MYCE"
