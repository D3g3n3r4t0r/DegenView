"""The simulated wallet as the profile and header show it (main._sim_snapshot)."""
from types import SimpleNamespace

import pytest

from app import main
from app.trading.onchain import alert_track as tr
from app.trading.onchain import autotrader as at
from app.trading.onchain import wealth


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(tr, "_STORE_FILE", tmp_path / "t.json")
    monkeypatch.setattr(wealth, "_STORE_FILE", tmp_path / "w.json")
    at.reset_for_tests()
    wealth.reset_for_tests()
    yield
    at.reset_for_tests()
    wealth.reset_for_tests()


USER = SimpleNamespace(id="u1")


def test_not_started_says_so():
    snap = main._sim_snapshot(USER)
    assert snap["total"] is None and snap["sim"] is None and not snap["complete"]


def test_started_shows_the_virtual_balance_and_records_its_own_line():
    at.configure("u1", mode="sim", usdg_now=250.0)
    snap = main._sim_snapshot(USER)
    assert snap["total"] == pytest.approx(250.0) and snap["cash"] == pytest.approx(250.0)
    assert snap["sim"]["autotrader"] == "sim" and snap["positions"] == []
    main._record_sim(USER, snap)
    assert wealth.series("u1:sim")[-1][1] == pytest.approx(250.0)
    assert wealth.series("u1") == []          # the real line is untouched


def test_paper_trades_show_in_the_simulated_wallet():
    """Lorenzo, 28/09: /api/profile and /api/wallets/total answered 500
    (KeyError 'qty') as soon as the simulated wallet followed an alert."""
    a = tr.record({"chain": "solana", "pair_address": "P", "token_address": "T", "symbol": "SOLY"}, "meme", 1_790_000_000)
    a["alert_bt"] = {"Trend EMA": {"state": "in", "ret": 0.1, "events": [{"side": "buy"}]}}
    at.configure("u1", mode="sim", pct=50, usdg_now=100.0)
    at.paper_tick(at._user("u1"), "Trend EMA", 1_790_000_060)
    at.paper_tick(at._user("u1"), "Trend EMA", 1_790_000_090)      # marked on the next pass
    snap = main._sim_snapshot(USER)
    assert [(p["symbol"], p["chain"]) for p in snap["positions"]] == [("SOLY", "solana")]
    assert snap["total"] == pytest.approx(50 + 55) and sum(snap["by_chain"].values()) == pytest.approx(snap["total"])
