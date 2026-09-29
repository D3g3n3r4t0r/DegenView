import asyncio

import httpx
import pytest

from app.trading.onchain import egress, legit


def test_public_ip_rejects_internal_literals():
    for ip in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "192.168.1.1"):
        assert asyncio.run(egress.public_ip(ip)) is None
    assert asyncio.run(egress.public_ip("1.1.1.1")) == "1.1.1.1"


def test_any_internal_answer_blocks_the_name(monkeypatch):
    async def fake(self, host, port, **kw):
        return [(0, 0, 0, "", ("1.1.1.1", 0)), (0, 0, 0, "", ("10.0.0.1", 0))]
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    assert asyncio.run(egress.public_ip("mixed.example")) is None


def test_connect_time_check_catches_a_rebound_name(monkeypatch):
    """The first lookup said public, the one at connect says loopback."""
    async def fake(self, host, port, **kw):
        return [(0, 0, 0, "", ("127.0.0.1", 0))]
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)

    async def go():
        async with egress.public_client() as c:
            await c.get("http://rebind.example:8000/admin")
    with pytest.raises(httpx.ConnectError, match="non-public"):
        asyncio.run(go())


def test_fetch_site_on_the_network_uses_the_guarded_client(monkeypatch):
    async def public(host):
        return True                      # the early check is fooled
    monkeypatch.setattr(legit, "_public_host", public)

    async def go():
        async with httpx.AsyncClient() as c:
            assert egress.is_network(c)
            return await legit.fetch_site("http://127.0.0.1:8000/admin", c)
    out = asyncio.run(go())
    assert not out["ok"] and out["error"] == "ConnectError"


def test_mock_clients_are_not_network():
    assert not egress.is_network(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
