"""base_token_address: salvato alla creazione di una entry dex, e
recuperato su un'entry esistente creata prima di questo campo (l'upsert non
deve restare "saltata" per sempre solo perche' la ricerca c'e' stata dopo).
"""
from __future__ import annotations

import pytest

from app import watchlist as watchlist_store


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist_store, "_STORE_FILE", tmp_path / "watchlist.json")
    watchlist_store._entries.clear()
    yield
    watchlist_store._entries.clear()


def test_base_token_address_saved_on_create():
    entry = watchlist_store.add_entry(
        "u1", "PEPE@solana:Pxxx1111111111111111111111", "dex",
        base_token_address="TokenMintAddr222",
    )
    assert entry.base_token_address == "TokenMintAddr222"


def test_missing_address_stays_none():
    entry = watchlist_store.add_entry("u1", "PEPE@solana:Pxxx1111111111111111111111", "dex")
    assert entry.base_token_address is None


def test_upsert_fills_address_on_existing_entry_without_one():
    old = watchlist_store.add_entry("u1", "PEPE@solana:Pxxx1111111111111111111111", "dex")
    assert old.base_token_address is None

    same = watchlist_store.add_entry(
        "u1", "PEPE@solana:Pxxx1111111111111111111111", "dex",
        base_token_address="TokenMintAddr222",
    )
    assert same.id == old.id
    assert same.base_token_address == "TokenMintAddr222"


def test_dex_symbol_case_is_preserved_not_uppercased():
    """Bug reale: .upper() su un simbolo dex rendeva l'indirizzo del pool
    (base58 case-sensitive su Solana, o un contratto EVM misto) illeggibile
    a _parse_symbol() — PEPE@solana:9xQe... diventava PEPE@SOLANA:9XQE...
    e smetteva di fare match con la sua regex."""
    entry = watchlist_store.add_entry("u1", "pepe@solana:9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin", "dex")
    assert entry.symbol == "pepe@solana:9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"


def test_non_dex_symbol_is_still_uppercased():
    entry = watchlist_store.add_entry("u1", "btcusdt", "crypto")
    assert entry.symbol == "BTCUSDT"
