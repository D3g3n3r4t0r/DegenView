import asyncio
import time

import httpx
import pandas as pd
from cachetools import TTLCache

from app.config import settings
from app.providers.base import DataProvider, ProviderError

_PREFERRED_EXCHANGES = {"NASDAQ", "NYSE"}
_PREFERRED_INSTRUMENT_TYPES = {"Common Stock", "ETF"}
_MAX_SUGGESTIONS = 8
_CANONICAL_TO_INTERVAL = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
    "1w": "1week",
    "1M": "1month",
}

_stock_search_cache: TTLCache = TTLCache(maxsize=256, ttl=300)

# Twelve Data's free tier allows 8 requests/minute *total* — shared across
# every browser tab (own + friends', once the app is shared via a tunnel) and
# the watchlist background loop. Rather than let bursts hit that cap and come
# back as ugly 429-style errors, queue our own outgoing requests to stay a
# little under it; callers just see a brief delay instead of a failure.
_RATE_LIMIT_PER_MINUTE = 7
_RATE_WINDOW_SECONDS = 60.0
_request_times: list[float] = []
_rate_lock = asyncio.Lock()


async def _throttle() -> None:
    async with _rate_lock:
        while True:
            now = time.monotonic()
            while _request_times and now - _request_times[0] > _RATE_WINDOW_SECONDS:
                _request_times.pop(0)
            if len(_request_times) < _RATE_LIMIT_PER_MINUTE:
                _request_times.append(now)
                return
            wait = _RATE_WINDOW_SECONDS - (now - _request_times[0]) + 0.1
            await asyncio.sleep(wait)


class TwelveDataProvider(DataProvider):
    """Stocks/equities only — crypto is served by MexcProvider instead."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key or settings.twelve_data_api_key
        self._base_url = base_url or settings.twelve_data_base_url

    async def fetch_ohlcv(self, symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
        if not self._api_key:
            raise ProviderError("Chiave API Twelve Data mancante. Impostala in backend/.env")

        formatted_symbol = symbol.strip().upper()
        interval = _CANONICAL_TO_INTERVAL[interval]
        params = {
            "symbol": formatted_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": self._api_key,
            "format": "JSON",
            "timezone": "UTC",
        }

        await _throttle()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self._base_url}/time_series", params=params)

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(f"Risposta non valida da Twelve Data per {formatted_symbol}") from exc

        if isinstance(payload, dict) and payload.get("status") == "error":
            raise ProviderError(payload.get("message", f"Errore Twelve Data per {formatted_symbol}"))

        values = payload.get("values") if isinstance(payload, dict) else None
        if not values:
            raise ProviderError(f"Nessun dato disponibile per {formatted_symbol} ({interval})")

        df = pd.DataFrame(values)
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0

        df = df.set_index("datetime").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    async def search_symbols(self, query: str) -> list[dict]:
        query = query.strip()
        if not query or not self._api_key:
            return []

        cache_key = query.upper()
        cached = _stock_search_cache.get(cache_key)
        if cached is not None:
            return cached

        await _throttle()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self._base_url}/symbol_search",
                params={"symbol": query, "outputsize": 30, "apikey": self._api_key},
            )
        payload = resp.json()
        items = payload.get("data", []) if isinstance(payload, dict) else []

        q = query.upper()

        def sort_key(item: dict):
            symbol = item.get("symbol", "").upper()
            return (
                symbol != q,
                item.get("exchange") not in _PREFERRED_EXCHANGES,
                item.get("instrument_type") not in _PREFERRED_INSTRUMENT_TYPES,
                not symbol.startswith(q),
                len(symbol),
            )

        items.sort(key=sort_key)

        seen: set[tuple[str, str]] = set()
        out = []
        for item in items:
            symbol, exchange = item.get("symbol", ""), item.get("exchange", "")
            if (symbol, exchange) in seen:
                continue
            seen.add((symbol, exchange))
            out.append({"symbol": symbol, "name": item.get("instrument_name", ""), "exchange": exchange})
            if len(out) >= _MAX_SUGGESTIONS:
                break

        _stock_search_cache[cache_key] = out
        return out
