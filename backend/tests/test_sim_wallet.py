"""The simulated wallet as the profile and header show it: the Top 50
wallet (main._sim_snapshot), the same for every account, and the one-time
reset of the old simulated books to $10,000."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app import main
from app.trading.onchain import autotrader as at
from app.trading.onchain import sim_backtest as sb
from app.trading.onchain import storage
from app.trading.onchain import wealth


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(sb, "_FILE", tmp_path / "l.json")
    monkeypatch.setattr(wealth, "_STORE_FILE", tmp_path / "w.json")
    wealth.reset_for_tests()
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "_top_entries", lambda n=50: [])
    main._top_wallet_cache.update(at=0.0, data=None)
    at.reset_for_tests()
    sb.reset_for_tests()
    yield
    at.reset_for_tests()
    sb.reset_for_tests()
    main._top_wallet_cache.update(at=0.0, data=None)


def _snap(uid):
    return asyncio.run(main._sim_snapshot(SimpleNamespace(id=uid)))


def test_every_account_sees_the_same_top50_wallet(monkeypatch):
    sb.remember("solana", "A", "AAA", {"rows": [{"label": "Trend EMA", "trades": 1, "return_pct": 100.0}],
                                       "best": {"label": "Trend EMA", "events": [
        {"t": 100, "side": "buy", "price": 1.0}, {"t": 200, "side": "sell", "price": 2.0, "ret": 1.0},
        {"t": 300, "side": "buy", "price": 2.0}]}})

    async def prices(keys):
        return {"solana:A": {"p": 3.0}}
    monkeypatch.setattr(main.onchain_live_prices, "prices", prices)
    a, b = _snap("u1"), _snap("u2")
    assert a["total"] == b["total"] and a["sim"]["start"] == 10_000
    assert [p["symbol"] for p in a["positions"]] == ["AAA"] and a["positions"][0]["ret"] == 0.5
    assert [c["symbol"] for c in a["closed"]] == ["AAA"] and a["closed"][0]["ret"] == 1.0
    assert a["total"] == pytest.approx(a["cash"] + sum(p["value_usd"] for p in a["positions"]))


def test_reset_puts_every_simulated_book_at_10k_and_keeps_a_backup(tmp_path):
    at.configure("u1", mode="sim", usdg_now=250.0)
    at._user("u1")["trades"] = [{"mode": "sim", "side": "buy"}, {"mode": "real", "side": "buy"}]
    at._save()
    main._sim_reset_once()
    u = at._user("u1")
    assert u["sim_usdg"] == 10_000 and u["sim_start"] == 10_000 and u["trend"] == [] and u["paper"] == []
    assert [t["mode"] for t in u["trades"]] == ["real"]
    backup = json.loads((tmp_path / "onchain_autotrader.before-sim-reset-2026-09-30.json").read_text())
    assert backup["u1"]["sim_start"] == 250.0
    u["sim_usdg"] = 5.0
    main._sim_reset_once()                    # once only
    assert at._user("u1")["sim_usdg"] == 5.0
