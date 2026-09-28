"""Narrative selection: meme catalog, per-account choice, discovery order."""
from __future__ import annotations

import pytest

from app import profiles
from app.trading.onchain import narratives


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "_STORE_FILE", tmp_path / "p.json")
    profiles.reset_for_tests()
    narratives.catalog.cache_clear()
    yield
    profiles.reset_for_tests()
    narratives.catalog.cache_clear()


def test_meme_catalog_has_twelve():
    memes = [n for n in narratives.catalog() if n["kind"] == "meme"]
    assert len(memes) == 12
    assert all(n["key"].startswith("meme_") for n in memes)


def test_match_kind_separates_meme_and_gem():
    assert "meme_dogs" in narratives.match("Doge Inu", "DINU", kind="meme")
    assert "meme_dogs" not in narratives.match("Doge Inu", "DINU", kind="gem")


def test_set_narratives_drops_unknown_and_dedupes():
    out = profiles.set_narratives("u1", ["meme_dogs", "nope", "meme_dogs", "meme_cats"])
    assert out == ["meme_dogs", "meme_cats"]
    assert profiles.narratives("u1") == ["meme_dogs", "meme_cats"]


def test_coingecko_categories_first_key_leads():
    key = next(n["key"] for n in narratives.catalog()
               if n["kind"] == "gem" and n.get("coingecko"))
    cats = narratives.coingecko_categories(first=[key])
    expected = next(n["coingecko"][0] for n in narratives.catalog() if n["key"] == key)
    assert cats[0] == expected


def test_wanted_narratives_ranks_by_count():
    profiles.set_narratives("u1", ["meme_dogs", "meme_cats"])
    profiles.set_narratives("u2", ["meme_dogs"])
    assert profiles.wanted_narratives()[0] == "meme_dogs"
