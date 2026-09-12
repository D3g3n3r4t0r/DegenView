"""Tetto per singola strategia (size_cap_usdt): impostato per strategia, non
per exchange, perche' la credenziale exchange e' condivisa da tutte le
strategie che ci operano sopra — un utente con dieci strategie automatiche
sullo stesso exchange non ha altro modo per limitare quanto rischia CIASCUNA.

Va SOLO agli ingressi: una chiusura chiude sempre per intero, mai vista qui.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app import watchlist as watchlist_store
from app.models import User

STRATEGY = "Gabriele (RSI+BB reversal)"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist_store, "_STORE_FILE", tmp_path / "watchlist.json")
    watchlist_store._entries.clear()
    user = User(id="u1", email="l@example.com", password_hash="x")
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def _entry():
    return watchlist_store.add_entry("u1", "KASUSDT", "crypto", exchange="mexc")


def test_setting_a_cap_via_the_endpoint_persists_it(client):
    entry = _entry()
    resp = client.patch(
        f"/api/watchlist/{entry.id}/size_cap",
        json={"strategy_name": STRATEGY, "cap_usdt": 500.0},
    )
    assert resp.status_code == 200
    assert resp.json()["size_cap_usdt"][STRATEGY] == pytest.approx(500.0)


def test_zero_removes_the_cap(client):
    entry = _entry()
    watchlist_store.set_size_cap(entry.id, STRATEGY, 500.0)
    resp = client.patch(
        f"/api/watchlist/{entry.id}/size_cap",
        json={"strategy_name": STRATEGY, "cap_usdt": 0.0},
    )
    assert resp.status_code == 200
    assert STRATEGY not in resp.json()["size_cap_usdt"]


def test_negative_cap_is_rejected(client):
    entry = _entry()
    resp = client.patch(
        f"/api/watchlist/{entry.id}/size_cap",
        json={"strategy_name": STRATEGY, "cap_usdt": -10.0},
    )
    assert resp.status_code == 400


def test_unknown_strategy_is_rejected(client):
    entry = _entry()
    resp = client.patch(
        f"/api/watchlist/{entry.id}/size_cap",
        json={"strategy_name": "non esiste", "cap_usdt": 100.0},
    )
    assert resp.status_code == 400


def test_cap_is_per_strategy_not_per_entry(client):
    """Due strategie sullo stesso ticker/exchange: il tetto dell'una non
    tocca l'altra — altrimenti non risolverebbe il problema per cui esiste
    (dieci strategie sullo stesso exchange, tetti diversi ciascuna)."""
    entry = _entry()
    watchlist_store.set_size_cap(entry.id, STRATEGY, 500.0)
    other = "Lorenzo (trend-follower)"
    updated = watchlist_store.set_size_cap(entry.id, other, 1000.0)
    assert updated.size_cap_usdt[STRATEGY] == pytest.approx(500.0)
    assert updated.size_cap_usdt[other] == pytest.approx(1000.0)
