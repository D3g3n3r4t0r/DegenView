import pandas as pd

from app.models import StrategySignal, StrategyState

# Direct port of the user's Pine Script v4 "Lorenzo" trend-follower strategy:
# entries/exits are driven by the slope of a moving average (EMA of the MA's
# rate of change), gated by an optional trend filter and volatility filter.
DEFAULT_PARAMS = {
    "average": "EMA",
    "len": 130,
    "slopeFlen": 7,
    "slopeSlen": 27,
    "trendfilter": True,
    "trendfilterperiod": 268,
    "trendfiltertype": "EMA",
    "volatilityfilter": True,
    "volatilitystdevlength": 16,
    "volatilitystdevmalength": 44,
}

_MAX_ALERTS_RETURNED = 30

# Registry of pluggable strategies — one entry today, built so a future
# "exhaustion/reversal" strategy just adds a name here without UI changes.
AVAILABLE_STRATEGIES = ["Lorenzo (trend-follower)"]
DEFAULT_STRATEGY = AVAILABLE_STRATEGIES[0]


def _ma(series: pd.Series, length: int, kind: str) -> pd.Series:
    if kind == "EMA":
        return series.ewm(span=length, adjust=False).mean()
    return series.rolling(length).mean()


def compute_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    close = df["close"]

    out = _ma(close, p["len"], p["average"])
    slope = out.diff() / out

    ema_slope_fast = slope.ewm(span=p["slopeFlen"], adjust=False).mean()
    ema_slope_slow = slope.ewm(span=p["slopeSlen"], adjust=False).mean()

    trend_ma = _ma(close, p["trendfilterperiod"], p["trendfiltertype"])
    trend_condition_long = close > trend_ma
    trend_condition_short = close < trend_ma

    # Pine's stdev() is a population (biased) standard deviation, ddof=0.
    vol_std = close.rolling(p["volatilitystdevlength"]).std(ddof=0)
    vol_ma = vol_std.rolling(p["volatilitystdevmalength"]).mean()
    volatility_condition = vol_std > vol_ma

    base_long = ema_slope_fast > ema_slope_slow
    base_short = ema_slope_fast < ema_slope_slow

    entry_long, entry_short = base_long, base_short
    if p["trendfilter"]:
        entry_long = entry_long & trend_condition_long
        entry_short = entry_short & trend_condition_short
    if p["volatilityfilter"]:
        entry_long = entry_long & volatility_condition
        entry_short = entry_short & volatility_condition

    crossunder = (ema_slope_fast.shift(1) >= ema_slope_slow.shift(1)) & (ema_slope_fast < ema_slope_slow)
    crossover = (ema_slope_fast.shift(1) <= ema_slope_slow.shift(1)) & (ema_slope_fast > ema_slope_slow)

    return pd.DataFrame(
        {
            "entry_long": entry_long.fillna(False),
            "entry_short": entry_short.fillna(False),
            "exit_long": crossunder.fillna(False),
            "exit_short": crossover.fillna(False),
        },
        index=df.index,
    )


_LABELS = {
    "entry_long": "Ingresso long rilevato",
    "entry_short": "Ingresso short rilevato",
    "exit_long": "Uscita long rilevata (inversione pendenza)",
    "exit_short": "Uscita short rilevata (inversione pendenza)",
    "flip_to_long": "Inversione: chiusura short e apertura long",
    "flip_to_short": "Inversione: chiusura long e apertura short",
}


def confirmed_events(df: pd.DataFrame, params: dict | None = None) -> tuple[list[StrategySignal], int]:
    """All confirmed position-transition events for the full window (uncapped —
    used for backtesting), plus the resulting final position (1/0/-1).

    The most recent candle is still forming — its close (and therefore any
    signal computed on it) keeps changing between fetches. Alerting on it
    would fire, vanish, and re-fire as the price moves, spamming the same
    timestamp. We still fold it into the returned position for a live-ish
    badge, but never emit it as a confirmed event.
    """
    signals = compute_signals(df, params)
    last_confirmed_ts = df.index[-2] if len(df) > 1 else None

    position = 0  # 0 flat, 1 long, -1 short
    events: list[StrategySignal] = []

    for ts, row in signals.iterrows():
        prev_position = position
        if position == 1 and row["exit_long"]:
            position = 0
        elif position == -1 and row["exit_short"]:
            position = 0
        if row["entry_long"]:
            position = 1
        elif row["entry_short"]:
            position = -1

        if position == prev_position:
            continue
        if last_confirmed_ts is not None and ts > last_confirmed_ts:
            continue  # transition happened on the still-forming candle; not confirmed yet

        if prev_position == 0 and position == 1:
            signal_type = "entry_long"
        elif prev_position == 0 and position == -1:
            signal_type = "entry_short"
        elif prev_position == 1 and position == 0:
            signal_type = "exit_long"
        elif prev_position == -1 and position == 0:
            signal_type = "exit_short"
        elif prev_position == 1 and position == -1:
            signal_type = "flip_to_short"
        else:
            signal_type = "flip_to_long"

        events.append(
            StrategySignal(
                time=int(ts.timestamp()),
                type=signal_type,
                price=float(df.loc[ts, "close"]),
                label=_LABELS[signal_type],
            )
        )

    return events, position


def build_strategy_state(name: str, df: pd.DataFrame, params: dict | None = None) -> StrategyState:
    events, position = confirmed_events(df, params)
    position_label = {1: "long", -1: "short", 0: "flat"}[position]
    return StrategyState(name=name, position=position_label, signals=events[-_MAX_ALERTS_RETURNED:])
