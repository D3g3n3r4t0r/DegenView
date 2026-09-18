"""Token effimeri per approvare da un secondo dispositivo la rivelazione
di una chiave on-chain — in memoria, uso unico, scadenza breve."""

from __future__ import annotations

import time

from app.trading.onchain import reveal_requests as rr


def test_pending_then_approved_then_consumed():
    token = rr.create("u1", "solana")
    assert rr.status(token, "u1") == "pending"
    assert rr.approve(token, "u1") is True
    assert rr.status(token, "u1") == "approved"
    assert rr.consume(token, "u1", "solana") is True
    # uso unico: una seconda consume sullo stesso token non trova piu' nulla
    assert rr.consume(token, "u1", "solana") is False


def test_wrong_user_cannot_see_or_approve_someone_elses_token():
    token = rr.create("owner", "solana")
    assert rr.status(token, "intruder") == "expired"  # mai "pending": non deve trapelare che esiste
    assert rr.approve(token, "intruder") is False
    assert rr.status(token, "owner") == "pending"  # il vero owner non e' stato toccato


def test_consume_requires_matching_chain():
    token = rr.create("u1", "solana")
    rr.approve(token, "u1")
    assert rr.consume(token, "u1", "robinhood") is False


def test_consume_without_approval_fails():
    token = rr.create("u1", "solana")
    assert rr.consume(token, "u1", "solana") is False


def test_expired_token_is_not_pending(monkeypatch):
    token = rr.create("u1", "solana")
    future = time.time() + 121
    monkeypatch.setattr(time, "time", lambda: future)
    assert rr.status(token, "u1") == "expired"
    assert rr.approve(token, "u1") is False
