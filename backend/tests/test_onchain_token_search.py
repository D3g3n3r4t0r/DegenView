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


def test_thin_tokens_still_listed_after_the_liquid_ones():
    """Lorenzo cercava MYCEL ($4.7k di pool su Pons) e non usciva: nessun
    ticker sparisce per poca liquidita', va solo in fondo."""
    out = token_search.pick_one_per_symbol([
        _c("PEPERAT", "thin", 2_000),
        _c("PEPEX", "liquid", 90_000),
        _c("PEPE", "exact", 1_200),
    ], "pepe")
    assert [r["address"] for r in out] == ["exact", "liquid", "thin"]


def test_dexscreener_adds_tokens_the_main_source_misses():
    payload = {"pairs": [
        {"chainId": "robinhood", "pairAddress": "0xpool",
         "baseToken": {"address": "0xMYCE", "symbol": "MYCE", "name": "Mycelium"},
         "quoteToken": {"address": "0xSHROOM", "symbol": "SHROOM"},
         "liquidity": {"usd": 7_224}, "volume": {"h24": 362}, "txns": {"h24": {"buys": 30, "sells": 12}},
         "info": {"imageUrl": "https://img.example/myce.png"}},
        {"chainId": "solana", "pairAddress": "x",
         "baseToken": {"address": "sol-myce", "symbol": "MYCE"}, "quoteToken": {"address": "sol", "symbol": "SOL"}},
    ]}
    extra = token_search._dexscreener_candidates(payload, "robinhood")
    merged = token_search.merge_candidates([_c("MYCEL", "0xMYCEL", 4_697)], extra)
    out = token_search.pick_one_per_symbol(merged, "MYCE")
    assert [r["address"] for r in out] == ["0xMYCE", "0xMYCEL"]
    assert out[0]["icon"] == "https://img.example/myce.png"


def test_merge_keeps_the_verification_of_the_main_source():
    merged = token_search.merge_candidates(
        [_c("WIF", "EKpQ", 6_000_000, verified=True)],
        [_c("WIF", "ekpq", 7_000_000), _c("WIF", "copy", 9_000_000)],
    )
    out = token_search.pick_one_per_symbol(merged, "wif")
    assert [(r["address"], r["liquidity_usd"]) for r in out] == [("EKpQ", 7_000_000)]


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


def test_partial_results_are_not_cached(monkeypatch):
    """Con una fonte caduta si risponde con quel che c'e', ma alla ricerca
    dopo si riprova: MYCEL spariva per 60s quando GeckoTerminal dava 429."""
    import asyncio

    import httpx

    calls = {"gecko": 0}

    async def fake_fetch(url, params):
        if url == token_search.GECKOTERMINAL_SEARCH_URL:
            calls["gecko"] += 1
            if calls["gecko"] == 1:
                raise httpx.HTTPStatusError("429", request=httpx.Request("GET", url), response=httpx.Response(429))
            return {"data": [], "included": []}
        return {"pairs": [{"chainId": "robinhood", "pairAddress": "0xp",
                           "baseToken": {"address": "0xMYCE", "symbol": "MYCE"},
                           "quoteToken": {"address": "0xS", "symbol": "SHROOM"},
                           "liquidity": {"usd": 7_000}, "volume": {"h24": 300},
                           "txns": {"h24": {"buys": 25, "sells": 5}}}]}

    monkeypatch.setattr(token_search, "_fetch_json", fake_fetch)
    monkeypatch.setattr(token_search, "_cache", {})
    asyncio.run(token_search.search("robinhood", "MYCE"))
    assert token_search._cache == {}
    asyncio.run(token_search.search("robinhood", "MYCE"))
    assert calls["gecko"] == 2
    assert ("robinhood", "myce") in token_search._cache
