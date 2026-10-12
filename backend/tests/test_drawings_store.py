"""Drawings follow the account across devices (drawing tools plan, phase 4)."""
import pytest

from app import drawings as D


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_STORE_FILE", tmp_path / "drawings.json")
    monkeypatch.setattr(D, "_store", {})


def test_put_then_get():
    D.put("u1", "draw:crypto:BTCUSDT", [{"id": "a", "type": "hline"}], 10)
    assert D.get("u1", "draw:crypto:BTCUSDT")["drawings"][0]["id"] == "a"
    assert D.get("u2", "draw:crypto:BTCUSDT") is None


def test_older_copy_does_not_overwrite_newer():
    D.put("u1", "draw:crypto:BTCUSDT", [{"id": "new"}], 20)
    kept = D.put("u1", "draw:crypto:BTCUSDT", [{"id": "old"}], 10)
    assert kept["drawings"][0]["id"] == "new"


def test_limits_and_keys():
    with pytest.raises(ValueError):
        D.put("u1", "../etc", [], 1)
    with pytest.raises(ValueError):
        D.put("u1", "draw:crypto:X", [{}] * (D.MAX_DRAWINGS_PER_KEY + 1), 1)
    assert D.valid_key("draw:dex:BONK@solana:So1111")
    assert D.valid_key("fractal:crypto:BTCUSDT")
