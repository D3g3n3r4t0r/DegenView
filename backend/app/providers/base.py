from abc import ABC, abstractmethod

import pandas as pd


class ProviderError(Exception):
    """Raised when a data provider fails to return usable OHLCV data."""


class DataProvider(ABC):
    """Each provider is already scoped to one asset type (chosen by the caller);
    it maps the canonical interval (app.timeframes.IntervalChoice) to its own format."""

    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
        """Return a DataFrame indexed by UTC datetime, columns: open, high, low, close, volume."""
        raise NotImplementedError

    @abstractmethod
    async def search_symbols(self, query: str) -> list[dict]:
        """Return up to a handful of {symbol, name, exchange} matches for a partial ticker query."""
        raise NotImplementedError
