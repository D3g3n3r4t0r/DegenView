"""The five faults found checking the classic Trading tab on 23/10.

Run against a local server with fake keys sent to the real exchanges:
1. a Bitstamp refusal (and any httpx error) was a 500 that never reached the log;
2. Binance Futures raised its own FuturesExecutionError, which the site does
   not catch: quote and order were a 500 and the positions list failed for
   every exchange;
3. the bots logged "eseguito" and sent "Ordine ESEGUITO" for orders the
   executor skipped (kill switch, breaker, a no-op signal);
4. a real copy trade failed on the wallet switch with no hint of it;
5. the manual order's free balance (frontend, not tested here).
"""
from __future__ import annotations

import asyncio

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import auth
from app import main
from app import trading_log as tl
from app.models import StrategySignal, User
from app.trading import binance_futures_exec as bfe
from app.trading import bitstamp_exec
from app.trading.futures import binance as binance_adapter
from app.trading.futures.base import FuturesExecutionError, Position


class _Provider:
    async def fetch_ohlcv(self, *a, **k):
        return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})


@pytest.fixture
def user(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "_STORE_FILE", tmp_path / "journal.json")
    tl._entries.clear()
    u = User(id="u1", email="l@example.com", password_hash="x")
    cred = type("C", (), {"api_key_enc": "a", "api_secret_enc": "b", "enabled": True})()
    u.trading_credentials["mexc"] = cred
    u.futures_credentials["binance"] = cred
    u.futures_credentials["okx"] = cred
    monkeypatch.setattr(auth, "get_decrypted_credential", lambda u, e: ("key", "secret", ""))
    monkeypatch.setattr(auth, "get_decrypted_futures_credential", lambda u, e: ("key", "secret", "pass"))
    monkeypatch.setattr(main, "get_provider", lambda *a, **k: _Provider())
    return u


@pytest.fixture
def client(user):
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def _order(client):
    return client.post("/api/trading/order", json={"exchange": "mexc", "symbol": "KASUSDT", "side": "BUY",
                                                   "size_mode": "fixed_usdt", "size_value": 10})


def test_an_http_error_is_a_readable_502_in_the_log(client, monkeypatch):
    async def refused(*a, **k):
        raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(main, "place_order_for_signal", refused)
    r = _order(client)
    assert r.status_code == 502 and "timed out" in r.json()["detail"]
    assert tl.list_for("u1")[0]["outcome"] == "fallito"


def test_a_skipped_order_is_not_executed(client, monkeypatch):
    async def halted(*a, **k):
        return {"skipped": True, "reason": "trading halted"}
    monkeypatch.setattr(main, "place_order_for_signal", halted)
    r = _order(client)
    assert r.status_code == 409 and "trading halted" in r.json()["detail"]
    e = tl.list_for("u1")[0]
    assert e["outcome"] == "saltato" and e["detail"] == "trading halted"


def test_bitstamp_http_errors_are_runtime_errors():
    resp = httpx.Response(403, text="Authentication Failed", request=httpx.Request("POST", "https://x"))
    with pytest.raises(RuntimeError, match="Bitstamp HTTP 403"):
        bitstamp_exec._check(resp)
    page = httpx.Response(403, text="<!DOCTYPE html><html>...</html>", request=httpx.Request("GET", "https://x"))
    with pytest.raises(RuntimeError, match=r"^Bitstamp HTTP 403: Forbidden$"):
        bitstamp_exec._check(page)
    bitstamp_exec._check(httpx.Response(200, text="{}", request=httpx.Request("GET", "https://x")))


def test_binance_futures_reads_raise_the_sites_error(monkeypatch):
    async def refused(*a, **k):
        raise bfe.FuturesExecutionError("binance futures positionRisk error: restricted location")
    for name in ("get_open_positions", "get_mark_price", "get_available_margin_usdt"):
        monkeypatch.setattr(bfe, name, refused)
    a, creds = binance_adapter.BinanceFutures(), binance_adapter.FuturesCreds("k", "s", "")
    for call in (a.open_positions(creds), a.mark_price("BTCUSDT", creds), a.available_margin(creds)):
        with pytest.raises(FuturesExecutionError):
            asyncio.run(call)


def test_one_failing_exchange_does_not_hide_the_others_positions(client, monkeypatch):
    from app.trading.futures import registry

    class Down:
        async def open_positions(self, creds):
            raise httpx.ReadTimeout("slow")

    class Up:
        async def open_positions(self, creds):
            return [Position(exchange="okx", symbol="BTCUSDT", side="long", quantity=1.0, entry_price=1.0,
                             mark_price=1.0, leverage=1, margin=1.0, notional=1.0, unrealized_pnl=0.0,
                             liquidation_price=0.0)]
    monkeypatch.setattr(registry, "get", lambda ex: Down() if ex == "binance" else Up())
    r = client.get("/api/trading/futures/positions")
    assert r.status_code == 200 and [p["exchange"] for p in r.json()] == ["okx"]


def test_the_bot_logs_a_skip_and_warns_only_when_it_matters(user, monkeypatch):
    sent = []
    monkeypatch.setattr(main, "_signal_chat", lambda owner: "chat")
    monkeypatch.setattr(main, "_telegram_allowed", lambda owner: True)
    monkeypatch.setattr(main, "_fire", lambda coro: (sent.append(coro), coro.close()))
    monkeypatch.setattr(main.telegram, "send_to", lambda chat, text: _Coro(text))
    entry = type("E", (), {"symbol": "BTCUSDT", "exchange": "mexc"})()
    sig = StrategySignal(time=1, type="exit_short", price=1.0, label="x")
    assert main._bot_skipped(user, entry, "Lorenzo", sig, {"skipped": True, "reason": "no-op signal type"})
    assert not sent                                   # nothing to say: on spot a short is cash
    assert main._bot_skipped(user, entry, "Lorenzo", sig, {"skipped": True, "reason": "trading halted"})
    assert len(sent) == 1 and "NON inviato" in sent[0].text
    assert [e["outcome"] for e in tl.list_for("u1")] == ["saltato", "saltato"]
    assert not main._bot_skipped(user, entry, "Lorenzo", sig, {"orderId": 1})


class _Coro:
    def __init__(self, text):
        self.text = text

    def close(self):
        pass


def test_a_real_copy_names_the_wallet_switch(monkeypatch, tmp_path):
    from app.config import settings
    from app.trading.onchain import copytrade as ct
    monkeypatch.setattr(ct, "STORE_FILE", tmp_path / "copytrade.json")
    monkeypatch.setattr(ct, "_store", None)
    monkeypatch.setattr(settings, "onchain_execution_enabled", True)
    monkeypatch.setattr(ct, "wallet_enabled", lambda owner: False)
    ct.set_real_ok("u1", True)
    assert ct._real_block(ct.account("u1"), "u1") == ct.WALLET_OFF
    monkeypatch.setattr(ct, "wallet_enabled", lambda owner: True)
    assert ct._real_block(ct.account("u1"), "u1") == ""
