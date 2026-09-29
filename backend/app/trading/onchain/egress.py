"""Outbound requests to addresses that anyone can write (a token's website).

Checking the host before the request is not enough: HTTPX (or Chromium)
resolves the name again when it connects, and a DNS answer that changes in
between (rebinding) lands on an internal address. Here the check runs at
connect time, on the very IP the socket opens, so there is no second lookup.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpcore
import httpx


async def public_ip(host: str) -> str | None:
    """The address to connect to, or None when any answer is not public."""
    try:
        return host if ipaddress.ip_address(host).is_global else None
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return None
    ips = [info[4][0] for info in infos]
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        return None
    return ips[0]


class _PublicOnly(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ip = await public_ip(host)
        if ip is None:
            raise httpcore.ConnectError(f"non-public address: {host}")
        # TLS still verifies the certificate against `host`: httpcore takes
        # the server name from the request, not from this socket.
        return await self._inner.connect_tcp(ip, port, timeout=timeout, local_address=local_address,
                                             socket_options=socket_options)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def public_client(**kwargs) -> httpx.AsyncClient:
    """A client that can only open connections to public IPs. No proxy from
    the environment: a proxy would be the address checked, not the site."""
    transport = httpx.AsyncHTTPTransport()
    transport._pool._network_backend = _PublicOnly()
    return httpx.AsyncClient(transport=transport, trust_env=False, **kwargs)


def is_network(client: httpx.AsyncClient) -> bool:
    """True for a client that talks to the real network (not a test mock)."""
    return isinstance(getattr(client, "_transport", None), httpx.AsyncHTTPTransport)
