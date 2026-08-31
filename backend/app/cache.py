import asyncio

from cachetools import TTLCache

_INTRADAY_TTL = 90
_DAILY_TTL = 600

_DAILY_PLUS_INTERVALS = {"1d", "1w", "1M"}

_intraday_cache: TTLCache = TTLCache(maxsize=256, ttl=_INTRADAY_TTL)
_daily_cache: TTLCache = TTLCache(maxsize=256, ttl=_DAILY_TTL)
_lock = asyncio.Lock()

# Singleflight: one in-flight Future per cache key — followers await the same
# Future instead of spawning duplicate fetches for the same (symbol, interval).
_in_flight: dict[tuple, asyncio.Future] = {}


def _cache_for(interval: str) -> TTLCache:
    return _daily_cache if interval in _DAILY_PLUS_INTERVALS else _intraday_cache


async def get_or_fetch(key: tuple, fetch_fn):
    cache = _cache_for(key[1])
    async with _lock:
        if key in cache:
            return cache[key]
        if key in _in_flight:
            fut: asyncio.Future = _in_flight[key]
            leader = False
        else:
            fut = asyncio.get_event_loop().create_future()
            _in_flight[key] = fut
            leader = True

    if not leader:
        # Wait for whoever started the fetch to finish; propagates exceptions.
        return await asyncio.shield(fut)

    try:
        result = await fetch_fn()
        async with _lock:
            cache[key] = result
        fut.set_result(result)
        return result
    except Exception as exc:
        fut.set_exception(exc)
        raise
    finally:
        async with _lock:
            _in_flight.pop(key, None)
