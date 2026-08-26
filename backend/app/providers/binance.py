import httpx
import pandas as pd
from cachetools import TTLCache

from app.providers.base import DataProvider, ProviderError

BASE_URL = "https://api.binance.com"
_CANONICAL_TO_INTERVAL = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
}
_QUOTE_ASSETS = ["USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "BTC", "ETH"]
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


class BinanceProvider(DataProvider):
    """Crypto only — public market data, no API key required. Deeper, more
    reliable history than MEXC for majors; MEXC stays the pick for freshly
    listed memecoins Binance doesn't carry yet."""

    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or BASE_URL

    async def fetch_ohlcv(self, symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
        formatted_symbol = format_symbol(symbol)
        interval = _CANONICAL_TO_INTERVAL[interval]
        params = {"symbol": formatted_symbol, "interval": interval, "limit": min(outputsize, 1000)}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self._base_url}/api/v3/klines", params=params)

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(f"Risposta non valida da Binance per {formatted_symbol}") from exc

        if isinstance(payload, dict) and "code" in payload:
            raise ProviderError(payload.get("msg", f"Errore Binance per {formatted_symbol}"))

        if not payload:
            raise ProviderError(f"Nessun dato disponibile per {formatted_symbol} ({interval})")

        # [openTime_ms, open, high, low, close, volume, closeTime_ms, quoteVolume, ...]
        df = pd.DataFrame(payload, columns=range(len(payload[0])))
        df = df.iloc[:, :6]
        df.columns = ["open_time", "open", "high", "low", "close", "volume"]
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
        matches = [
            s
            for s in symbols
            if s.get("symbol", "").startswith(q) and s.get("isSpotTradingAllowed") and s.get("status") == "TRADING"
        ]
        matches.sort(key=lambda s: (s.get("quoteAsset") != "USDT", len(s.get("symbol", ""))))

        out = []
        for s in matches[:_MAX_SUGGESTIONS]:
            base, quote = s.get("baseAsset", ""), s.get("quoteAsset", "")
            out.append({"symbol": s.get("symbol", ""), "name": base, "exchange": f"Binance ({quote})"})
        return out
