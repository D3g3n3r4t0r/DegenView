"""Guardrail dell'esecuzione futures manuale (Fase 4 del piano "Operazioni
futures"): cap di leva, conferma esplicita obbligatoria, kill switch,
controllo del margine disponibile prima di ogni ordine. Niente rete vera —
tutto quello che tocca binance_futures_exec e' monkeypatchato.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import main
from app import trading_log as tl
from app.models import MAX_FUTURES_LEVERAGE, FuturesCredential, User
from app.trading import binance_futures_exec as bfe


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "_STORE_FILE", tmp_path / "journal.json")
    tl._entries.clear()
    user = User(id="u1", email="l@example.com", password_hash="x")
    user.futures_credentials["binance"] = FuturesCredential(
        api_key_enc="a", api_secret_enc="b", enabled=True,
        size_mode="fixed_usdt", size_value=100.0, leverage=5,
    )
    monkeypatch.setattr(auth, "get_decrypted_futures_credential", lambda u, e: ("key", "secret", ""))
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def _order(client, **kw):
    body = {"exchange": "binance", "symbol": "BTCUSDT", "side": "BUY",
            "size_mode": "fixed_usdt", "size_value": 100.0, "leverage": 5, "confirm": True}
    body.update(kw)
    return client.post("/api/trading/futures/order", json=body)


# --- credenziali: il cap di leva si applica anche solo a salvarle -----------


def test_saving_a_credential_above_the_leverage_cap_is_rejected(client):
    resp = client.patch("/api/auth/futures", json={
        "exchange": "binance", "api_key": "k", "api_secret": "s",
        "enabled": True, "size_mode": "fixed_usdt", "size_value": 50.0,
        "leverage": MAX_FUTURES_LEVERAGE + 1,
    })
    assert resp.status_code == 400
    assert "Leva" in resp.json()["detail"]


def test_saving_a_credential_at_the_cap_is_accepted(client):
    resp = client.patch("/api/auth/futures", json={
        "exchange": "binance", "api_key": "k", "api_secret": "s",
        "enabled": True, "size_mode": "fixed_usdt", "size_value": 50.0,
        "leverage": MAX_FUTURES_LEVERAGE,
    })
    assert resp.status_code == 200


def test_unsupported_exchange_is_rejected_before_touching_credentials(client):
    # mexc ha i futures ma non e' nel registro: nessuna licenza UE per i
    # derivati (vedi app/trading/futures/registry.py).
    resp = client.patch("/api/auth/futures", json={
        "exchange": "mexc", "api_key": "k", "api_secret": "s",
        "enabled": True, "leverage": 1,
    })
    assert resp.status_code == 400


# --- conferma esplicita obbligatoria -----------------------------------------


def test_an_order_without_confirm_never_reaches_the_exchange(client, monkeypatch):
    called = []
    monkeypatch.setattr(main, "place_futures_order_for_signal", lambda *a, **k: called.append(1))
    resp = _order(client, confirm=False)
    assert resp.status_code == 400
    assert "onferma" in resp.json()["detail"]
    assert called == []


# --- kill switch --------------------------------------------------------------


def test_the_kill_switch_blocks_the_order_even_with_confirm(client, monkeypatch):
    called = []
    monkeypatch.setattr(main, "place_futures_order_for_signal", lambda *a, **k: called.append(1))
    user = User(id="u1", email="l@example.com", password_hash="x")
    user.futures_credentials["binance"] = FuturesCredential(
        api_key_enc="a", api_secret_enc="b", enabled=False,  # spento
        size_mode="fixed_usdt", size_value=100.0, leverage=5,
    )
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    resp = _order(client)
    assert resp.status_code == 400
    assert "disattivat" in resp.json()["detail"]
    assert called == []


# --- leva fuori dal cap rifiutata anche al momento dell'ordine --------------


def test_leverage_above_the_cap_is_rejected_at_order_time_too(client, monkeypatch):
    called = []
    monkeypatch.setattr(main, "place_futures_order_for_signal", lambda *a, **k: called.append(1))
    resp = _order(client, leverage=MAX_FUTURES_LEVERAGE + 5)
    assert resp.status_code == 400
    assert called == []


# --- controllo pre-trade del margine -----------------------------------------


def test_insufficient_margin_blocks_the_order_before_it_is_sent(client, monkeypatch):
    called = []

    async def _balance(client_, secret):
        return 10.0  # molto meno dei 100 richiesti

    monkeypatch.setattr(bfe, "get_available_margin_usdt", _balance)
    monkeypatch.setattr(main, "place_futures_order_for_signal", lambda *a, **k: called.append(1))
    resp = _order(client)
    assert resp.status_code == 400
    assert "insufficiente" in resp.json()["detail"]
    assert called == []


def test_sufficient_margin_lets_the_order_through_and_journals_the_leverage(client, monkeypatch):
    async def _balance(client_, secret):
        return 1000.0

    async def _ok(*a, **k):
        return {"orderId": 42, "status": "FILLED"}

    monkeypatch.setattr(bfe, "get_available_margin_usdt", _balance)
    monkeypatch.setattr(main, "place_futures_order_for_signal", _ok)
    resp = _order(client)
    assert resp.status_code == 200
    entries = tl.list_for("u1")
    assert len(entries) == 1
    assert entries[0]["outcome"] == "eseguito"
    assert "leva 5x" in entries[0]["detail"]


def test_a_failed_order_is_journalled_with_its_leverage_too(client, monkeypatch):
    async def _balance(client_, secret):
        return 1000.0

    async def _boom(*a, **k):
        raise RuntimeError("binance futures order error: margin is insufficient")

    monkeypatch.setattr(bfe, "get_available_margin_usdt", _balance)
    monkeypatch.setattr(main, "place_futures_order_for_signal", _boom)
    resp = _order(client)
    assert resp.status_code == 502
    entries = tl.list_for("u1")
    assert entries[0]["outcome"] == "fallito"
    assert "leva 5x" in entries[0]["detail"]


# --- quote/anteprima ----------------------------------------------------------


def test_quote_reports_leverage_margin_and_liquidation_price(client, monkeypatch):
    async def _mark(client_, symbol):
        return 100.0

    async def _balance(client_, secret):
        return 500.0

    monkeypatch.setattr(bfe, "get_mark_price", _mark)
    monkeypatch.setattr(bfe, "get_available_margin_usdt", _balance)
    resp = client.post("/api/trading/futures/quote", json={
        "exchange": "binance", "symbol": "BTCUSDT", "side": "BUY",
        "size_mode": "fixed_usdt", "size_value": 100.0, "leverage": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["leverage"] == 5
    assert data["margin_used"] == 100.0
    assert data["notional"] == 500.0
    assert data["margin_sufficient"] is True
    # Long a leva 5x: prezzo di liquidazione sotto l'entry.
    assert data["liquidation_price"] < 100.0
