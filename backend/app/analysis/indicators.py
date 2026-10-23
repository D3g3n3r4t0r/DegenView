import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401  (registers the .ta accessor on DataFrame)

from app.models import IndicatorSeries

_IND_CACHE: dict[tuple, list[IndicatorSeries]] = {}
_IND_CACHE_MAX = 192


def _series_to_values(s: pd.Series) -> list[float | None]:
    arr = s.to_numpy(dtype=np.float64, copy=False)
    return [float(v) if v == v else None for v in arr]


def _first_col(df: pd.DataFrame | None, prefix: str) -> pd.Series | None:
    if df is None:
        return None
    col = next((c for c in df.columns if c.startswith(prefix)), None)
    return df[col] if col is not None else None


def _as_series(x: object, n: int) -> pd.Series | None:
    # When a requested indicator's length exceeds the available history (e.g.
    # a 50-period EMA on a symbol with only 48 candles at this timeframe),
    # pandas_ta silently returns the *input* DataFrame back unchanged instead
    # of a NaN-filled Series. Iterating that as if it were a series of prices
    # yields its column names ('open', 'high', ...) — not floats — and blows
    # up downstream. Anything that isn't a proper same-length Series is
    # simply "not enough data for this indicator" and gets dropped.
    return x if isinstance(x, pd.Series) and len(x) == n else None


def _as_dataframe(x: object, n: int) -> pd.DataFrame | None:
    return x if isinstance(x, pd.DataFrame) and len(x) == n else None


# VWAP resets at the start of each anchor period. A daily anchor on a daily
# chart makes every bar its own period, so the "VWAP" was just (H+L+C)/3 of
# each candle, and on 4h it reset every 6 bars into a sawtooth. One anchor
# period spans many bars on every timeframe instead.
VWAP_ANCHORS: dict[str, str] = {
    "1m": "D", "5m": "D", "15m": "D", "30m": "D",
    "1h": "W", "4h": "W",
    "1d": "M", "2d": "M", "3d": "M", "5d": "M",
    "1w": "Y", "1M": "Y",
}


def vwap_anchor(interval: str | None) -> str:
    return VWAP_ANCHORS.get(interval or "", "D")


def compute_indicators(df: pd.DataFrame, interval: str | None = None) -> list[IndicatorSeries]:
    n = len(df)
    cache_key = None
    if n >= 2 and "close" in df.columns:
        try:
            c_arr = df["close"].to_numpy(dtype=np.float64, copy=False)
            cache_key = (
                interval or "",
                n,
                int(df.index[0].value),
                int(df.index[-1].value),
                float(c_arr[0]),
                float(c_arr[-1]),
                float(c_arr[-2]),
            )
            hit = _IND_CACHE.get(cache_key)
            if hit is not None:
                return list(hit)
        except Exception:
            cache_key = None

    out: list[IndicatorSeries] = []

    ema20 = _as_series(df.ta.ema(length=20), n)
    ema50 = _as_series(df.ta.ema(length=50), n)
    rsi14 = _as_series(df.ta.rsi(length=14), n)
    macd = _as_dataframe(df.ta.macd(), n)
    # ddof=0: population deviation, as TradingView's stdev() and as the RSI+BB
    # strategy computes its own bands (strategies.py). pandas-ta's default
    # ddof=1 drew the bands ~2.6% wider than the ones the signals use.
    bbands = _as_dataframe(df.ta.bbands(length=20, std=2.0, ddof=0), n)
    vwap = _as_series(df.ta.vwap(anchor=vwap_anchor(interval)), n)
    stoch = _as_dataframe(df.ta.stoch(k=14, d=3, smooth_k=3), n)

    if ema20 is not None:
        out.append(IndicatorSeries(name="EMA20", values=_series_to_values(ema20)))
    if ema50 is not None:
        out.append(IndicatorSeries(name="EMA50", values=_series_to_values(ema50)))
    if rsi14 is not None:
        out.append(IndicatorSeries(name="RSI14", values=_series_to_values(rsi14)))

    macd_line = _first_col(macd, "MACD_")
    macd_signal = _first_col(macd, "MACDs_")
    macd_hist = _first_col(macd, "MACDh_")
    if macd_line is not None:
        out.append(IndicatorSeries(name="MACD", values=_series_to_values(macd_line)))
    if macd_signal is not None:
        out.append(IndicatorSeries(name="MACD_signal", values=_series_to_values(macd_signal)))
    if macd_hist is not None:
        out.append(IndicatorSeries(name="MACD_hist", values=_series_to_values(macd_hist)))

    bb_lower = _first_col(bbands, "BBL_")
    bb_mid = _first_col(bbands, "BBM_")
    bb_upper = _first_col(bbands, "BBU_")
    if bb_lower is not None:
        out.append(IndicatorSeries(name="BB_lower", values=_series_to_values(bb_lower)))
    if bb_mid is not None:
        out.append(IndicatorSeries(name="BB_mid", values=_series_to_values(bb_mid)))
    if bb_upper is not None:
        out.append(IndicatorSeries(name="BB_upper", values=_series_to_values(bb_upper)))

    if vwap is not None:
        out.append(IndicatorSeries(name="VWAP", values=_series_to_values(vwap)))

    stoch_k = _first_col(stoch, "STOCHk_")
    stoch_d = _first_col(stoch, "STOCHd_")
    if stoch_k is not None:
        out.append(IndicatorSeries(name="STOCH_K", values=_series_to_values(stoch_k)))
    if stoch_d is not None:
        out.append(IndicatorSeries(name="STOCH_D", values=_series_to_values(stoch_d)))

    if cache_key is not None:
        if len(_IND_CACHE) >= _IND_CACHE_MAX:
            _IND_CACHE.pop(next(iter(_IND_CACHE)))
        _IND_CACHE[cache_key] = list(out)
    return out


def bull_market_support_band(df: pd.DataFrame, weekly: pd.DataFrame) -> list[IndicatorSeries]:
    """Bull Market Support Band (segnalazione 893ea67a): SMA 20 and EMA 21 of
    the weekly close, drawn on any chart timeframe.

    Each chart candle sees the week it falls in as still forming, with its own
    close as that week's close so far: what TradingView shows live, and what
    the candle could actually know. Taking the weekly bar's final close
    instead painted every past day with a value from days later. Candles
    before 19 completed weeks get nothing."""
    if weekly is None or weekly.empty or df.empty:
        return []
    wclose = weekly["close"].astype(float)
    if not (wclose.index.is_monotonic_increasing and df.index.is_monotonic_increasing):
        return []
    try:
        # Position of the week each chart candle falls in.
        pos = wclose.index.searchsorted(df.index, side="right") - 1
    except (TypeError, ValueError):   # an index the other can't be compared to: no band
        return []
    alpha = 2 / 22
    ema = wclose.ewm(span=21, adjust=False).mean().to_numpy()
    sums = wclose.rolling(19).sum().to_numpy()          # 19 weeks before the current one
    close = df["close"].astype(float).to_numpy()
    sma_vals: list[float | None] = []
    ema_vals: list[float | None] = []
    for k, p in enumerate(pos):
        if p < 19:   # fewer than 19 completed weeks before this one
            sma_vals.append(None)
            ema_vals.append(None)
            continue
        c = close[k]
        sma_vals.append(float((sums[p - 1] + c) / 20))
        ema_vals.append(float(ema[p - 1] * (1 - alpha) + c * alpha))
    out = []
    for name, vals in (("BMSB_SMA20W", sma_vals), ("BMSB_EMA21W", ema_vals)):
        if any(v is not None for v in vals):
            out.append(IndicatorSeries(name=name, values=vals))
    return out
