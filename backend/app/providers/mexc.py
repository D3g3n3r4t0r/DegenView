import httpx
import pandas as pd
from cachetools import TTLCache

from app.providers.base import DataProvider, ProviderError

BASE_URL = "https://api.mexc.com"
_CANONICAL_TO_INTERVAL = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "4h",
    "1d": "1d",
    "1w": "1W",
    "1M": "1M",
}
# MEXC's spot market has no bare-USD-quoted pairs (verified against /api/v3/exchangeInfo) —
# only USDT/USDC/etc. A trailing "USD" is normalized away below, not treated as already-quoted.
_QUOTE_ASSETS = ["USDT", "USDC", "FDUSD", "TUSD", "DAI", "BTC", "ETH"]
_MAX_SUGGESTIONS = 8

_symbols_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


def format_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper().replace("/", "").replace("-", "")
    for quote in _QUOTE_ASSETS:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol
    if symbol.endswith("USD") and len(symbol) > 3:
        symbol = symbol[:-3]
    return f"{symbol}USDT"


class MexcProvider(DataProvider):
    """Crypto only — public market data, no API key required."""

    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or BASE_URL

    async def fetch_ohlcv(self, symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
        formatted_symbol = format_symbol(symbol)
        interval = _CANONICAL_TO_INTERVAL[interval]
        params = {"symbol": formatted_symbol, "interval": interval, "limit": min(outputsize, 500)}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self._base_url}/api/v3/klines", params=params)

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(f"Risposta non valida da MEXC per {formatted_symbol}") from exc

        if isinstance(payload, dict) and "code" in payload:
            raise ProviderError(payload.get("msg", f"Errore MEXC per {formatted_symbol}"))

        if not payload:
            raise ProviderError(f"Nessun dato disponibile per {formatted_symbol} ({interval})")

        # [openTime_ms, open, high, low, close, volume, closeTime_ms, quoteVolume]
        df = pd.DataFrame(
            payload, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]
        )
        df["datetime"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        df = df.set_index("datetime").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    async def search_symbols(self, query: str) -> list[dict]:
        query = query.strip()
        if not query:
            return []

        symbols = _symbols_cache.get("all")
        if symbols is None:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self._base_url}/api/v3/exchangeInfo")
            payload = resp.json()
            symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
            _symbols_cache["all"] = symbols

        q = query.upper().replace("/", "")
        matches = [s for s in symbols if s.get("symbol", "").startswith(q) and s.get("isSpotTradingAllowed")]
        matches.sort(key=lambda s: (s.get("quoteAsset") != "USDT", len(s.get("symbol", ""))))

        out = []
        for s in matches[:_MAX_SUGGESTIONS]:
            base, quote = s.get("baseAsset", ""), s.get("quoteAsset", "")
            out.append({"symbol": s.get("symbol", ""), "name": s.get("fullName", "") or base, "exchange": f"MEXC ({quote})"})
        return out
