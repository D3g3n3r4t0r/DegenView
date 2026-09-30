"""Sniper store pruning: stale candidates leave RAM for a gzipped archive,
nothing is lost; the market screener drops tokens unseen for a week."""
from __future__ import annotations

import gzip
import json
import time

from app.sniper import cache, market


def _cand(addr: str, updated: float) -> cache.Candidate:
    return cache.Candidate(
        chain_id="solana", token_address=addr, pair_address="p" + addr, symbol=addr.upper(), name=addr,
        dex_id="raydium", pair_url="", price_usd=1.0, market_cap=1e6, liquidity_usd=5e4,
        volume_h24=1e5, volume_h1=1e4, age_hours=10.0, buy_sell_ratio=1.2, website=None,
        first_seen=updated, last_updated=updated,
    )


def test_prune_archives_stale_and_overflow(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_ARCHIVE_FILE", tmp_path / "arch.jsonl.gz")
    monkeypatch.setattr(cache, "_store", {})
    monkeypatch.setattr(cache, "CANDIDATES_MAX", 2)
    now = time.time()
    for addr, age in (("a", 0), ("b", 60), ("c", 120), ("old", cache.CANDIDATES_MAX_AGE_S + 1)):
        cache._store[addr] = _cand(addr, now - age)

    assert cache._prune_candidates(now) == 2
    assert set(cache._store) == {"a", "b"}
    with gzip.open(tmp_path / "arch.jsonl.gz", "rt", encoding="utf-8") as fh:
        archived = {json.loads(line)["token_address"] for line in fh}
    assert archived == {"c", "old"}

    cache._store["d"] = _cand("d", now - cache.CANDIDATES_MAX_AGE_S - 5)
    assert cache._prune_candidates(now) == 1
    with gzip.open(tmp_path / "arch.jsonl.gz", "rt", encoding="utf-8") as fh:
        assert sum(1 for _ in fh) == 3


def test_prune_keeps_everything_if_archive_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_ARCHIVE_FILE", tmp_path / "missing" / "arch.jsonl.gz")
    monkeypatch.setattr(cache, "_store", {"old": _cand("old", 0.0)})
    assert cache._prune_candidates() == 0
    assert "old" in cache._store


def test_market_prune_drops_week_old(monkeypatch):
    now = time.time()
    fresh = market.MarketToken("solana", "a", "p", "A", "a", "dex", "", 1.0, None, 1.0, 1.0, 1.0, 1.0, now)
    stale = market.MarketToken("solana", "b", "p", "B", "b", "dex", "", 1.0, None, 1.0, 1.0, 1.0, 1.0,
                               now - market.STORE_MAX_AGE_S - 1)
    monkeypatch.setattr(market, "_store", {"solana:a": fresh, "solana:b": stale})
    assert market._prune(now) == 1
    assert set(market._store) == {"solana:a"}
