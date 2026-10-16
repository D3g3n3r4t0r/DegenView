"""BTC filter: no long entry while BTC is below its weekly EMA 21.

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

The regime of a candle is the last CLOSED weekly BTC candle against the EMA
21 of the weekly closes (15/10, after the test environment: the same results
as the daily EMA 200 the filter started with, but 5-6 changes a year instead
of 15-17 — Lorenzo: "per avere un segnale di mercato piu' nitido il timeframe
del filtro dovrebbe essere weekly", then "Ok, procedi"). A week closes on
Sunday; its verdict applies from the Monday after, so no look-ahead. Before
the BTC history starts (or before 21 weeks of it) the filter does not act.

`btc_filter_exit` (second switch, only with the filter on): a long still open
is also closed when the filter turns off. Measured: on RSI+BB 4H the worst
2022 loss -61% -> -12% for +28 -> +25% a year in 2023-26; costly on RSI+BB
1D (+33 -> +11% a year), no effect on Lorenzo.

The daily closes are cached in memory and refreshed in the background
(main._btc_regime_loop); the strategy code is synchronous and only reads the
cache. With the switch on and no cache yet, BtcRegimeUnavailable is raised
rather than silently ignoring the filter.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

EMA_WEEKS = 21
MIN_DAYS = 200      # daily closes needed to load (and 21 weeks of them)

_closes: pd.Series | None = None
_up: pd.Series | None = None       # weekly, indexed on the Monday it applies from
_up_daily: pd.Series | None = None
_band: pd.Series | None = None     # weekly, Monday it applies from: above the Bull Market Support Band
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
    global _closes, _up, _up_daily, _band, _updated, _pinned
    closes = closes.astype(float).sort_index()
    if closes.index.tz is None:
        closes.index = closes.index.tz_localize("UTC")
    day = closes.groupby(closes.index.normalize()).last()
    # a week (Monday-Sunday) closes with Sunday's daily close; the week still
    # running is left out: its Sunday has not come yet
    week = day.resample("W-SUN").last().dropna()
    if len(day) and day.index[-1].dayofweek != 6:
        week = week.iloc[:-1]
    ema = week.ewm(span=EMA_WEEKS, adjust=False, min_periods=EMA_WEEKS).mean()
    # True where the filter lets longs in; unknown (no history yet) counts as in
    up = (week > ema).where(ema.notna(), True)
    _up = up.shift(1, freq="D")                  # from the Monday after the close
    _up_daily = _up.reindex(pd.date_range(_up.index[0], _up.index[-1] + pd.Timedelta(days=6),
                                          freq="D", tz="UTC"), method="ffill") if len(_up) else _up
    # Bull Market Support Band (weekly SMA 20 and EMA 21): above = over both;
    # before 20 weeks of history it counts as not above
    top = np.maximum(week.rolling(20).mean(), week.ewm(span=21, adjust=False).mean())
    _band = ((week > top) & top.notna()).shift(1, freq="D")
    _closes, _updated, _pinned = day, time.time(), pin


def clear() -> None:
    global _closes, _up, _up_daily, _band, _updated, _pinned
    _closes = _up = _up_daily = _band = None
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


def band_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """True where BTC's last closed week is above its Bull Market Support
    Band (RSI+BB BTC band). Before the BTC history: False."""
    if _band is None:
        raise BtcRegimeUnavailable("RSI+BB BTC band: BTC daily candles not loaded yet, retry in a minute")
    idx = index if index.tz is not None else index.tz_localize("UTC")
    out = _band.reindex(idx, method="ffill")
    return out.where(out.notna(), False).to_numpy(dtype=bool)


def _state(weekly: pd.Series | None) -> dict | None:
    """Current verdict of a weekly series and the Monday it took effect."""
    if weekly is None or not len(weekly):
        return None
    v = weekly.astype(bool)
    now = bool(v.iloc[-1])
    changed = v.ne(v.shift()).to_numpy()
    since = v.index[changed.nonzero()[0][-1]] if changed.any() else v.index[0]
    return {"up": now, "since": f"{since:%Y-%m-%d}"}


def status() -> dict:
    """BTC as the filter and the band strategy see it now (top-bar badge)."""
    if _closes is None:
        return {"loaded": False}
    return {"loaded": True, "close": round(float(_closes.iloc[-1]), 2), "as_of": f"{_closes.index[-1]:%Y-%m-%d}",
            "ema21": _state(_up), "band": _state(_band)}


def down_share(year: int) -> float:
    """Share of the days of `year` with longs blocked (0 when unknown)."""
    if _up_daily is None:
        return 0.0
    days = _up_daily[(_up_daily.index.year == year)]
    return 0.0 if days.empty else float((~days.astype(bool)).mean())


def exit_enabled(params: dict | None) -> bool:
    return enabled(params) and enabled({"btc_filter": (params or {}).get("btc_filter_exit")})


def apply(signals: pd.DataFrame, params: dict | None) -> pd.DataFrame:
    if not enabled(params) or "entry_long" not in signals:
        return signals
    out = signals.copy()
    up = up_mask(out.index)
    out["entry_long"] = out["entry_long"].to_numpy(dtype=bool) & up
    if exit_enabled(params) and "exit_long" in out:
        out["exit_long"] = out["exit_long"].to_numpy(dtype=bool) | ~up
    return out


async def refresh() -> None:
    """Load BTCUSDT daily candles from MEXC (the site's crypto provider)."""
    if _pinned:
        return
    from app.providers.mexc import MexcProvider
    df = await MexcProvider().fetch_ohlcv("BTCUSDT", "1d", 4000)
    if df is not None and len(df) >= MIN_DAYS:
        set_closes(df["close"])
