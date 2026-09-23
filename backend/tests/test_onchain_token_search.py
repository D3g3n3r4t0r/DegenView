"""Un risultato per ticker nella ricerca token del wallet: il contratto
verificato con piu' liquidita' vera, mai una copia col pool gonfiato."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import auth, main
from app.trading.onchain import token_search


def _c(symbol, address, liquidity, verified=False, volume=0.0):
    return {"symbol": symbol, "address": address, "name": "", "decimals": 6,
            "verified": verified, "icon": None, "liquidity_usd": liquidity, "volume_usd": volume}


def test_one_result_per_ticker_prefers_verified_over_bigger_copy():
    out = token_search.pick_one_per_symbol([
        _c("BONK", "fake-big", 50_000_000),
        _c("$Bonk", "real", 1_400_000, verified=True),
        _c("bonk", "fake-small", 20_000),
    ], "bonk")
    assert [r["address"] for r in out] == ["real"]


def test_exact_ticker_first_and_name_only_matches_dropped():
    out = token_search.pick_one_per_symbol([
        _c("BONKSOL", "a", 11_000_000, verified=True),
        _c("BERN", "name-match", 250_000, verified=True),
        _c("BONK", "b", 5_000_000, verified=True),
    ], "BONK")
    assert [r["symbol"] for r in out] == ["BONK", "BONKSOL"]


def test_thin_unverified_tokens_hidden_unless_actually_traded():
    out = token_search.pick_one_per_symbol([
        _c("PEPERAT", "thin", 2_000),
        _c("PEPE", "traded", 1_200, volume=1_800_000),
    ], "pepe")
    assert [r["address"] for r in out] == ["traded"]


def test_gecko_pools_with_reserve_but_no_trades_count_as_zero_liquidity():
    def pool(base_id, reserve, volume, txns):
        return {
            "attributes": {"reserve_in_usd": str(reserve), "volume_usd": {"h24": str(volume)},
                           "transactions": {"h24": {"buys": txns, "sells": 0}}},
            "relationships": {"base_token": {"data": {"id": base_id}},
                              "quote_token": {"data": {"id": "weth"}}},
        }
    payload = {
        "data": [pool("fake", 270_000_000, 0.03, 2), pool("real", 1_237, 1_806_169, 3_170)],
        "included": [
            {"id": "fake", "type": "token", "attributes": {"address": "0xFAKE", "symbol": "Bonk"}},
            {"id": "real", "type": "token", "attributes": {"address": "0xREAL", "symbol": "BONK"}},
            {"id": "weth", "type": "token", "attributes": {
                "address": "0xWETH", "symbol": "WETH", "coingecko_coin_id": "weth"}},
        ],
    }
    candidates = {c["address"]: c for c in token_search._gecko_candidates(payload)}
    assert candidates["0xFAKE"]["liquidity_usd"] == 0
    assert candidates["0xWETH"]["verified"] is True
    out = token_search.pick_one_per_symbol(candidates.values(), "BONK")
    assert [r["address"] for r in out] == ["0xREAL"]


def test_jupiter_payload_parsed_with_verification_flag():
    out = token_search._jupiter_candidates([
        {"id": "EKpQ", "symbol": "$WIF", "name": "dogwifhat", "decimals": 6, "isVerified": True,
         "liquidity": 6_800_000, "stats24h": {"buyVolume": 10, "sellVolume": 5},
         "icon": "https://img.example/wif.png"},
        {"symbol": "NOID"},
    ])
    assert out == [{"address": "EKpQ", "symbol": "WIF", "name": "dogwifhat", "decimals": 6,
                    "verified": True, "icon": "https://img.example/wif.png",
                    "liquidity_usd": 6_800_000.0, "volume_usd": 15.0}]


def test_search_endpoint_returns_one_token_per_ticker(monkeypatch):
    async def fake_fetch(url, params):
        return [
            {"id": "fake", "symbol": "BONK", "liquidity": 50_000_000},
            {"id": "real", "symbol": "Bonk", "isVerified": True, "liquidity": 1_400_000},
        ]
    monkeypatch.setattr(token_search, "_fetch_json", fake_fetch)
    monkeypatch.setattr(token_search, "_cache", {})
    monkeypatch.setattr(main, "_require_onchain_enabled", lambda: None)
    main.app.dependency_overrides[auth.get_current_user] = lambda: object()
    try:
        resp = TestClient(main.app).get("/api/onchain/tokens/search", params={"chain": "solana", "query": "bonk"})
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert [r["address"] for r in resp.json()] == ["real"]
