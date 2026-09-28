"""The wallet snapshot is read once, not once per caller (main._wallet_snapshot).

Lorenzo, 28/09: "passare da real wallet a simulato e' laggoso e molto lento,
a volte non va neanche". /api/profile and /api/wallets/total asked for the
same chain read at the same moment, and every switch asked again.
"""
from __future__ import annotations

import asyncio

import pytest

from app import main
from app.models import User

USER = User(id="u", email="u@example.com", password_hash="x")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    main._snap_cache.clear()
    main._snap_inflight.clear()
    clock = [1000.0]
    monkeypatch.setattr(main, "_snap_clock", lambda: clock[0])
    yield clock
    main._snap_cache.clear()
    main._snap_inflight.clear()


def _fake(monkeypatch, fail=False):
    calls = []

    async def read(user):
        calls.append(user.id)
        await asyncio.sleep(0.05)
        if fail:
            raise RuntimeError("chain down")
        return {"total": 2.0}
    monkeypatch.setattr(main, "_wallet_snapshot_uncached", read)
    return calls


def test_concurrent_callers_share_one_read(monkeypatch):
    calls = _fake(monkeypatch)

    async def run():
        return await asyncio.gather(main._wallet_snapshot(USER), main._wallet_snapshot(USER))
    a, b = asyncio.run(run())
    assert a == b == {"total": 2.0}
    assert calls == ["u"]


def test_fresh_entry_is_reused_then_expires(monkeypatch, _clean):
    calls = _fake(monkeypatch)
    asyncio.run(main._wallet_snapshot(USER))
    _clean[0] += 10
    asyncio.run(main._wallet_snapshot(USER))
    assert len(calls) == 1
    _clean[0] += main._SNAP_TTL
    asyncio.run(main._wallet_snapshot(USER))
    assert len(calls) == 2


def test_failures_are_not_cached(monkeypatch):
    calls = _fake(monkeypatch, fail=True)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            asyncio.run(main._wallet_snapshot(USER))
    assert len(calls) == 2
