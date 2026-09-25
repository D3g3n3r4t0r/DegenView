"""Plans: the reader is for everyone, Claude is a paid boost."""
import asyncio

import pytest

from app.trading.onchain import plans, research as rs


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(plans, "_STORE", tmp_path / "plans.json")
    monkeypatch.setattr(plans, "_state", {"users": {}, "usage": {}})
    monkeypatch.setattr(rs, "_STORE", tmp_path / "research.json")
    monkeypatch.setattr(rs, "_cache", {})
    monkeypatch.setattr(rs, "_prints", {})
    monkeypatch.setattr(plans.legit.settings, "anthropic_api_key", "")
    seen = {"boost": []}

    async def item(chain, token, client):
        return {"chain": chain, "token_address": token, "name": "Solrouter", "symbol": "ROUTER"}

    async def analyze(it, client, launched):
        seen["boost"].append(it.get("boost"))
        return {"key": "site", "score": 70, "facts": {}}, []

    monkeypatch.setattr(plans, "token_item", item)
    monkeypatch.setattr(rs, "analyze", analyze)
    yield seen


def _read(email="a@x.it", deep=False, admin=False):
    return asyncio.run(plans.read_project(email, "solana", "T" * 32, deep=deep, admin=admin))


def test_free_plan_has_a_daily_limit():
    for _ in range(plans.PLANS["free"]["reads"]):
        assert _read()["ok"]
    r = _read()
    assert not r["ok"] and "5 a day" in r["error"] and r["used"]["reads"] == 5


def test_deep_reading_needs_a_key_and_a_paid_plan(monkeypatch, _clean):
    assert "not available" in _read(deep=True)["error"]
    monkeypatch.setattr(plans.legit.settings, "anthropic_api_key", "sk")
    assert "paid plan" in _read(deep=True)["error"]
    plans.set_plan("a@x.it", "boost")
    assert _read(deep=True)["ok"] and _clean["boost"] == [True]
    assert plans.usage("a@x.it") == {"reads": 0, "deep": 1}


def test_admin_is_pro_and_unknown_plan_is_refused():
    assert plans.status("boss@x.it", admin=True)["plan"] == "pro"
    with pytest.raises(ValueError):
        plans.set_plan("a@x.it", "gold")


def test_boost_reading_runs_while_background_readings_are_off(monkeypatch):
    monkeypatch.setattr(rs, "AI_ENABLED", False)
    monkeypatch.setattr(rs.legit.settings, "anthropic_api_key", "")
    assert asyncio.run(rs.ai_dossier({}, "x", [], boost=True)) is None   # no key, no call
