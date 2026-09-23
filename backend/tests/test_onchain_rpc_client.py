"""Fallback multi-RPC + circuit breaker (rpc_client.py) — piano SRE punto 1.
httpx mockato: nessuna chiamata di rete vera."""
import asyncio

import httpx
import pytest

from app.trading.onchain import rpc_client


@pytest.fixture(autouse=True)
def _reset_breaker_state():
    rpc_client._breaker_state.clear()
    yield
    rpc_client._breaker_state.clear()


def _run(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, json_body: dict):
        self._json_body = json_body

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_body


def test_primary_success_no_fallback(monkeypatch):
    calls = []

    async def fake_post(self, url, json=None):
        calls.append(url)
        return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": {"value": 42}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = _run(rpc_client.call_rpc("solana", "getBalance", ["addr"]))
    assert result == {"value": 42}
    assert calls == ["https://api.mainnet-beta.solana.com"]


def test_transport_failure_falls_back_to_secondary(monkeypatch):
    calls = []

    async def fake_post(self, url, json=None):
        calls.append(url)
        if "ankr" not in url:
            raise httpx.ConnectTimeout("timeout", request=None)
        return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": {"value": 7}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = _run(rpc_client.call_rpc("solana", "getBalance", ["addr"]))
    assert result == {"value": 7}
    assert len(calls) == 2


def test_application_error_does_not_fall_back(monkeypatch):
    calls = []

    async def fake_post(self, url, json=None):
        calls.append(url)
        return _FakeResponse({"jsonrpc": "2.0", "id": 1, "error": {"message": "invalid address"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(RuntimeError, match="invalid address"):
        _run(rpc_client.call_rpc("solana", "getBalance", ["bad"]))
    # Nessun fallback: e' un errore applicativo, non di trasporto.
    assert calls == ["https://api.mainnet-beta.solana.com"]


def test_circuit_breaker_trips_after_threshold_and_skips_endpoint(monkeypatch):
    async def always_fail(self, url, json=None):
        raise httpx.ConnectTimeout("timeout", request=None)

    monkeypatch.setattr(httpx.AsyncClient, "post", always_fail)

    # robinhood ha un solo endpoint: N fallimenti consecutivi devono
    # comunque esaurire il breaker (candidates ricade sul primo se tutti
    # in cooldown) senza sollevare un errore diverso da RuntimeError.
    for _ in range(rpc_client._FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            _run(rpc_client.call_rpc("robinhood", "eth_call", []))

    url = rpc_client._ENDPOINTS["robinhood"][0]
    assert rpc_client._is_cooling_down(url)
    status = rpc_client.circuit_status()
    assert status["robinhood"]["endpoints"][0]["cooling_down"] is True


def test_success_resets_consecutive_failures(monkeypatch):
    state = {"fail": True}

    async def flaky(self, url, json=None):
        if state["fail"]:
            raise httpx.ConnectTimeout("timeout", request=None)
        return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "post", flaky)
    url = rpc_client._ENDPOINTS["solana"][0]

    with pytest.raises(RuntimeError):
        _run(rpc_client.call_rpc("solana", "getBalance", ["addr"]))
    assert rpc_client._state_for(url)["consecutive_failures"] >= 1

    state["fail"] = False
    result = _run(rpc_client.call_rpc("solana", "getBalance", ["addr"]))
    assert result == "ok"
    assert rpc_client._state_for(url)["consecutive_failures"] == 0
