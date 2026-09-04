"""Diario degli ordini automatici.

Il guasto che questo diario rende impossibile e' gia' successo: il trading
automatico non ha mai piazzato un ordine e non c'era modo di accorgersene —
nessun errore, nessuna notifica. Un percorso che, funzionando, non diceva nulla,
e che rotto diceva la stessa cosa.
"""

from __future__ import annotations

import pytest

from app import trading_log as tl


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "_STORE_FILE", tmp_path / "journal.json")
    tl._entries.clear()


def _rec(owner="u1", outcome="eseguito", symbol="KASUSDT", **kw):
    return tl.record(owner, symbol=symbol, exchange="mexc",
                     strategy_name="Lorenzo (trend-follower)",
                     signal_type="entry_long", outcome=outcome, **kw)


def test_the_three_outcomes_are_all_recorded():
    _rec(outcome="eseguito")
    _rec(outcome="fallito", detail="saldo insufficiente")
    _rec(outcome="saltato", detail="chiavi API mancanti o non leggibili")
    assert {e["outcome"] for e in tl.list_for("u1")} == {"eseguito", "fallito", "saltato"}


def test_a_skip_says_why():
    """È la riga che sarebbe servita: c'era un segnale, l'ordine non è partito."""
    _rec(outcome="saltato", detail="esecuzione automatica disattivata per questo exchange")
    assert "disattivata" in tl.list_for("u1")[0]["detail"]


def test_newest_first_and_stable_within_the_same_second():
    a = _rec(symbol="AAA")
    b = _rec(symbol="BBB")
    assert [e["id"] for e in tl.list_for("u1")] == [b["id"], a["id"]]


def test_each_owner_sees_only_their_own():
    _rec(owner="u1")
    _rec(owner="u2")
    assert len(tl.list_for("u1")) == 1
    assert len(tl.list_for("u2")) == 1


def test_clearing_is_owner_scoped():
    _rec(owner="u1")
    _rec(owner="u2")
    assert tl.clear("u1") == 1
    assert tl.list_for("u1") == []
    assert len(tl.list_for("u2")) == 1


def test_entries_survive_a_reload():
    _rec()
    tl._entries.clear()
    tl._load()
    assert len(tl.list_for("u1")) == 1


def test_last_activity_is_the_newest_or_none():
    assert tl.last_activity("u1") is None
    _rec(symbol="AAA")
    last = _rec(symbol="ZZZ")
    assert tl.last_activity("u1")["id"] == last["id"]


def test_the_cap_drops_the_oldest_of_that_owner_only(monkeypatch):
    monkeypatch.setattr(tl, "_MAX_PER_OWNER", 3)
    keeper = _rec(owner="u2")
    for i in range(6):
        _rec(owner="u1", detail=f"n{i}")
    mine = tl.list_for("u1")
    assert len(mine) == 3
    assert [e["detail"] for e in mine] == ["n5", "n4", "n3"]
    assert tl.list_for("u2")[0]["id"] == keeper["id"]


def test_long_details_are_truncated_not_refused():
    e = _rec(outcome="fallito", detail="x" * 5000)
    assert len(e["detail"]) == 400
