import pandas as pd
import pandas_ta  # noqa: F401  (registers the .ta accessor on DataFrame)

from app.models import IndicatorSeries


def _series_to_values(s: pd.Series) -> list[float | None]:
    return [None if pd.isna(v) else float(v) for v in s]


def _first_col(df: pd.DataFrame | None, prefix: str) -> pd.Series | None:
    if df is None:
        return None
    col = next((c for c in df.columns if c.startswith(prefix)), None)
    return df[col] if col is not None else None


def compute_indicators(df: pd.DataFrame) -> list[IndicatorSeries]:
    out: list[IndicatorSeries] = []

    ema20 = df.ta.ema(length=20)
    ema50 = df.ta.ema(length=50)
    rsi14 = df.ta.rsi(length=14)
    macd = df.ta.macd()
    bbands = df.ta.bbands(length=20)
    vwap = df.ta.vwap()
    stoch = df.ta.stoch(k=14, d=3, smooth_k=3)

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

    return out
