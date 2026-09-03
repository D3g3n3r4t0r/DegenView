import time
from typing import Literal

import pandas as pd

# TradingView-style granularity choices. 2d/3d/5d have no native support from
# either provider (Twelve Data or the crypto exchanges) — they're synthesized
# by resampling native "1d" candles (see app.resample.resample_by_count).
IntervalChoice = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d", "2d", "3d", "5d", "1w", "1M"]
CANONICAL_INTERVALS: tuple[IntervalChoice, ...] = (
    "1m", "5m", "15m", "30m", "1h", "4h", "1d", "2d", "3d", "5d", "1w", "1M",
)

# interval -> how many native daily candles get folded into one synthetic candle.
SYNTHETIC_DAY_INTERVALS: dict[str, int] = {"2d": 2, "3d": 3, "5d": 5}

DEFAULT_INTERVALS: dict[str, IntervalChoice] = {"htf": "1d", "mtf": "1h", "ltf": "15m"}

# interval -> duration in seconds, used to tell whether the most recent
# candle a provider returned has actually closed yet or is still forming.
# "1M" has no fixed length (28-31 days) — approximated as 30 days, which is
# precise enough for a "has this bar closed" check on a monthly timeframe.
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "2d": 2 * 86400,
    "3d": 3 * 86400,
    "5d": 5 * 86400,
    "1w": 7 * 86400,
    "1M": 30 * 86400,
}


def drop_unclosed_candle(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Anything that treats a candle as a confirmed data point — an alert
    condition, a swing pivot — must not anchor on the still-forming last
    bar: on a weekly/monthly timeframe especially, that bar's high/low can
    still be far from final days into the week, so a "swing" pinned to it
    is really just today's intraweek wiggle, not confirmed structure, and
    will keep sliding around until the bar actually closes. Drops the last
    row whenever its open time + the interval's duration is still in the
    future."""
    if df.empty:
        return df
    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        return df
    last_open = df.index[-1].timestamp()
    if last_open + seconds > time.time():
        return df.iloc[:-1]
    return df
