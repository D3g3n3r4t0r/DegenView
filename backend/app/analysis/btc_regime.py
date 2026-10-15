"""BTC filter: no long entry while BTC is below its daily EMA 200.

Lorenzo, 15/10: "Il filtro Btc può essere utile da attivare/disattivare su
tutte le strategie del sito?", then "Ok, implementiamo così". Measured in the
test environment (scripts/compare_claudio_folds.py, SET=btc, 35 pairs, values
chosen from 2023, tested on 2021 and 2022): it wiped out most of the 2022
losses of every long strategy and cost some return in the sideways years.

One switch per strategy (`btc_filter` in the strategy params, off by
default), applied where every strategy is dispatched (strategies.
STRATEGY_REGISTRY), so Run, the chart, the alerts, the archive and the
optimizations all see the same filtered signals. Only long ENTRIES are
blocked: exits and shorts are untouched.

The regime of a candle is the PREVIOUS day's BTC close against its EMA 200:
known before the candle opens, so no look-ahead. Before the BTC history
starts (or before 200 days of it) the filter does not act.

The daily closes are cached in memory and refreshed in the background
(main._btc_regime_loop); the strategy code is synchronous and only reads the
cache. With the switch on and no cache yet, BtcRegimeUnavailable is raised
rather than silently ignoring the filter.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

EMA_DAYS = 200

_closes: pd.Series | None = None
_up: pd.Series | None = None
_updated = 0.0
_pinned = False


class BtcRegimeUnavailable(RuntimeError):
    pass


def enabled(params: dict | None) -> bool:
    if not params:
        return False
    v = params.get("btc_filter")
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def set_closes(closes: pd.Series, pin: bool = False) -> None:
    """Daily BTC closes (UTC-indexed). `pin` keeps them from the background
    refresh (tests)."""
    global _closes, _up, _updated, _pinned
    closes = closes.astype(float).sort_index()
    if closes.index.tz is None:
        closes.index = closes.index.tz_localize("UTC")
    day = closes.groupby(closes.index.normalize()).last()
    ema = day.ewm(span=EMA_DAYS, adjust=False, min_periods=EMA_DAYS).mean()
    # True where the filter lets longs in; unknown (no history yet) counts as in
    up = (day > ema).where(ema.notna(), True)
    # the regime of day D is decided by the close of D-1
    _up = up.shift(1, freq="D")
    _closes, _updated, _pinned = day, time.time(), pin


def clear() -> None:
    global _closes, _up, _updated, _pinned
    _closes = _up = None
    _updated, _pinned = 0.0, False


def age_s() -> float | None:
    return None if _closes is None else time.time() - _updated


def pinned() -> bool:
    return _pinned


def up_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """True where a long may open, one value per candle of `index`."""
    if _up is None:
        raise BtcRegimeUnavailable("BTC filter: BTC daily candles not loaded yet, retry in a minute")
    idx = index if index.tz is not None else index.tz_localize("UTC")
    first = _up.index[0]
    out = _up.reindex(idx, method="ffill")
    out = out.where(~((idx < first) | out.isna()), True)        # before the BTC history: no filter
    return out.to_numpy(dtype=bool)


def down_share(year: int) -> float:
    """Share of the days of `year` with longs blocked (0 when unknown)."""
    if _up is None:
        return 0.0
    days = _up[(_up.index.year == year)]
    return 0.0 if days.empty else float((~days.astype(bool)).mean())


def apply(signals: pd.DataFrame, params: dict | None) -> pd.DataFrame:
    if not enabled(params) or "entry_long" not in signals:
        return signals
    out = signals.copy()
    out["entry_long"] = out["entry_long"].to_numpy(dtype=bool) & up_mask(out.index)
    return out


async def refresh() -> None:
    """Load BTCUSDT daily candles from MEXC (the site's crypto provider)."""
    if _pinned:
        return
    from app.providers.mexc import MexcProvider
    df = await MexcProvider().fetch_ohlcv("BTCUSDT", "1d", 4000)
    if df is not None and len(df) >= EMA_DAYS:
        set_closes(df["close"])
