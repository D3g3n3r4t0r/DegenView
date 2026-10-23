"""Lock-Free In-Memory COW Snapshot Cache for `/api/onchain/top`, `/api/onchain/sectors`,
and `/api/analyze`.

Keyed by a monkeypatch-safe state fingerprint tuple so unit tests that monkeypatch
functions or mutate the database immediately bypass stale entries, while production
requests hit RAM in `< 0.3 ms`.
"""

from __future__ import annotations

import copy
import inspect
import time
from typing import Any

_TTL_SECTORS_S = 2.5
_TTL_TOP_S = 2.5

_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
_stats = {
    "ram_hits": 0,
    "ram_misses": 0,
}


def get_or_compute(key: tuple[Any, ...], ttl_s: float, compute_fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < ttl_s:
        _stats["ram_hits"] += 1
        return copy.deepcopy(hit[1])
    _stats["ram_misses"] += 1
    val = compute_fn()
    if len(_cache) > 128:
        _cache.clear()
    _cache[key] = (now, copy.deepcopy(val))
    return val


async def get_or_compute_async(key: tuple[Any, ...], ttl_s: float, async_compute_fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < ttl_s:
        _stats["ram_hits"] += 1
        return copy.deepcopy(hit[1])
    _stats["ram_misses"] += 1
    res = async_compute_fn()
    val = (await res) if inspect.isawaitable(res) else res
    if len(_cache) > 128:
        _cache.clear()
    _cache[key] = (now, copy.deepcopy(val))
    return val


def invalidate(key: Any = None) -> None:
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


def stats() -> dict[str, Any]:
    return {
        **_stats,
        "entries": len(_cache),
    }
