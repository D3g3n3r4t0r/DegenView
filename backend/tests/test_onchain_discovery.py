"""Scan dei progetti seri: filtri su CoinGecko e DexScreener, senza rete."""
import asyncio

import pytest

from app.trading.onchain import depth, discovery as d


@pytest.fixture(autouse=True)
def _clean():
    d.reset_for_tests()
    yield
    d.reset_for_tests()


def test_market_candidates_keeps_cap_band_and_drops_meme_names():
    rows = [{"id": "big", "symbol": "big", "name": "Big", "market_cap": 9_000_000},
            {"id": "tiny", "symbol": "tiny", "name": "Tiny", "market_cap": 10_000},
            {"id": "dog", "symbol": "doge2", "name": "Doge Inu", "market_cap": 500_000},
            {"id": "grid", "symbol": "grid", "name": "Grid Protocol", "market_cap": 900_000}]
    assert [c["id"] for c in d.market_candidates("robinhood", rows)] == ["grid"]


def _coin(**kw):
    coin = {"symbol": "grid", "name": "Grid Protocol", "platforms": {"robinhood": "0xabc"},
            "categories": ["Robinhood Ecosystem", "Artificial Intelligence (AI)"],
            "links": {"homepage": ["https://grid.xyz"], "repos_url": {"github": ["https://github.com/grid/core"]},
                      "twitter_screen_name": "grid"},
            "description": {"en": "Inference network"}, "genesis_date": "2026-07-01"}
    coin.update(kw)
    return coin


def test_coin_detail_builds_item():
    item, why = d.from_coin_detail("robinhood", _coin(), {"symbol": "GRID", "market_cap": 900_000})
    assert why == "" and item["token_address"] == "0xabc" and item["github"] == "https://github.com/grid/core"
    assert item["website"] == "https://grid.xyz" and item["launched_at"]


def test_coin_detail_rejects_meme_stock_and_missing_contract():
    assert d.from_coin_detail("robinhood", _coin(categories=["Robinhood Chain Meme"]))[1].startswith("categoria")
    assert d.from_coin_detail("robinhood", _coin(categories=["Tokenized Stocks"]))[1].startswith("categoria")
    assert d.from_coin_detail("solana", _coin())[1] == "nessun contratto sulla chain"


def test_coin_detail_without_github_goes_to_site_analysis():
    item, _ = d.from_coin_detail("robinhood", _coin(links={"homepage": ["https://grid.xyz"]}))
    assert item and item["github"] is None


def test_profiles_keep_own_site_on_our_chains():
    profiles = [
        {"chainId": "solana", "tokenAddress": "M1", "description": "ZK proving network",
         "links": [{"label": "Website", "url": "https://prover.io"}, {"type": "github", "url": "https://github.com/p/r"}]},
        {"chainId": "base", "tokenAddress": "M2", "links": [{"label": "Website", "url": "https://x.io"}]},
        {"chainId": "solana", "tokenAddress": "M3", "description": "the funniest meme on solana",
         "links": [{"label": "Website", "url": "https://lol.io"}]},
        {"chainId": "solana", "tokenAddress": "M4", "links": [{"type": "twitter", "url": "https://x.com/a"}]},
    ]
    out = d.profile_candidates(profiles)
    assert [c["token_address"] for c in out] == ["M1"] and out[0]["github"] == "https://github.com/p/r"


def test_step_queues_pages_then_details(monkeypatch):
    calls = []

    async def fake_get(client, path, params=None):
        calls.append(path)
        if path == "/coins/markets":
            return [{"id": "grid", "symbol": "grid", "name": "Grid Protocol", "market_cap": 900_000}]
        return _coin()

    monkeypatch.setattr(d, "_cg_get", fake_get)
    monkeypatch.setattr(d, "_save", lambda: None)
    added = []
    add = lambda item, source: added.append((item["symbol"], source)) or True  # noqa: E731
    now = 1_790_000_000.0
    asyncio.run(d._cg_step(None, add, now))                 # prepara il giro
    asyncio.run(d._cg_step(None, add, now + 1))             # troppo presto
    assert calls == []
    for i in range(1, 12):
        asyncio.run(d._cg_step(None, add, now + i * d.CG_GAP_S))
    assert ("GRID", "coingecko") in added
    assert d.status()["found"] >= 1


def test_github_of_another_project_is_fatal(monkeypatch):
    async def repo(owner, name, client):
        return {"full_name": "alice/rust-utils", "homepage": "", "description": "misc helpers"}

    monkeypatch.setattr(depth.legit, "github_repo", repo)
    out = asyncio.run(depth.analyze_github(["https://github.com/alice/rust-utils"], None, None,
                                           token={"chain": "solana", "token_address": "M", "symbol": "GRID",
                                                  "name": "Grid Protocol"}, website="https://grid.xyz"))
    assert out["fatal"] == "GitHub non appartiene al progetto"
