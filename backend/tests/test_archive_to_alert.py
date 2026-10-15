"""
Dall'archivio all'alert: accendere il monitoraggio con i parametri trovati,
non con quelli di default.

La segnalazione: dopo un'ottimizzazione, nella scheda del ticker comparivano i
parametri predefiniti della strategia. L'archivio conservava i parametri
trovati, ma restava una fotografia — per farli lavorare bisognava riscriverli a
mano, e chi non lo faceva teneva acceso un alert identico d'aspetto a uno
ottimizzato e diverso in tutto il resto.

Due regole che questi test tengono ferme:
  * i parametri li legge il server dalla voce d'archivio, non dal client;
  * accendere non scrive nell'archivio (dal 13/10): le voci "from alert" non
    nascono piu'.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import archive as archive_store
from app import auth, main
from app import watchlist as watchlist_store
from app.models import User

STRATEGY = "Gabriele (RSI+BB reversal)"
FOUND = {"rsi_length": 9, "bb_length": 34, "bb_mult": 2.6, "rsi_oversold": 19, "rsi_overbought": 81}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_store, "_STORE_FILE", tmp_path / "archive.json")
    monkeypatch.setattr(watchlist_store, "_STORE_FILE", tmp_path / "watchlist.json")
    archive_store._entries.clear()
    watchlist_store._entries.clear()
    user = User(id="u1", email="l@example.com", password_hash="x")
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def _archived(**kw) -> dict:
    fields = dict(owner_id="u1", symbol="KASUSDT", asset_type="crypto", exchange="mexc",
                  interval="4h", strategy_name=STRATEGY, params=dict(FOUND),
                  backtest_params={}, source="ottimizzazione")
    fields.update(kw)
    return archive_store.create(**fields)


def test_the_alert_starts_with_the_archived_parameters(client):
    entry = _archived()
    resp = client.post(f"/api/archive/{entry['id']}/apply-to-alert")
    assert resp.status_code == 200
    body = resp.json()
    assert body["params"] == FOUND

    watch = watchlist_store.list_entries("u1")
    assert len(watch) == 1
    assert STRATEGY in watch[0].strategies
    assert watch[0].strategy_params[STRATEGY] == FOUND, "l'alert gira sui parametri trovati"


def test_the_alert_uses_the_archived_timeframe(client):
    entry = _archived(interval="4h")
    client.post(f"/api/archive/{entry['id']}/apply-to-alert")
    watch = watchlist_store.list_entries("u1")[0]
    assert watch.strategy_intervals.get(STRATEGY) == "4h"


def test_switching_on_from_the_archive_adds_no_archive_entry(client):
    """Accendere non fotografa piu' nell'archivio (Lorenzo, 13/10: "nessuna
    strategia venga salvata automaticamente in archivio"): niente voci
    "from alert", e l'alert lavora con i parametri della voce applicata."""
    entry = _archived()
    client.post(f"/api/archive/{entry['id']}/apply-to-alert")
    assert [e for e in archive_store.list_for("u1") if e["source"] == "alert"] == []
    watch = watchlist_store.list_entries("u1")[0]
    assert watch.strategy_params.get(STRATEGY) == FOUND


def test_applying_twice_does_not_duplicate_the_watchlist_entry(client):
    entry = _archived()
    client.post(f"/api/archive/{entry['id']}/apply-to-alert")
    client.post(f"/api/archive/{entry['id']}/apply-to-alert")
    assert len(watchlist_store.list_entries("u1")) == 1


def test_an_entry_of_someone_else_is_not_found(client):
    entry = _archived(owner_id="altro")
    assert client.post(f"/api/archive/{entry['id']}/apply-to-alert").status_code == 404


def test_an_unknown_strategy_is_refused(client):
    entry = _archived(strategy_name="Strategia che non esiste")
    resp = client.post(f"/api/archive/{entry['id']}/apply-to-alert")
    assert resp.status_code == 400
    assert "Unknown" in resp.json()["detail"]


def test_testing_an_entry_on_another_pair(client, monkeypatch):
    # Lorenzo, 15/10: "testare la strategia salvata su un altro asset [...]
    # con gli stessi valori"
    import numpy as np
    import pandas as pd
    n = 3000
    close = 100 + np.cumsum(np.random.default_rng(2).normal(0, 1, n)) + 10 * np.sin(np.arange(n) / 9)
    df = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close,
                       "volume": np.full(n, 1000.0)},
                      index=pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC"))

    class _P:
        async def fetch_ohlcv(self, symbol, interval, outputsize, since_ms=None):
            return df
    monkeypatch.setattr(main, "get_provider", lambda *a, **k: _P())
    entry = _archived()
    resp = client.post(f"/api/archive/{entry['id']}/test-on-pair", json={"symbol": "ethusdt"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == "ETHUSDT" and body["params"] == FOUND
    assert "last_year" not in body and body["history"]["trades"] >= 0
    assert client.post("/api/archive/nope/test-on-pair", json={"symbol": "X"}).status_code == 404
