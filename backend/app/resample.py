import numpy as np
import pandas as pd


def resample_by_count(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Aggregate every n consecutive candles into one, used for interval
    choices no provider natively supports (2D/3D/5D synthesized from 1D).

    Groups are counted from the newest row backwards so the most recent
    synthetic candle is always a complete group as of now — any leftover
    partial group lands at the oldest end of the history instead of leaving
    today's candle incomplete.
    """
    if n <= 1 or df.empty:
        return df
    ascending = df.sort_index()
    m = len(ascending)
    group = np.arange(m)[::-1] // n
    tmp = ascending.copy()
    tmp["_grp"] = group
    grouped = tmp.groupby("_grp", sort=False)
    result = pd.DataFrame({
        "open": grouped["open"].apply(lambda s: s.iloc[0]),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].apply(lambda s: s.iloc[-1]),
        "volume": grouped["volume"].sum(),
    })
    result.index = grouped.apply(lambda g: g.index[0])
    return result.sort_index()
