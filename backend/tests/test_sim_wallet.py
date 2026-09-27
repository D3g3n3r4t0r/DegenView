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
