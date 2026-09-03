"""Archivio delle strategie attivate.

Il punto della richiesta era poter tornare, mesi dopo, su "che cosa avevo
attivato e con quali numeri". Le due proprietà che lo rendono utile invece che
decorativo sono qui: i numeri li misura il server, e riaccendere un alert non
riempie l'archivio di copie della stessa cosa.
"""

from __future__ import annotations

import time

import pytest

from app import archive


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_STORE_FILE", tmp_path / "archive.json")
    archive._entries.clear()


def _create(owner="u1", strategy="Lorenzo (trend-follower)", params=None, **kw):
    return archive.create(
        owner_id=owner, symbol="kasusdt", asset_type="crypto", exchange="mexc",
        interval="1d", strategy_name=strategy, params=params or {"swing_length": 8},
        backtest_params={}, **kw,
    )


# --- il ciclo di vita di una voce ----------------------------------------


def test_a_new_entry_starts_without_numbers():
    e = _create()
    assert e["state"] == "in corso"
    assert e["metrics"] is None
    assert e["symbol"] == "KASUSDT"


def test_metrics_are_attached_afterwards():
    e = _create()
    archive.attach_result(e["id"], {"total_return_pct": 12.5, "num_trades": 9})
    got = archive.get(e["id"], "u1")
    assert got["state"] == "pronto"
    assert got["metrics"]["total_return_pct"] == 12.5


def test_a_failure_is_written_on_the_entry_not_deleted():
    """Una voce sparita non si distingue da una mai creata."""
    e = _create()
    archive.attach_error(e["id"], "Nessun dato per KASUSDT")
    got = archive.get(e["id"], "u1")
    assert got is not None
    assert got["state"] == "fallito"
    assert "Nessun dato" in got["error"]


def test_entries_survive_a_reload():
    _create()
    archive._entries.clear()
    archive._load()
    assert len(archive.list_for("u1")) == 1


# --- separazione fra proprietari ------------------------------------------


def test_each_owner_sees_only_their_own():
    _create(owner="u1")
    _create(owner="u2")
    assert len(archive.list_for("u1")) == 1
    assert archive.get(archive.list_for("u2")[0]["id"], "u1") is None


def test_deleting_someone_elses_entry_fails():
    e = _create(owner="u2")
    assert archive.remove(e["id"], "u1") is False
    assert archive.remove(e["id"], "u2") is True


def test_notes_are_owner_scoped():
    e = _create(owner="u2")
    assert archive.set_note(e["id"], "u1", "mia") is None
    assert archive.set_note(e["id"], "u2", "mia")["note"] == "mia"


# --- niente copie della stessa attivazione --------------------------------


def test_toggling_an_alert_off_and_on_does_not_duplicate():
    params = {"swing_length": 8}
    _create(params=params, source="alert", watchlist_entry_id="w1")
    assert archive.already_archived("u1", "w1", "Lorenzo (trend-follower)", params)


def test_reactivating_with_different_params_is_a_new_entry():
    """Sono due strategie diverse, non due accensioni della stessa."""
    _create(params={"swing_length": 8}, source="alert", watchlist_entry_id="w1")
    assert not archive.already_archived(
        "u1", "w1", "Lorenzo (trend-follower)", {"swing_length": 12})


def test_the_guard_is_per_strategy():
    _create(params={"a": 1}, source="alert", watchlist_entry_id="w1")
    assert not archive.already_archived(
        "u1", "w1", "Gabriele (RSI+BB reversal)", {"a": 1})


def test_the_guard_expires():
    e = _create(params={"a": 1}, source="alert", watchlist_entry_id="w1")
    e["created_at"] = int(time.time()) - 90 * 86400
    assert not archive.already_archived("u1", "w1", "Lorenzo (trend-follower)", {"a": 1})


# --- ordine e limite -------------------------------------------------------


def test_newest_first():
    a = _create()
    a["created_at"] = 100
    b = _create()
    b["created_at"] = 200
    assert [x["id"] for x in archive.list_for("u1")] == [b["id"], a["id"]]


def test_the_cap_drops_the_oldest_of_that_owner_only(monkeypatch):
    monkeypatch.setattr(archive, "_MAX_PER_OWNER", 3)
    keeper = _create(owner="u2")
    for i in range(6):
        _create(owner="u1", params={"i": i})
    assert len(archive.list_for("u1")) == 3
    assert archive.get(keeper["id"], "u2") is not None
    assert [x["params"]["i"] for x in archive.list_for("u1")] == [5, 4, 3]
