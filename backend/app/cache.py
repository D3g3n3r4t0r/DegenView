import asyncio

from cachetools import TTLCache

_INTRADAY_TTL = 90
_DAILY_TTL = 600

_DAILY_PLUS_INTERVALS = {"1d", "1w", "1M"}

_intraday_cache: TTLCache = TTLCache(maxsize=256, ttl=_INTRADAY_TTL)
_daily_cache: TTLCache = TTLCache(maxsize=256, ttl=_DAILY_TTL)
_lock = asyncio.Lock()


def _cache_for(interval: str) -> TTLCache:
    return _daily_cache if interval in _DAILY_PLUS_INTERVALS else _intraday_cache


async def get_or_fetch(key: tuple, fetch_fn):
    cache = _cache_for(key[1])
    async with _lock:
        if key in cache:
            return cache[key]
    result = await fetch_fn()
    async with _lock:
        cache[key] = result
    return result
