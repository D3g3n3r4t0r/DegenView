from abc import ABC, abstractmethod

import pandas as pd


class ProviderError(Exception):
    """Raised when a data provider fails to return usable OHLCV data."""


class ProviderUnreachable(ProviderError):
    """L'exchange non ha risposto: rete, TLS, proxy.

    Distinta perche' e' quasi sempre passeggera e si risolve da sola al giro
    dopo. Trattata come un guasto qualunque produceva un messaggio allarmante
    al minuto per ticker — e' arrivata sulla bacheca cosi', per un errore TLS
    di MEXC che poi non si e' piu' ripresentato.
    """


class QuotaExceeded(ProviderError):
    """The provider refused because the plan's quota is spent, not because
    anything is wrong with the request.

    Kept apart from ProviderError because it calls for the opposite reaction:
    a normal failure is worth retrying at the next pass, this one is worth
    stopping for. Retrying it every minute burns nothing but does produce one
    alarming message per ticker per minute, which is how it reached the board
    as "errore monitoraggio" — a wording that suggests something broke.
    """

    def __init__(self, message: str, retry_after_s: int | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class DataProvider(ABC):
    """Each provider is already scoped to one asset type (chosen by the caller);
    it maps the canonical interval (app.timeframes.IntervalChoice) to its own format."""

    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, interval: str, outputsize: int, since_ms: int | None = None) -> pd.DataFrame:
        """Return a DataFrame indexed by UTC datetime, columns: open, high, low, close, volume.

        When since_ms is provided, fetch all available candles from that
        timestamp to now, ignoring outputsize. The caller is responsible for
        any further slicing."""
        raise NotImplementedError

    @abstractmethod
    async def search_symbols(self, query: str) -> list[dict]:
        """Return up to a handful of {symbol, name, exchange} matches for a partial ticker query."""
        raise NotImplementedError
