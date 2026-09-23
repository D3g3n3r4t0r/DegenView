"""/admin/status — piano SRE on-chain punto 3: ordini 24h, circuit breaker,
saldo wallet, stato fallback RPC. Stesso schema fixture di
test_onchain_trading_api.py."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, config, main
from app.trading.onchain import ledger as onchain_ledger
from app.trading.onchain import rpc_client as onchain_rpc_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(onchain_ledger, "_DB_FILE", tmp_path / "ledger.db")
    onchain_ledger._init_db()
    onchain_rpc_client._breaker_state.clear()
    auth._users.clear()
    user = auth.create_user("trader@example.com", "correct-horse-battery-9")
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.get_user(user.id)
    with TestClient(main.app) as c:
        c.owner_id = user.id
        c.user_email = user.email
        yield c
    main.app.dependency_overrides.clear()


def test_admin_status_rejects_non_admin(client, monkeypatch):
    monkeypatch.setattr(config.settings, "admin_emails", "someone-else@example.com")
    resp = client.get("/admin/status")
    assert resp.status_code == 403


def test_admin_status_reports_orders_breaker_and_rpc(client, monkeypatch):
    monkeypatch.setattr(config.settings, "admin_emails", client.user_email)

    onchain_ledger.reserve("k-confirmed", client.owner_id, "solana", "TOKEN", "lorenzo", "buy", "simulated", 10.0)
    onchain_ledger.mark_confirmed("k-confirmed", executed_qty=5.0, executed_price_usd=2.0)

    onchain_ledger.reserve("k-failed", client.owner_id, "solana", "TOKEN", "lorenzo", "buy", "live", 10.0)
    onchain_ledger.mark_failed("k-failed", "firma fallita: boom")

    resp = client.get("/admin/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["orders_last_24h"]["executed"] == 1
    assert body["orders_last_24h"]["failed_by_cause"] == {"firma fallita: boom": 1}
    assert set(body["circuit_breakers"].keys()) == {"solana", "robinhood"}
    assert body["circuit_breakers"]["solana"]["tripped"] is False
    assert "solana" in body["rpc_fallback"]
    assert body["rpc_fallback"]["solana"]["active_endpoint"]
    assert body["wallet_balances"] == {}
