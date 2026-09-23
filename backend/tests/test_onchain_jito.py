"""Piano MEV — bundle Jito: verifica che la richiesta costruita rispetti
la doc reale (endpoint, metodo, encoding, tip account), non un invio vero
(nessun fondo reale in questa sessione per una tip transaction vera)."""
from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from app.trading.onchain import jito


def _run(coro):
    return asyncio.run(coro)


def test_tip_accounts_list_has_eight_distinct_addresses():
    assert len(jito.JITO_TIP_ACCOUNTS) == 8
    assert len(set(jito.JITO_TIP_ACCOUNTS)) == 8


def test_pick_tip_account_returns_one_of_the_official_eight():
    import random
    rng = random.Random(42)
    for _ in range(20):
        assert jito.pick_tip_account(rng) in jito.JITO_TIP_ACCOUNTS


def test_dynamic_tip_scales_with_notional_within_bounds():
    small = jito.compute_dynamic_tip_lamports(5.0, 150.0)
    large = jito.compute_dynamic_tip_lamports(5000.0, 150.0)
    assert jito.JITO_MIN_TIP_LAMPORTS <= small <= large <= jito.JITO_MAX_TIP_LAMPORTS


def test_dynamic_tip_never_below_minimum_even_for_tiny_notional():
    tip = jito.compute_dynamic_tip_lamports(0.01, 150.0)
    assert tip == jito.JITO_MIN_TIP_LAMPORTS


def test_dynamic_tip_capped_at_maximum_for_huge_notional():
    tip = jito.compute_dynamic_tip_lamports(10_000_000.0, 150.0)
    assert tip == jito.JITO_MAX_TIP_LAMPORTS


def test_dynamic_tip_handles_missing_price_without_crashing():
    assert jito.compute_dynamic_tip_lamports(100.0, 0.0) == jito.JITO_MIN_TIP_LAMPORTS


def test_send_bundle_via_jito_hits_real_endpoint_with_correct_shape(monkeypatch):
    """Mock della sola risposta HTTP: verifica URL, metodo JSON-RPC e
    struttura dei params (lista di 2 tx base64 + {"encoding": "base64"}),
    esattamente come documentato in docs.jito.wtf/lowlatencytxnsend/."""
    captured = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"jsonrpc": "2.0", "result": "bundle-xyz", "id": 1}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

    bundle_id = _run(jito.send_bundle_via_jito(b"signed-swap", b"signed-tip"))

    assert bundle_id == "bundle-xyz"
    assert captured["url"] == "https://mainnet.block-engine.jito.wtf:443/api/v1/bundles"
    payload = captured["payload"]
    assert payload["method"] == "sendBundle"
    assert payload["jsonrpc"] == "2.0"
    txs, opts = payload["params"]
    assert len(txs) == 2
    assert base64.b64decode(txs[0]) == b"signed-swap"
    assert base64.b64decode(txs[1]) == b"signed-tip"
    assert opts == {"encoding": "base64"}


def test_send_bundle_via_jito_raises_on_rpc_error(monkeypatch):
    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"jsonrpc": "2.0", "error": {"message": "bundle contains an already processed transaction"}}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

    with pytest.raises(RuntimeError):
        _run(jito.send_bundle_via_jito(b"a", b"b"))


def test_send_bundle_via_jito_raises_on_http_error(monkeypatch):
    class _FakeResponse:
        status_code = 500
        text = "internal error"

        def json(self):
            return {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

    with pytest.raises(RuntimeError):
        _run(jito.send_bundle_via_jito(b"a", b"b"))


def test_tip_transfer_instruction_data_encodes_index_and_amount():
    data = jito.build_tip_transfer_instruction_data(1234)
    assert data[:4] == (2).to_bytes(4, "little")
    assert int.from_bytes(data[4:], "little") == 1234
