"""Regression tests for the 29/09 security audit (docs/audits/2026-09-29):
the stops no execution path may skip, and a ledger that counts each fill once."""
from __future__ import annotations

import asyncio

from app.trading.onchain import execute, ledger, reconciliation, risk, send


def _run(coro):
    return asyncio.run(coro)


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_FILE", tmp_path / "ledger.db")
    ledger._init_db()


def _quote():
    return {"in_amount": 1_000_000, "out_amount": 2_000_000, "price_impact_pct": 0.5, "raw": {}}


def _spy_signing(monkeypatch):
    calls = {"signed": 0, "sent": 0}

    async def _sign(private_key_hex, quote):
        calls["signed"] += 1
        return b"signed"

    async def _send(signed):
        calls["sent"] += 1
        return "sig"

    monkeypatch.setattr(execute.execution, "build_signed_solana_swap", _sign)
    monkeypatch.setattr(execute, "_send_solana_with_jito_fallback", lambda cid, pk, s, n: _send(s))
    monkeypatch.setattr(execute.settings, "onchain_execution_enabled", True)
    return calls


def test_switched_off_wallet_never_signs_even_without_guards(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    calls = _spy_signing(monkeypatch)
    monkeypatch.setattr(risk, "_wallet_enabled", lambda owner_id, chain: False)
    for guards in (True, False):
        result = _run(execute.execute_order(
            "u1", "solana", "TOKEN", "System", "buy", 10.0, 0.5, 2.0, "deadbeef", _quote(), guards=guards,
        ))
        assert result["accepted"] is False
        assert "switched off" in result["reason"]
    assert calls == {"signed": 0, "sent": 0}


def test_tripped_breaker_stops_the_autotrader_path(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    calls = _spy_signing(monkeypatch)
    for _ in range(5):
        ledger.record_trade_outcome("u1", "solana", -1.0)
    result = _run(execute.execute_order(
        "u1", "solana", "TOKEN", "System", "buy", 10.0, 0.5, 2.0, "deadbeef", _quote(), guards=False,
    ))
    assert result["accepted"] is False
    assert "circuit breaker" in result["reason"]
    assert calls["signed"] == 0


def test_wallet_switched_off_while_signing_is_not_broadcast(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    calls = _spy_signing(monkeypatch)
    state = {"on": True}
    monkeypatch.setattr(risk, "_wallet_enabled", lambda owner_id, chain: state["on"])

    async def _sign_then_switch_off(private_key_hex, quote):
        state["on"] = False
        return b"signed"

    monkeypatch.setattr(execute.execution, "build_signed_solana_swap", _sign_then_switch_off)
    result = _run(execute.execute_order(
        "u1", "solana", "TOKEN", "manuale", "buy", 10.0, 0.5, 2.0, "deadbeef", _quote(),
    ))
    assert result["accepted"] is False
    assert calls["sent"] == 0
    assert ledger.get_order(result["idempotency_key"])["status"] == "failed"


def test_switched_off_wallet_blocks_withdrawals(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(risk, "_wallet_enabled", lambda owner_id, chain: False)
    result = _run(send.send_token(
        "u1", "solana", "SOL", "dest", 1.0, 10**9, 10.0, "deadbeef", True, None,
    ))
    assert result["accepted"] is False
    assert "switched off" in result["reason"]


def test_pool_clamp_refuses_instead_of_signing_the_full_amount(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    calls = _spy_signing(monkeypatch)

    async def _snapshot(chain, pool):
        return {"liquidity_usd": 1000.0, "created_at": 0}

    monkeypatch.setattr(execute.pool_safety, "fetch_pool_snapshot", _snapshot)
    result = _run(execute.execute_order(
        "u1", "solana", "TOKEN", "manuale", "buy", 50.0, 0.5, 2.0, "deadbeef", _quote(), pool_address="P",
    ))
    assert result["accepted"] is False
    assert "above what this pool allows" in result["reason"]
    assert calls["signed"] == 0


def test_second_confirmation_does_not_double_the_position(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    ledger.reserve("k", "u1", "solana", "TOKEN", "lorenzo", "buy", "live", 10.0)
    ledger.mark_confirmed("k", executed_qty=10.0, executed_price_usd=1.0)
    ledger.mark_confirmed("k", executed_qty=10.0, executed_price_usd=1.0)
    assert ledger.get_position("u1", "solana", "TOKEN")["quantity"] == 10.0
    assert ledger.get_daily_spent("u1", "solana") == 10.0


def test_daily_cap_counts_orders_in_flight(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(risk.settings, "onchain_max_usd_per_day", 150.0)
    ledger.reserve("k", "u1", "solana", "TOKEN", "lorenzo", "buy", "live", 100.0)
    ok, reason = risk.check_daily_cap("u1", "solana", 100.0)
    assert ok is False
    assert "daily cap" in reason


def test_processed_solana_signature_stays_pending(monkeypatch):
    class _Resp:
        def json(self):
            return {"result": {"value": [{"err": None, "confirmationStatus": "processed"}]}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _Resp()

    monkeypatch.setattr(reconciliation.httpx, "AsyncClient", _Client)
    assert _run(reconciliation._solana_signature_status("sig")) == "pending"
