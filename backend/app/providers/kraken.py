import httpx
import pandas as pd
from cachetools import TTLCache

from app.providers.base import DataProvider, ProviderError, ProviderUnreachable

BASE_URL = "https://api.kraken.com"
_CANONICAL_TO_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}
# Kraken chiama Bitcoin "XBT", non "BTC" — l'unico exchange fra quelli
# collegati con questa stranezza. Un utente che scrive "BTC" deve comunque
# trovare il pair giusto senza doverlo sapere.
_BASE_ALIASES = {"BTC": "XBT"}
_QUOTE_ASSETS = ["USDT", "USDC", "USD", "EUR", "BTC", "XBT", "ETH"]
_MAX_SUGGESTIONS = 25

_symbols_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


def format_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper().replace("/", "").replace("-", "")
    for base, alias in _BASE_ALIASES.items():
        if symbol.startswith(base):
            symbol = alias + symbol[len(base):]
            break
    for quote in _QUOTE_ASSETS:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol
    return f"{symbol}USD"


class KrakenProvider(DataProvider):
    """Crypto only — dati pubblici, nessuna chiave richiesta.

    Limite reale, non aggirabile: l'endpoint pubblico OHLC di Kraken non
    pagina all'indietro nel tempo come MEXC/Binance/KuCoin — restituisce
    sempre e solo le candele piu' recenti, al massimo 720 per intervallo,
    qualunque sia `outputsize` richiesto. Per un backtest che vuole la
    storia piu' profonda possibile questo e' un limite vero: su 1d, 720
    candele sono meno di due anni, contro le migliaia che gli altri
    provider restituiscono. Dichiarato qui, non nascosto — chi chiama
    ottiene comunque quello che c'e', solo meno di quanto chiesto.
    """

    _MAX_CANDLES = 720

    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or BASE_URL

    async def fetch_ohlcv(self, symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
        formatted_symbol = format_symbol(symbol)
        minutes = _CANONICAL_TO_MINUTES.get(interval)
        if minutes is None:
            raise ProviderError(f"Timeframe {interval} non supportato su Kraken")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._base_url}/0/public/OHLC",
                    params={"pair": formatted_symbol, "interval": minutes},
                )
            try:
                payload = resp.json()
            except ValueError as exc:
                raise ProviderError(f"Risposta non valida da Kraken per {formatted_symbol}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnreachable(f"Kraken non raggiungibile per {formatted_symbol}: {exc}") from exc

        errors = payload.get("error") or []
        if errors:
            raise ProviderError(f"Kraken non riconosce {formatted_symbol}: {'; '.join(errors)}")

        result = payload.get("result") or {}
        # La chiave del risultato non e' il pair richiesto ma il nome interno
        # di Kraken per quel pair (es. XXBTZUSD per XBTUSD) — c'e' sempre
        # esattamente una chiave oltre a "last".
        rows = next((v for k, v in result.items() if k != "last"), None)
        if not rows:
            raise ProviderError(f"Nessun dato disponibile per {formatted_symbol} ({interval})")

        df = pd.DataFrame(
            rows, columns=["open_time", "open", "high", "low", "close", "vwap", "volume", "count"]
        )
        df["datetime"] = pd.to_datetime(df["open_time"].astype("int64"), unit="s", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        df = df.set_index("datetime").sort_index()
        df = df[~df.index.duplicated(keep="first")]
        return df[["open", "high", "low", "close", "volume"]].tail(min(outputsize, self._MAX_CANDLES))

    async def search_symbols(self, query: str) -> list[dict]:
        query = query.strip()
        if not query:
            return []

        pairs = _symbols_cache.get("all")
        if pairs is None:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self._base_url}/0/public/AssetPairs")
            payload = resp.json()
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            pairs = [v for v in result.values() if not (v.get("status") or "online") != "online"]
            _symbols_cache["all"] = pairs

        q = query.upper().replace("/", "")
        for base, alias in _BASE_ALIASES.items():
            if q.startswith(base):
                q = alias + q[len(base):]
                break

        def alt(p: dict) -> str:
            return p.get("altname", "")

        starts = [p for p in pairs if alt(p).startswith(q)]
        contains = [p for p in pairs if q in alt(p) and not alt(p).startswith(q)]
        matches = starts + contains
        # Senza una preferenza esplicita per il quote, il pareggio a parita' di
        # lunghezza si decideva alfabeticamente — XBTAUD prima di XBTUSD, un
        # ordine che non riflette cosa cerca davvero chi digita "BTC".
        matches.sort(key=lambda p: (
            not alt(p).startswith(q),
            p.get("quote", "") not in ("ZUSDT", "USDT", "ZUSD", "USD"),
            len(alt(p)),
        ))

        out = []
        for p in matches[:_MAX_SUGGESTIONS]:
            base = (p.get("base") or "").lstrip("XZ") if len(p.get("base", "")) == 4 else p.get("base", "")
            quote = (p.get("quote") or "").lstrip("XZ") if len(p.get("quote", "")) == 4 else p.get("quote", "")
            display_base = "BTC" if base == "XBT" else base
            out.append({
                "symbol": alt(p),
                "name": p.get("wsname", "") or display_base,
                "exchange": f"Kraken ({quote})",
            })
        return out
