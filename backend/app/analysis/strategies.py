import time

import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401  (registers the .ta accessor on DataFrame)
from smartmoneyconcepts import smc

from app.analysis import btc_regime
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
    # Quanta pendenza serve perche' conti come direzione, misurata in deviazioni
    # standard della pendenza stessa.
    #
    # Lorenzo e' un incrocio puro: due medie della pendenza si incrociano e si
    # entra, qualunque sia l'ampiezza del movimento. Su una coppia liquida con
    # un trend vero e' ragionevole; su una altcoin che oscilla del 15% al giorno
    # senza andare da nessuna parte, gli incroci arrivano dal rumore e la
    # strategia entra ed esce su oscillazioni che non sono direzione.
    #
    # La soglia e' in unita' di sigma e non in valore assoluto perche' deve
    # significare la stessa cosa su ogni coppia: 0.002 di pendenza e' enorme su
    # una coppia che fa lo 0.5% al giorno e invisibile su una che ne fa il 15%.
    #
    # Zero di default, cioe' spenta: accenderla cambia tutti i risultati
    # storici, e quel cambiamento va chiesto, non subito.
    "slope_threshold_sigma": 0.0,
    "slope_sigma_length": 100,
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

    # Freno sul rumore: la pendenza deve superare k volte la propria deviazione
    # standard recente. Normalizzata sulla pendenza stessa e non sul prezzo,
    # cosi' la stessa k vale su qualsiasi coppia. A zero non tocca niente — e
    # non e' solo una soglia inefficace, e' proprio il ramo che non viene
    # eseguito, quindi i risultati restano identici bit per bit.
    k = float(p.get("slope_threshold_sigma", 0.0) or 0.0)
    if k > 0:
        slope_sigma = slope.rolling(int(p.get("slope_sigma_length", 100))).std(ddof=0)
        strong = (ema_slope_fast.abs() > k * slope_sigma).fillna(False)
        base_long = base_long & strong
        base_short = base_short & strong

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


# Lorenzo on minute candles of young on-chain tokens. Lorenzo asked for "la
# logica di quella di Lorenzo applicata ad un time frame sui minuti, con dei
# filtri diversi", trend-following only.
#
# The core is unchanged: slope of a moving average, fast/slow EMA of that
# slope, long while fast > slow, out at the crossunder. What changes is
# everything the daily version takes for granted:
#   - a 268-bar trend EMA does not exist on a token that is a few hours old.
#     The trend filter becomes the VWAP anchored at the first candle: price
#     above it means the average buyer since launch is in profit;
#   - minute returns on young DEX pools are mostly anti-persistent (variance
#     ratio < 1 on ~80% of 98 pools measured in Sept 2026): a rise is more
#     often given back than extended, and a trend-follower there pays the
#     ~1.6% DEX round trip on every fake move. The regime gate replaces the
#     volatility filter: enter only while the token's own rolling variance
#     ratio says moves are persisting. On that sample it was the one filter
#     that mattered (mean per pool -20% -> ~0 before the others);
#   - Kaufman's efficiency ratio keeps only moves that go somewhere, and the
#     slope threshold in sigma (measured to pay on agitated pairs) is on;
#   - a pump can give back everything in two candles, well before the slope
#     EMAs cross. A trailing stop in ATR multiples closes the trade first, and
#     after any exit a fresh crossover is needed before buying again, so one
#     trend is never paid for twice. It cannot help against a single-candle
#     rug: the fill is the next open, wherever that is.
# The volume burst filter is there but off: on the same sample it did not
# add anything once the regime gate was on.
# Long only: on-chain spot cannot go short.
LORENZO_HF_DEFAULT_PARAMS = {
    "len": 30,
    "slopeFlen": 4,
    "slopeSlen": 14,
    "slope_threshold_sigma": 0.5,
    "slope_sigma_length": 60,
    "vwap_filter": True,
    "volume_len": 30,
    "volume_mult": 0.0,
    "er_len": 10,
    "er_min": 0.5,
    "vr_len": 60,
    "vr_min": 1.0,
    "atr_len": 14,
    "trail_atr": 4.0,
}


# Lorenzo HF is meant for pools a few minutes old: its filters work on the
# history there is, from HF_MIN_BARS candles on, instead of waiting for their
# full windows (the variance ratio wanted 60 five-minute bars, 5 hours).
# Lorenzo, 28/09: "quando parte l'alert voglio che la strategia sia subito
# operativa [...] deve entrare con i criteri della strategia, sempre". On
# fresh pools it was blind for hours: 0 entries out of 20 synthetic pumps
# starting at the alert, against 20/20 on older pools.
HF_MIN_BARS = 10


def compute_lorenzo_hf_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {**LORENZO_HF_DEFAULT_PARAMS, **(params or {})}
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    ma = close.ewm(span=int(p["len"]), adjust=False).mean()
    slope = ma.diff() / ma
    fast = slope.ewm(span=int(p["slopeFlen"]), adjust=False).mean()
    slow = slope.ewm(span=int(p["slopeSlen"]), adjust=False).mean()
    crossover = (fast.shift(1) <= slow.shift(1)) & (fast > slow)
    crossunder = (fast.shift(1) >= slow.shift(1)) & (fast < slow)

    ok = fast > slow
    k = float(p["slope_threshold_sigma"] or 0.0)
    if k > 0:
        sigma = slope.rolling(int(p["slope_sigma_length"]), min_periods=min(int(p["slopeSlen"]), HF_MIN_BARS)).std(ddof=0)
        ok &= fast > k * sigma
    if p["vwap_filter"]:
        typical = (high + low + close) / 3
        cum_vol = volume.cumsum()
        vwap = (typical * volume).cumsum() / cum_vol.where(cum_vol > 0)
        ok &= close > vwap.fillna(typical.expanding().mean())
    if p["volume_mult"] and p["volume_mult"] > 0:
        n = int(p["volume_len"])
        ref = volume.shift(1).rolling(n, min_periods=max(3, n // 3)).median()
        burst = volume.rolling(3, min_periods=1).max() >= p["volume_mult"] * ref
        ok &= burst & (ref > 0)
    if p["er_min"] and p["er_min"] > 0:
        n = int(p["er_len"])
        path = close.diff().abs().rolling(n).sum()
        ok &= (close - close.shift(n)) / path.where(path > 0) >= p["er_min"]
    if p["vr_min"] and p["vr_min"] > 0:
        n, q = int(p["vr_len"]), 4
        log_c = np.log(close.where(close > 0))
        var_1 = log_c.diff().rolling(n, min_periods=min(n, HF_MIN_BARS)).var()
        var_q = log_c.diff(q).rolling(n, min_periods=min(n, HF_MIN_BARS)).var()
        ok &= var_q / (q * var_1.where(var_1 > 0)) >= p["vr_min"]

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder_rma(tr, int(p["atr_len"])).to_numpy()

    # Stateful on purpose: the trailing stop needs the high since entry, and
    # confirmed_events re-enters on any bar where entry_long is true — so this
    # emits edges only, never an entry and an exit on the same bar.
    ok_a = ok.fillna(False).to_numpy()
    xo, xu = crossover.fillna(False).to_numpy(), crossunder.fillna(False).to_numpy()
    close_a, high_a = close.to_numpy(), high.to_numpy()
    trail = float(p["trail_atr"] or 0.0)
    warmup = min(int(p["slopeSlen"]), HF_MIN_BARS)
    n_bars = len(df)
    entry = np.zeros(n_bars, dtype=bool)
    exit_ = np.zeros(n_bars, dtype=bool)
    in_pos, armed, peak = False, True, 0.0
    for i in range(warmup, n_bars):
        if in_pos:
            peak = max(peak, high_a[i])
            stopped = trail > 0 and np.isfinite(atr[i]) and close_a[i] < peak - trail * atr[i]
            if xu[i] or stopped:
                exit_[i] = True
                in_pos, armed = False, False
            continue
        if xo[i]:
            armed = True
        if armed and ok_a[i]:
            entry[i] = True
            in_pos, peak = True, high_a[i]

    false = pd.Series(False, index=df.index)
    return pd.DataFrame(
        {
            "entry_long": pd.Series(entry, index=df.index),
            "entry_short": false,
            "exit_long": pd.Series(exit_, index=df.index),
            "exit_short": false,
        },
        index=df.index,
    )


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
    # None = "not set": the strategy's own default stays (bb_mult is None in
    # the shared query model, so RSI+BB 4H keeps its 2.5).
    p = {**LKI_DEFAULT_PARAMS, **{k: v for k, v in (params or {}).items() if v is not None}}
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


# Stessa logica, simmetrica: la reazione di ipercomprato sulla banda superiore
# apre uno short invece di limitarsi a chiudere il long. E' la variante chiesta
# per i futures, dove si puo' stare corti davvero.
#
# Tenuta separata dall'originale invece di aggiungerle un'opzione: la strategia
# di sopra e' quella che gira sugli alert attivi, e cambiarne il comportamento
# in base a un parametro avrebbe cambiato i risultati storici di chi la usa gia'.
# Qui i parametri sono gli stessi, quindi una configurazione trovata per l'una
# si porta sull'altra e le due si confrontano sugli stessi assi.
LKI2_DEFAULT_PARAMS = dict(LKI_DEFAULT_PARAMS)

# RSI+BB 4H (Lorenzo, 13/10): the long-only RSI+BB, same rules, with the
# Bollinger multiplier at 2.5 by default — a 4h candle's 2-sigma band is
# touched too often to mean an extreme.
RSI_BB_4H = "RSI+BB 4H"
LKI4H_DEFAULT_PARAMS = {**LKI_DEFAULT_PARAMS, "bb_mult": 2.5}


def compute_lki4h_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    return compute_lki_signals(df, {**LKI4H_DEFAULT_PARAMS,
                                    **{k: v for k, v in (params or {}).items() if v is not None}})


# ── Claudio 4H ──────────────────────────────────────────────────────────────
# Lorenzo, 15/10: "sviluppare una strategia 'Claudio' tutta tua adatta al
# timeframe 4H [...] massimo profitto e stabilita' da applicare anche su
# candele mai viste". A controlled rebound, long only, built on what this
# site measured:
#   * RSI+BB buys falling knives in strong downtrends → regime filter: enter
#     only while the market is ranging (Kaufman efficiency ratio low) or the
#     price is above its long average;
#   * it buys while the price is still falling → wait for the first candle
#     that closes above the previous one's high after the oversold close
#     under the lower band;
#   * it exits only on overbought, which may never come → the first of:
#     back to the band's middle (the rebound's natural target), a stop at a
#     multiple of the ATR measured at entry, a time stop;
#   * more free parameters did worse out of sample → three are searched
#     (oversold level, band width, stop distance), the rest are fixed.
# Everything uses closed candles only: no information from the future.
CLAUDIO_4H = "Claudio 4H"
CLAUDIO_DEFAULT_PARAMS = {
    "cl_rsi_os": 30,          # searched: RSI under this on the setup candle
    "cl_bb_mult": 2.2,        # searched: band width (20-candle Bollinger)
    "cl_atr_stop": 2.5,       # searched: stop = entry close - this × ATR(14)
    "cl_er_max": 0.30,        # fixed: efficiency ratio (20) at or below = ranging
    "cl_ema_len": 200,        # fixed: long average (~33 days of 4h)
    "cl_time_stop": 30,       # fixed: candles in a trade at most (~5 days)
    # v2 (15/10, after the fold test: the exit at the middle band capped every
    # winner while the stop took the full losses, net ~0): 1 = exit at the
    # upper band instead of the middle one, and the stop trails the close by
    # the same k × ATR. 0 = the original rules.
    "cl_exit_upper": 0,
    "cl_trail": 0,
}
_CL_RSI_LEN, _CL_BB_LEN, _CL_ATR_LEN, _CL_ER_LEN = 14, 20, 14, 20


def compute_claudio_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {**CLAUDIO_DEFAULT_PARAMS, **{k: v for k, v in (params or {}).items()
                                      if k in CLAUDIO_DEFAULT_PARAMS and v is not None}}
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    delta = close.diff()
    gain = _wilder_rma(delta.clip(lower=0), _CL_RSI_LEN)
    loss = _wilder_rma(-delta.clip(upper=0), _CL_RSI_LEN)
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi = rsi.where(loss != 0, 100.0)

    mid = close.rolling(_CL_BB_LEN).mean()
    dev = float(p["cl_bb_mult"]) * close.rolling(_CL_BB_LEN).std(ddof=0)
    lower = mid - dev
    target = mid + dev if int(p["cl_exit_upper"]) else mid

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder_rma(tr, _CL_ATR_LEN)

    path = close.diff().abs().rolling(_CL_ER_LEN).sum()
    er = (close - close.shift(_CL_ER_LEN)).abs() / path.where(path > 0)
    ema = close.ewm(span=int(p["cl_ema_len"]), adjust=False, min_periods=int(p["cl_ema_len"])).mean()
    regime_ok = (er <= float(p["cl_er_max"])) | (close > ema)

    setup = (close < lower) & (rsi < float(p["cl_rsi_os"]))          # the oversold close
    trigger = setup.shift(1, fill_value=False) & (close > high.shift(1)) & regime_ok.fillna(False)

    c, m, a, trig = close.to_numpy(), target.to_numpy(), atr.to_numpy(), trigger.to_numpy()
    trail = bool(int(p["cl_trail"]))
    n = len(c)
    entry = np.zeros(n, dtype=bool)
    exit_ = np.zeros(n, dtype=bool)
    in_pos, stop, since = False, 0.0, 0
    k, limit = float(p["cl_atr_stop"]), int(p["cl_time_stop"])
    for i in range(n):
        if in_pos:
            since += 1
            if trail:   # from the previous close: known before this candle
                stop = max(stop, c[i - 1] - k * a[i - 1])
            if c[i] <= stop or (m[i] == m[i] and c[i] >= m[i]) or since >= limit:
                exit_[i] = True
                in_pos = False
            continue
        if trig[i] and a[i] == a[i]:
            entry[i] = True
            in_pos, stop, since = True, c[i] - k * a[i], 0

    false = pd.Series(False, index=df.index)
    return pd.DataFrame({"entry_long": entry, "entry_short": false.to_numpy(),
                         "exit_long": exit_, "exit_short": false.to_numpy()}, index=df.index)


CLAUDIO_TREND_4H = "Claudio Trend 4H"
# Lorenzo, 15/10: "una strategia che e' efficace sia in un mercato fortemente
# rialzista come il 2021, sia in un mercato fortemente ribassista come il
# 2022 [...] senza grosse perdite". Long only, trend: buy strength only while
# the daily chart is healthy, leave as soon as it is not.
CLAUDIO_TREND_DEFAULT_PARAMS = {
    "ct_len": 120,         # searched: breakout above the high of the last N 4h candles
    "ct_atr": 4.0,         # searched: trailing stop k × ATR(14) under the closes
    "ct_ema_days": 200,    # searched: daily EMA of the regime (100/150/200 days)
}


def daily_regime(df: pd.DataFrame, days: int) -> pd.Series:
    """True on a 4h candle when the PREVIOUS day closed above its daily EMA:
    known before the candle opens, no look-ahead."""
    day = df["close"].astype(float).resample("1D").last().dropna()
    ema = day.ewm(span=int(days), adjust=False, min_periods=min(int(days), 120)).mean()
    up = (day > ema).shift(1)
    return up.reindex(df.index, method="ffill").fillna(False).astype(bool)


def compute_claudio_trend_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {**CLAUDIO_TREND_DEFAULT_PARAMS, **{k: v for k, v in (params or {}).items()
                                            if k in CLAUDIO_TREND_DEFAULT_PARAMS and v is not None}}
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder_rma(tr, 14)
    top = high.rolling(int(p["ct_len"])).max().shift(1)       # the high of the N candles before
    regime = daily_regime(df, int(p["ct_ema_days"])).to_numpy()

    c, a, t = close.to_numpy(), atr.to_numpy(), top.to_numpy()
    k = float(p["ct_atr"])
    n = len(c)
    entry = np.zeros(n, dtype=bool)
    exit_ = np.zeros(n, dtype=bool)
    in_pos, stop = False, 0.0
    for i in range(n):
        if in_pos:
            stop = max(stop, c[i - 1] - k * a[i - 1])            # from the previous close
            if c[i] <= stop or not regime[i]:
                exit_[i] = True
                in_pos = False
            continue
        if regime[i] and t[i] == t[i] and a[i] == a[i] and c[i] > t[i]:
            entry[i] = True
            in_pos, stop = True, c[i] - k * a[i]

    false = np.zeros(n, dtype=bool)
    return pd.DataFrame({"entry_long": entry, "entry_short": false,
                         "exit_long": exit_, "exit_short": false}, index=df.index)


CLAUDIO_1D = "Claudio 1D"
# Lorenzo, 15/10: "metti a punto una tua strategia che reputi la migliore per
# il time frame di un giorno". Long only: buy the end of a pullback inside an
# uptrend, let the trend run on a trailing stop, leave when the trend breaks.
CLAUDIO_1D_DEFAULT_PARAMS = {
    "c1_ema": 100,      # searched: the trend — close above this EMA and the EMA rising
    "c1_pb": 20,        # searched: the pullback — a close under this EMA in the last 5 days
    "c1_atr": 3.5,      # searched: trailing stop k × ATR(14) under the closes
}


def compute_claudio_1d_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    p = {**CLAUDIO_1D_DEFAULT_PARAMS, **{k: v for k, v in (params or {}).items()
                                         if k in CLAUDIO_1D_DEFAULT_PARAMS and v is not None}}
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder_rma(tr, 14)
    n_long = int(p["c1_ema"])
    ema_l = close.ewm(span=n_long, adjust=False, min_periods=n_long).mean()
    ema_s = close.ewm(span=int(p["c1_pb"]), adjust=False, min_periods=int(p["c1_pb"])).mean()
    trend = (close > ema_l) & (ema_l > ema_l.shift(10))
    dipped = (close < ema_s).astype(float).rolling(5).max().shift(1) == 1   # under it in the 5 days before
    trigger = (trend & dipped & (close > ema_s)).fillna(False).to_numpy()

    c, a, el = close.to_numpy(), atr.to_numpy(), ema_l.to_numpy()
    k = float(p["c1_atr"])
    n = len(c)
    entry = np.zeros(n, dtype=bool)
    exit_ = np.zeros(n, dtype=bool)
    in_pos, stop = False, 0.0
    for i in range(n):
        if in_pos:
            stop = max(stop, c[i - 1] - k * a[i - 1])            # from the previous close
            if c[i] <= stop or c[i] < el[i]:
                exit_[i] = True
                in_pos = False
            continue
        if trigger[i] and a[i] == a[i]:
            entry[i] = True
            in_pos, stop = True, c[i] - k * a[i]

    false = np.zeros(n, dtype=bool)
    return pd.DataFrame({"entry_long": entry, "entry_short": false,
                         "exit_long": exit_, "exit_short": false}, index=df.index)


def compute_lki2_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    base = compute_lki_signals(df, params)
    # L'uscita long dell'originale e' la condizione di ipercomprato: qui apre
    # anche lo short. Simmetricamente l'ingresso long chiude lo short — cioe'
    # la posizione si ribalta invece di restare piatta fra i due estremi.
    entry_long = base["entry_long"]
    entry_short = base["exit_long"]
    return pd.DataFrame(
        {
            "entry_long": entry_long,
            "entry_short": entry_short,
            "exit_long": entry_short,
            "exit_short": entry_long,
        },
        index=df.index,
    )


# Registry of pluggable strategies — dispatch used by confirmed_events()
# whenever a caller passes a strategy name instead of pre-computed signals.
STRATEGY_REGISTRY = {
    "Lorenzo (trend-follower)": compute_signals,
    "Accumulo / Distribuzione (long-term)": compute_exhaustion_signals,
    "Gabriele (RSI+BB reversal)": compute_lki_signals,
    "Gabriele 2 (RSI+BB long/short)": compute_lki2_signals,
    RSI_BB_4H: compute_lki4h_signals,
    CLAUDIO_4H: compute_claudio_signals,
    CLAUDIO_TREND_4H: compute_claudio_trend_signals,
    CLAUDIO_1D: compute_claudio_1d_signals,
    "Lorenzo HF (minuti on-chain)": compute_lorenzo_hf_signals,
}


def _with_btc_filter(fn):
    """Every strategy honours the `btc_filter` switch (btc_regime): wrapping
    the registry once means every caller — Run, chart, alerts, archive,
    optimizations — sees the same filtered signals."""
    def run(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        return btc_regime.apply(fn(df, params), params)
    run.__name__ = getattr(fn, "__name__", "strategy")
    run.__wrapped__ = fn
    return run


STRATEGY_REGISTRY = {name: _with_btc_filter(fn) for name, fn in STRATEGY_REGISTRY.items()}
# Registered (backtests and the comparison script can run them) but not
# offered in the menus or alerts until Lorenzo has seen the real-data
# comparison (15/10: "prima di renderla operativa").
HIDDEN_STRATEGIES = {CLAUDIO_4H, CLAUDIO_TREND_4H, CLAUDIO_1D}
AVAILABLE_STRATEGIES = [k for k in STRATEGY_REGISTRY if k not in HIDDEN_STRATEGIES]
DEFAULT_STRATEGY = AVAILABLE_STRATEGIES[0]


_LABELS = {
    "entry_long": "Ingresso long rilevato",
    "entry_short": "Ingresso short rilevato",
    "exit_long": "Uscita long rilevata",
    "exit_short": "Uscita short rilevata",
    "flip_to_long": "Inversione: chiusura short e apertura long",
    "flip_to_short": "Inversione: chiusura long e apertura short",
}


def last_bar_is_closed(df: pd.DataFrame) -> bool:
    """Se l'ultima barra della serie e' gia' chiusa o si sta ancora formando.

    La durata della barra si deduce dalla distanza fra le ultime due, invece
    di farsela passare: cosi' vale anche per gli intervalli sintetici (2d/3d/5d,
    ricampionati) senza che ogni chiamante debba sapere quale sia.
    """
    if len(df) < 2:
        return False
    bar_seconds = (df.index[-1] - df.index[-2]).total_seconds()
    if bar_seconds <= 0:
        return False
    return df.index[-1].timestamp() + bar_seconds <= time.time()


def confirmed_events(
    df: pd.DataFrame,
    params: dict | None = None,
    signals: pd.DataFrame | None = None,
    strategy_name: str = DEFAULT_STRATEGY,
    last_bar_closed: bool = False,
) -> tuple[list[StrategySignal], int]:
    """All confirmed position-transition events for the full window (uncapped —
    used for backtesting), plus the resulting final position (1/0/-1).

    The most recent candle is still forming — its close (and therefore any
    signal computed on it) keeps changing between fetches. Alerting on it
    would fire, vanish, and re-fire as the price moves, spamming the same
    timestamp. We still fold it into the returned position for a live-ish
    badge, but never emit it as a confirmed event.

    `last_bar_closed` esiste perche' quella regola, applicata alla cieca,
    ritardava ogni alert di una barra intera. Il watcher, per le voci con
    "alla chiusura della candela", toglie gia' la barra in formazione
    (drop_unclosed_candle): l'ultima riga che resta e' quindi una barra
    CHIUSA, e scartarla comunque come "non confermata" significava aspettare
    la barra successiva per accorgersi di un segnale gia' definitivo — su un
    daily, un giorno intero. E' quello che e' successo su INJUSDT: incrocio
    alla chiusura del 14 settembre, notifica il 16.

    Resta `False` di default apposta: i backtest passano la serie cosi' com'e'
    (barra in formazione inclusa) e devono continuare a vedere esattamente i
    segnali di prima — questo parametro non deve cambiare un solo numero
    storico. Lo passa `build_strategy_state`, che sa distinguere i due casi.

    `signals` lets callers (e.g. the Pine Script engine) inject an
    already-computed entry_long/entry_short/exit_long/exit_short frame
    instead of dispatching to a registered strategy by name.
    """
    if signals is None:
        compute_fn = STRATEGY_REGISTRY.get(strategy_name, STRATEGY_REGISTRY["Lorenzo (trend-follower)"])
        signals = compute_fn(df, params)
    if last_bar_closed:
        last_confirmed_ts = df.index[-1] if len(df) else None
    else:
        last_confirmed_ts = df.index[-2] if len(df) > 1 else None

    position = 0  # 0 flat, 1 long, -1 short
    events: list[StrategySignal] = []

    # Columns as plain lists instead of signals.iterrows() (overhaul plan,
    # week 2): same values, same order, no Series per row.
    cols = {c: signals[c].tolist() for c in ("entry_long", "entry_short", "exit_long", "exit_short")}
    # Bars past the last closed one, by position: iterating the DatetimeIndex
    # built a Timestamp per bar and was 40% of a backtest on 20 000 candles.
    sig_index = signals.index
    n_confirmed = (len(sig_index) if last_confirmed_ts is None
                   else int(sig_index.searchsorted(last_confirmed_ts, side="right")))
    for i in range(len(sig_index)):
        prev_position = position
        if position == 1 and cols["exit_long"][i]:
            position = 0
        elif position == -1 and cols["exit_short"][i]:
            position = 0
        if cols["entry_long"][i]:
            position = 1
        elif cols["entry_short"][i]:
            position = -1

        if position == prev_position:
            continue
        if i >= n_confirmed:
            continue  # transition happened on the still-forming candle; not confirmed yet
        ts = sig_index[i]

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


def trend_down(df: pd.DataFrame, strategy_name: str, params: dict | None = None) -> pd.Series:
    """True on every bar where the trend follower's fast slope is below the
    slow one: the trend is down, whatever the entry filters say.

    The strategies only emit exit edges (the cross, or HF's own position
    closing), so a position the strategy did not open itself (the sniper,
    bought on the alert) never gets an exit if the trend was already down
    when it was bought: MESUB rode -95% (Lorenzo, 28/09: "come mai su queste
    la strategia non e' uscita prima?")."""
    hf = strategy_name.startswith("Lorenzo HF")
    p = {**(LORENZO_HF_DEFAULT_PARAMS if hf else DEFAULT_PARAMS), **(params or {})}
    ma = _ma(df["close"], int(p["len"]), "EMA" if hf else p["average"])
    slope = ma.diff() / ma
    fast = slope.ewm(span=int(p["slopeFlen"]), adjust=False).mean()
    slow = slope.ewm(span=int(p["slopeSlen"]), adjust=False).mean()
    return (fast < slow).fillna(False)


def spot_only(signals: pd.DataFrame) -> pd.DataFrame:
    """Solo acquisti e vendite, mai short: un segnale short diventa la
    vendita di quello che si ha. Per il DEX, dove si compra e si vende il
    token e basta (Lorenzo: "non voglio short, solo acquisti spot e vendite")."""
    out = signals.copy()
    out["exit_long"] = out["exit_long"].astype(bool) | out["entry_short"].astype(bool)
    out["entry_short"] = False
    out["exit_short"] = False
    return out


# Un token non muore solo con un crollo rapido: la liquidita' puo' essere
# ritirata in una candela, il prezzo puo' spegnersi lentamente, gli scambi
# possono prosciugarsi dopo la caduta, o il rug puo' essere gia' stato visto
# on-chain. Ognuno di questi casi spegne la strategia e non la fa rientrare
# (Lorenzo, 28/09: "come regola e' un po' insufficiente; valuta tu un modo
# piu' intelligente, che carpisca il senso di quello che intendevo").
RUG_CRASH_WINDOW = "6h"
RUG_DEAD_RATIO = 0.15
RUG_ABANDONED_WINDOW = "24h"
RUG_ABANDONED_RATIO = 0.40
RUG_VOLUME_WINDOW = "24h"
RUG_VOLUME_BARS = 12
RUG_VOLUME_RATIO = 0.05


def _pct(ratio: float) -> str:
    return f"-{round((1 - ratio) * 100)}%"


def rug_event(df: pd.DataFrame, known: dict | None = None) -> dict | None:
    """La prima barra in cui il token mostra di essere morto, con il motivo.

    Ogni barra e' giudicata solo sulle barre fino a lei (nessuna informazione
    futura). Ritorna {"i": posizione, "why": testo} o None. L'ordine dei
    controlli e' quello dei casi piu' netti prima: prima la liquidita'
    ritirata in una candela, poi il crollo, poi il token morto, poi gli
    scambi prosciugati, infine il rug gia' visto on-chain."""
    if df.empty:
        return None
    close, high, open_, volume = df["close"], df["high"], df["open"], df["volume"]
    peak6 = high.rolling(RUG_CRASH_WINDOW).max()
    top = high.cummax()
    peak24 = high.rolling(RUG_ABANDONED_WINDOW).max()
    vol_mean = volume.rolling(RUG_VOLUME_BARS).mean()
    vol_peak = vol_mean.rolling(RUG_VOLUME_WINDOW).max()
    # (condition, reason at bar i): the earliest bar wins; on the same bar,
    # the order below (sharpest cases first).
    checks = [
        (close <= 0.5 * open_, lambda i: f"one candle {_pct(close.iloc[i] / open_.iloc[i])}: liquidity pulled"),
        (close <= 0.30 * peak6, lambda i: f"crash {_pct(close.iloc[i] / peak6.iloc[i])} in under 6h"),
        # Not a rug by itself: HYDX (30/09) was -86% from its top and alive, $311k
        # a day on $58k locked. The strategy still stops (seed-0199), as a "fall".
        (close <= RUG_DEAD_RATIO * top, lambda i: f"{_pct(close.iloc[i] / top.iloc[i])} from its top"),
        ((close <= RUG_ABANDONED_RATIO * peak24) & (vol_mean <= RUG_VOLUME_RATIO * vol_peak),
         lambda i: "trading dried up after the fall"),
    ]
    best = None
    for n, (cond, why) in enumerate(checks):
        hit = cond.fillna(False).to_numpy().nonzero()[0]
        if len(hit) and (best is None or hit[0] < best[0]):
            best = (int(hit[0]), why, "fall" if n == 2 else "rug")
    if known and known.get("at"):
        stamps = [i for i, ts in enumerate(df.index) if ts.timestamp() >= known["at"]]
        if stamps and (best is None or stamps[0] < best[0]):
            return {"i": stamps[0], "why": known.get("why") or "rug seen on-chain", "kind": "rug"}
    return {"i": best[0], "why": best[1](best[0]), "kind": best[2]} if best else None


def rug_stop(df: pd.DataFrame, signals: pd.DataFrame, known: dict | None = None) -> pd.DataFrame:
    """Dal rug in poi niente piu' ingressi e la posizione lunga si chiude
    sulla barra dell'evento: il token e' flaggato come morto e il backtest
    non prosegue (Lorenzo, 28/09)."""
    out = signals.copy()
    ev = rug_event(df, known)
    if ev is None:
        return out
    i = ev["i"]
    out.iloc[i:, out.columns.get_loc("entry_long")] = False
    out.iloc[i:, out.columns.get_loc("entry_short")] = False
    out.iloc[i, out.columns.get_loc("exit_long")] = True
    return out


def build_strategy_state(
    name: str, df: pd.DataFrame, params: dict | None = None, signals: pd.DataFrame | None = None
) -> StrategyState:
    # A differenza del backtest, qui la serie puo' gia' essere stata ripulita
    # dalla barra in formazione (il watcher lo fa per le voci "alla chiusura
    # della candela"): in quel caso l'ultima riga e' una barra chiusa, e
    # trattarla come non confermata ritarderebbe l'alert di una barra intera.
    events, position = confirmed_events(
        df, params, signals=signals, strategy_name=name,
        last_bar_closed=last_bar_is_closed(df),
    )
    position_label = {1: "long", -1: "short", 0: "flat"}[position]
    return StrategyState(name=name, position=position_label, signals=events[-_MAX_ALERTS_RETURNED:])
