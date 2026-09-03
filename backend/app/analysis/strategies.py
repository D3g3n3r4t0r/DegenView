import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401  (registers the .ta accessor on DataFrame)
from smartmoneyconcepts import smc

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

# Contrarian counterpart to Lorenzo: instead of riding a trend, it looks for
# the point selling (or buying) pressure exhausts itself. Two distinct real
# patterns both count as "exhaustion" and both get caught here:
#   - Capitulation: a sharp new low on a volume climax, RSI still oversold —
#     the classic panic V-bottom.
#   - Accumulation/basing: price re-tests a prior swing low at roughly the
#     SAME level (not a new low) on much *lower* volume while RSI is clearly
#     higher than it was at that prior low — sellers have stopped pressing,
#     a Wyckoff-style spring/re-test rather than a spike. Comparing against
#     the lowest of the last few swings (not just the immediately preceding
#     one) is what lets a multi-touch range register instead of only the
#     single sharpest capitulation candle.
# Swing points reuse the same smartmoneyconcepts detection already powering
# the SMC overlays, so the "evident sign on the price chart" is the same
# swing structure a trader would circle by hand.
EXHAUSTION_DEFAULT_PARAMS = {
    "swing_length": 8,
    "rsi_length": 14,
    "rsi_oversold": 40,
    "rsi_overbought": 60,
    "rsi_min_gap": 3.0,
    "low_tolerance_pct": 1.0,
    "divergence_lookback": 3,
    "volume_ma_length": 20,
    "volume_multiplier": 1.3,
    "trend_filter": True,
    "trend_ema_length": 50,
    "confirmation_lookahead": 10,
    # Swing-divergence needs two *confirmed* swings (swing_length bars settled
    # on each side), so it structurally can't fire inside a range that formed
    # only in the last handful of candles — exactly the freshest, tightest
    # accumulation zones. This second, independent condition catches those:
    # realized volatility collapsing after a decline (the sharp move has
    # stopped, price is coiling) plus a breakout back through the range.
    "contraction_lookback": 10,
    "contraction_prior_lookback": 30,
    "contraction_ratio": 0.55,
    # A long grinding range has neither a volume climax nor unusually quiet
    # volume at any single touch — it's just unremarkable chop — so it can
    # satisfy neither condition above. This buys the range's own lower
    # quartile directly on an oversold reaction candle.
    "range_lookback": 40,
    "range_zone_pct": 0.25,
    # These three entry conditions were added reactively in one sitting,
    # each while looking at a chart where the previous ones didn't fire —
    # a textbook overfitting pattern. Exposing them as independent on/off
    # switches (rather than baking the OR together silently) lets a user
    # who wants only the most conservative signal (divergence) turn the
    # other two off instead of trusting all three blindly.
    "enable_divergence": True,
    "enable_contraction": True,
    "enable_range_bounce": True,
}

_MAX_ALERTS_RETURNED = 10_000  # effectively uncapped — ltf_candles is the real ceiling


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


def _find_confirmation(
    df: pd.DataFrame,
    swing_pos: int,
    direction: str,
    max_lookahead: int,
    swing_length: int = 0,
) -> int | None:
    """First bar after the swing point whose close actually breaks back
    through the swing bar's high/low — the follow-through that turns a
    divergence into a real signal instead of a mid-formation guess.

    The scan starts `swing_length` bars after the swing, not one, and that
    offset is the difference between a backtest and a fantasy. smc's swing
    detection uses a centred window: a swing at P is only identifiable once
    `swing_length` further bars exist — measured on KASUSDT across 16 swings by
    finding the first moment the swing appears and never disappears again, the
    delay was 8 every single time, exactly swing_length.

    Starting at swing_pos + 1 therefore confirmed against a swing that, at that
    moment, nobody could yet know was a swing. Of 87 confirmed signals, 84 (97%)
    fired inside that blind window, at a median of 2 bars. The backtest opened
    those trades; a live bot could not have, because the signal did not exist
    yet. Waiting the detection delay costs entry price and removes signals — and
    buys back the only property that makes a backtest worth reading.
    """
    n = len(df)
    start = swing_pos + max(1, swing_length)
    end = min(n, start + max_lookahead)
    if direction == "long":
        level = df["high"].iloc[swing_pos]
        for pos in range(start, end):
            if df["close"].iloc[pos] > level:
                return pos
    else:
        level = df["low"].iloc[swing_pos]
        for pos in range(start, end):
            if df["close"].iloc[pos] < level:
                return pos
    return None


def _reference_swing(positions: list[int], i: int, lookback: int, values, pick: str) -> int:
    """Among the `lookback` swings before index i, return the position holding
    the min (pick="low") or max (pick="high") value — the range's own
    established extreme, not just whatever the immediately preceding swing
    happened to be. That's what lets a multi-touch accumulation range register
    instead of only a single sharp capitulation candle."""
    window = positions[max(0, i - lookback) : i]
    if pick == "low":
        return min(window, key=lambda pos: values.iloc[pos])
    return max(window, key=lambda pos: values.iloc[pos])


def compute_exhaustion_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Contrarian reversal strategy: fires when momentum (RSI) diverges from
    price at a swing extreme relative to the range's established low/high —
    either a sharp capitulation (new low, volume climax) or a quiet
    accumulation re-test (roughly the same low, below-average volume, RSI
    clearly firmer) — gated by an optional prior-trend filter and confirmed
    only once price actually closes back through the swing bar's level.
    """
    p = {**EXHAUSTION_DEFAULT_PARAMS, **(params or {})}
    close = df["close"]
    tolerance = p["low_tolerance_pct"] / 100

    rsi = df.ta.rsi(length=p["rsi_length"])
    # pandas_ta silently returns the input DataFrame unchanged (not a
    # NaN-filled Series) when there's too little history for the requested
    # length — treat that as "no RSI available" rather than let it corrupt
    # every downstream comparison.
    if not isinstance(rsi, pd.Series) or len(rsi) != len(df):
        rsi = pd.Series(float("nan"), index=df.index)
    vol_ma = df["volume"].rolling(p["volume_ma_length"]).mean()
    trend_ema = close.ewm(span=p["trend_ema_length"], adjust=False).mean()

    swings = smc.swing_highs_lows(df, swing_length=p["swing_length"])
    swing_lows = swings[swings["HighLow"] == -1]
    swing_highs = swings[swings["HighLow"] == 1]

    entry_long = pd.Series(False, index=df.index)
    entry_short = pd.Series(False, index=df.index)

    trend_ok_long = (close < trend_ema) if p["trend_filter"] else pd.Series(True, index=df.index)
    trend_ok_short = (close > trend_ema) if p["trend_filter"] else pd.Series(True, index=df.index)

    if p["enable_divergence"]:
        low_positions = swing_lows.index.to_list()
        for i in range(1, len(low_positions)):
            cur_pos = int(low_positions[i])
            ref_pos = _reference_swing(low_positions, i, p["divergence_lookback"], df["low"], "low")
            cur_rsi, ref_rsi = rsi.iloc[cur_pos], rsi.iloc[ref_pos]
            cur_vol_ma = vol_ma.iloc[cur_pos]
            if pd.isna(cur_rsi) or pd.isna(ref_rsi) or pd.isna(cur_vol_ma):
                continue
            not_a_higher_low = df["low"].iloc[cur_pos] <= df["low"].iloc[ref_pos] * (1 + tolerance)
            bullish_divergence = not_a_higher_low and cur_rsi > ref_rsi + p["rsi_min_gap"]
            oversold = cur_rsi < p["rsi_oversold"]
            volume_climax = df["volume"].iloc[cur_pos] > cur_vol_ma * p["volume_multiplier"]
            volume_quiet = df["volume"].iloc[cur_pos] < cur_vol_ma / p["volume_multiplier"]
            trend_ok = (not p["trend_filter"]) or (close.iloc[cur_pos] < trend_ema.iloc[cur_pos])
            if bullish_divergence and oversold and (volume_climax or volume_quiet) and trend_ok:
                confirm_pos = _find_confirmation(df, cur_pos, "long", p["confirmation_lookahead"], p["swing_length"])
                if confirm_pos is not None:
                    entry_long.iloc[confirm_pos] = True

        high_positions = swing_highs.index.to_list()
        for i in range(1, len(high_positions)):
            cur_pos = int(high_positions[i])
            ref_pos = _reference_swing(high_positions, i, p["divergence_lookback"], df["high"], "high")
            cur_rsi, ref_rsi = rsi.iloc[cur_pos], rsi.iloc[ref_pos]
            cur_vol_ma = vol_ma.iloc[cur_pos]
            if pd.isna(cur_rsi) or pd.isna(ref_rsi) or pd.isna(cur_vol_ma):
                continue
            not_a_lower_high = df["high"].iloc[cur_pos] >= df["high"].iloc[ref_pos] * (1 - tolerance)
            bearish_divergence = not_a_lower_high and cur_rsi < ref_rsi - p["rsi_min_gap"]
            overbought = cur_rsi > p["rsi_overbought"]
            volume_climax = df["volume"].iloc[cur_pos] > cur_vol_ma * p["volume_multiplier"]
            volume_quiet = df["volume"].iloc[cur_pos] < cur_vol_ma / p["volume_multiplier"]
            trend_ok = (not p["trend_filter"]) or (close.iloc[cur_pos] > trend_ema.iloc[cur_pos])
            if bearish_divergence and overbought and (volume_climax or volume_quiet) and trend_ok:
                confirm_pos = _find_confirmation(df, cur_pos, "short", p["confirmation_lookahead"], p["swing_length"])
                if confirm_pos is not None:
                    entry_short.iloc[confirm_pos] = True

    if p["enable_contraction"]:
        # Volatility-contraction breakout — independent of confirmed swings,
        # so it can fire inside a range that only just formed.
        recent_std = close.rolling(p["contraction_lookback"]).std()
        prior_std = close.rolling(p["contraction_prior_lookback"]).std().shift(p["contraction_lookback"])
        contracted = recent_std < prior_std * p["contraction_ratio"]
        was_oversold_recently = rsi.rolling(p["contraction_lookback"]).min() < p["rsi_oversold"]
        was_overbought_recently = rsi.rolling(p["contraction_lookback"]).max() > p["rsi_overbought"]
        range_high = df["high"].rolling(p["contraction_lookback"]).max().shift(1)
        range_low = df["low"].rolling(p["contraction_lookback"]).min().shift(1)
        # A mere tick above the range is noise; require a real break plus
        # renewed volume on the breakout bar itself — without it this fires
        # on every minor chop and drags win rate down.
        breakout_long = close > range_high * 1.003
        breakout_short = close < range_low * 0.997
        volume_confirms = df["volume"] > vol_ma

        entry_long_contraction = (
            contracted & was_oversold_recently & (rsi > p["rsi_oversold"]) & breakout_long & volume_confirms & trend_ok_long
        )
        entry_short_contraction = (
            contracted & was_overbought_recently & (rsi < p["rsi_overbought"]) & breakout_short & volume_confirms & trend_ok_short
        )
        entry_long = entry_long | entry_long_contraction.fillna(False)
        entry_short = entry_short | entry_short_contraction.fillna(False)

    if p["enable_range_bounce"]:
        # Range-support bounce — a long, grinding sideways range (many small
        # touches, no volume climax and no real quiet-volume either, since
        # it's just unremarkable chop) satisfies neither condition above.
        # This buys the range's own lower quartile directly on an oversold
        # reaction candle, which is what "buy the lows of this range" means.
        range_est_high = df["high"].rolling(p["range_lookback"]).max()
        range_est_low = df["low"].rolling(p["range_lookback"]).min()
        range_width = range_est_high - range_est_low
        in_lower_zone = close <= range_est_low + range_width * p["range_zone_pct"]
        in_upper_zone = close >= range_est_high - range_width * p["range_zone_pct"]
        bullish_reaction = close > df["open"]
        bearish_reaction = close < df["open"]

        entry_long_range = in_lower_zone & (rsi < p["rsi_oversold"]) & bullish_reaction & trend_ok_long
        entry_short_range = in_upper_zone & (rsi > p["rsi_overbought"]) & bearish_reaction & trend_ok_short
        entry_long = entry_long | entry_long_range.fillna(False)
        entry_short = entry_short | entry_short_range.fillna(False)

    # This reads as an accumulation/distribution indicator for long-horizon
    # positions, not a scalp: an RSI-recovery exit would close the trade
    # within days of an entry meant to be held through a slow re-accumulation
    # base. Flip out only when the opposite exhaustion condition appears —
    # i.e. hold the long until distribution (buying exhaustion) shows up.
    exit_long = entry_short
    exit_short = entry_long

    return pd.DataFrame(
        {
            "entry_long": entry_long.fillna(False),
            "entry_short": entry_short.fillna(False),
            "exit_long": exit_long.fillna(False),
            "exit_short": exit_short.fillna(False),
        },
        index=df.index,
    )


def _wilder_rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1 / length, adjust=False).mean()


# RSI + Bollinger Bands mean-reversion, ported from a Pine Script v4
# indicator the user calls "LKI Trading" — supplied as two separate scripts
# (one for the long alert, one for the short alert), combined here into one.
# Despite the name, the "short" alert was never meant to open a short
# position — Gabriele's own strategy is long-only (buy oversold, sell the
# overbought reaction): the second alert just closes the long. So it maps to
# exit_long here, not entry_short — there is no entry_short/exit_short at all.
LKI_DEFAULT_PARAMS = {
    "rsi_length": 14,
    "bb_length": 20,
    "bb_mult": 2.0,
    "rsi_oversold": 28,
    "rsi_overbought": 72,
}


def compute_lki_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {**LKI_DEFAULT_PARAMS, **(params or {})}
    close = df["close"]

    # Matches Pine's rsi() exactly, including its edge-case ternary:
    # down==0 -> 100, up==0 (and down!=0) -> 0, else the usual formula.
    delta = close.diff()
    avg_gain = _wilder_rma(delta.clip(lower=0), p["rsi_length"])
    avg_loss = _wilder_rma(-delta.clip(upper=0), p["rsi_length"])
    avg_loss_safe = avg_loss.replace(0, np.nan)
    raw_rsi = 100 - (100 / (1 + avg_gain / avg_loss_safe))
    rsi = pd.Series(
        np.where(avg_loss == 0, 100.0, np.where(avg_gain == 0, 0.0, raw_rsi)),
        index=df.index,
    )

    # Pine's stdev() is a population (biased) standard deviation, ddof=0 —
    # same convention already used by the Lorenzo strategy above.
    basis = close.rolling(p["bb_length"]).mean()
    dev = p["bb_mult"] * close.rolling(p["bb_length"]).std(ddof=0)
    upper = basis + dev
    lower = basis - dev

    entry_long = (rsi < p["rsi_oversold"]) & (close < lower)
    exit_long = (rsi > p["rsi_overbought"]) & (close > upper)

    return pd.DataFrame(
        {
            "entry_long": entry_long.fillna(False),
            "entry_short": pd.Series(False, index=df.index),
            "exit_long": exit_long.fillna(False),
            "exit_short": pd.Series(False, index=df.index),
        },
        index=df.index,
    )


# Registry of pluggable strategies — dispatch used by confirmed_events()
# whenever a caller passes a strategy name instead of pre-computed signals.
STRATEGY_REGISTRY = {
    "Lorenzo (trend-follower)": compute_signals,
    "Accumulo / Distribuzione (long-term)": compute_exhaustion_signals,
    "Gabriele (RSI+BB reversal)": compute_lki_signals,
}
AVAILABLE_STRATEGIES = list(STRATEGY_REGISTRY.keys())
DEFAULT_STRATEGY = AVAILABLE_STRATEGIES[0]


_LABELS = {
    "entry_long": "Ingresso long rilevato",
    "entry_short": "Ingresso short rilevato",
    "exit_long": "Uscita long rilevata",
    "exit_short": "Uscita short rilevata",
    "flip_to_long": "Inversione: chiusura short e apertura long",
    "flip_to_short": "Inversione: chiusura long e apertura short",
}


def confirmed_events(
    df: pd.DataFrame,
    params: dict | None = None,
    signals: pd.DataFrame | None = None,
    strategy_name: str = DEFAULT_STRATEGY,
) -> tuple[list[StrategySignal], int]:
    """All confirmed position-transition events for the full window (uncapped —
    used for backtesting), plus the resulting final position (1/0/-1).

    The most recent candle is still forming — its close (and therefore any
    signal computed on it) keeps changing between fetches. Alerting on it
    would fire, vanish, and re-fire as the price moves, spamming the same
    timestamp. We still fold it into the returned position for a live-ish
    badge, but never emit it as a confirmed event.

    `signals` lets callers (e.g. the Pine Script engine) inject an
    already-computed entry_long/entry_short/exit_long/exit_short frame
    instead of dispatching to a registered strategy by name.
    """
    if signals is None:
        compute_fn = STRATEGY_REGISTRY.get(strategy_name, compute_signals)
        signals = compute_fn(df, params)
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


def build_strategy_state(
    name: str, df: pd.DataFrame, params: dict | None = None, signals: pd.DataFrame | None = None
) -> StrategyState:
    events, position = confirmed_events(df, params, signals=signals, strategy_name=name)
    position_label = {1: "long", -1: "short", 0: "flat"}[position]
    return StrategyState(name=name, position=position_label, signals=events[-_MAX_ALERTS_RETURNED:])
