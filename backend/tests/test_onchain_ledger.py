"""Ledger on-chain: idempotenza vera (vincolo UNIQUE), posizione come unica
fonte di verita', spesa giornaliera, circuit breaker su perdite consecutive.
Ogni test usa un DB SQLite temporaneo — mai il file di produzione."""

from __future__ import annotations

from app.trading.onchain import ledger


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_FILE", tmp_path / "ledger.db")
    ledger._init_db()


def test_reserve_is_idempotent(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    assert ledger.reserve("k1", "u1", "solana", "TOKEN", "lorenzo", "buy", "real", 20.0) is True
    # stessa chiave: non deve scrivere una seconda riga, ne' permettere una seconda firma
    assert ledger.reserve("k1", "u1", "solana", "TOKEN", "lorenzo", "buy", "real", 20.0) is False


def test_full_lifecycle_updates_position_and_daily_spend(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    ledger.reserve("k2", "u1", "solana", "TOKEN", "lorenzo", "buy", "real", 20.0)
    ledger.mark_submitted("k2", "sig123")
    order = ledger.get_order("k2")
    assert order["status"] == "submitted"
    assert order["tx_signature"] == "sig123"

    ledger.mark_confirmed("k2", executed_qty=100.0, executed_price_usd=0.2, price_impact_pct=1.2)
    order = ledger.get_order("k2")
    assert order["status"] == "confirmed"

    pos = ledger.get_position("u1", "solana", "TOKEN")
    assert pos["quantity"] == 100.0
    assert pos["cost_usd"] == 20.0
    assert ledger.get_daily_spent("u1", "solana") == 20.0


def test_sell_reduces_position(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    ledger.reserve("buy1", "u1", "solana", "TOKEN", "lorenzo", "buy", "real", 20.0)
    ledger.mark_confirmed("buy1", executed_qty=100.0, executed_price_usd=0.2)
    ledger.reserve("sell1", "u1", "solana", "TOKEN", "lorenzo", "sell", "real", 10.0)
    ledger.mark_confirmed("sell1", executed_qty=50.0, executed_price_usd=0.2)

    pos = ledger.get_position("u1", "solana", "TOKEN")
    assert pos["quantity"] == 50.0
    assert pos["cost_usd"] == 10.0


def test_mark_failed_does_not_touch_position(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    ledger.reserve("k3", "u1", "solana", "TOKEN", "lorenzo", "buy", "real", 20.0)
    ledger.mark_failed("k3", "slippage troppo alto")
    assert ledger.get_order("k3")["status"] == "failed"
    assert ledger.get_position("u1", "solana", "TOKEN") == {"quantity": 0.0, "cost_usd": 0.0}


def test_pending_unconfirmed_lists_only_submitted(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    ledger.reserve("a", "u1", "solana", "TOKEN", "s", "buy", "real", 20.0)
    ledger.mark_submitted("a", "sig-a")
    ledger.reserve("b", "u1", "solana", "TOKEN", "s", "buy", "real", 20.0)
    ledger.mark_submitted("b", "sig-b")
    ledger.mark_confirmed("b", 1.0, 20.0)

    pending = ledger.pending_unconfirmed("u1")
    assert [p["idempotency_key"] for p in pending] == ["a"]


def test_circuit_breaker_trips_after_five_losses(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    for _ in range(4):
        tripped = ledger.record_trade_outcome("u1", "solana", -5.0)
        assert tripped is False
    tripped = ledger.record_trade_outcome("u1", "solana", -5.0)
    assert tripped is True
    status = ledger.breaker_status("u1", "solana")
    assert status["tripped"] is True
    assert status["consecutive_losses"] == 5


def test_win_resets_loss_streak(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    ledger.record_trade_outcome("u1", "solana", -5.0)
    ledger.record_trade_outcome("u1", "solana", -5.0)
    ledger.record_trade_outcome("u1", "solana", 3.0)
    status = ledger.breaker_status("u1", "solana")
    assert status["consecutive_losses"] == 0
    assert status["tripped"] is False


def test_reset_breaker_is_manual_only(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    for _ in range(5):
        ledger.record_trade_outcome("u1", "solana", -5.0)
    assert ledger.breaker_status("u1", "solana")["tripped"] is True
    ledger.reset_breaker("u1", "solana")
    assert ledger.breaker_status("u1", "solana") == {"tripped": False, "consecutive_losses": 0, "reason": None}
