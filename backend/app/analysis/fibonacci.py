"""
Automatic Fibonacci retracement + extension engine.

Reuses the same swing-detection primitive already powering the app's SMC
levels (smc.swing_highs_lows / smc_engine.SWING_LENGTH_BY_TIMEFRAME) so a
"swing" means the same thing here as it does for BOS/CHoCH/order blocks —
prototyped and eyeballed against real BTC/ETH data before being wired in.

Only the single most recent retracement and, when a confirmed pullback
exists, the single most recent extension are returned — same philosophy as
compute_dealing_range's "most recent swing low -> most recent swing high":
older legs are no longer actionable and just clutter the chart.
"""

import pandas as pd
from smartmoneyconcepts import smc

from app.analysis.smc_engine import SWING_LENGTH_BY_TIMEFRAME
from app.models import FibZone

RETRACEMENT_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
EXTENSION_RATIOS = [1.272, 1.414, 1.618, 2.0, 2.618]

# A leg smaller than this (as a fraction of its own lower end) is noise, not
# a tradeable impulse — skip it rather than draw a fib on a wiggle.
MIN_LEG_PCT = 0.008  # 0.8%


def _get_swing_pivots(df: pd.DataFrame, timeframe_key: str) -> list[dict]:
    swing_length = SWING_LENGTH_BY_TIMEFRAME.get(timeframe_key, 8)
    swings = smc.swing_highs_lows(df, swing_length=swing_length)
    valid = swings.dropna(subset=["HighLow"])
    return [
        {"pos": pos, "HighLow": row["HighLow"], "Level": float(row["Level"]), "ts": int(df.index[int(pos)].timestamp())}
        for pos, row in valid.iterrows()
    ]


def _leg_pct(a: float, b: float) -> float:
    return abs(b - a) / min(a, b)


def compute_fib_zones(df: pd.DataFrame, timeframe_key: str) -> list[FibZone]:
    pivots = _get_swing_pivots(df, timeframe_key)
    if len(pivots) < 2:
        return []

    zones: list[FibZone] = []

    # Most recent completed leg: second-to-last pivot -> last pivot.
    a, b = pivots[-2], pivots[-1]
    if _leg_pct(a["Level"], b["Level"]) >= MIN_LEG_PCT:
        bullish = b["HighLow"] == 1  # ends on a high => leg went up
        retracement_levels = {str(r): a["Level"] + (b["Level"] - a["Level"]) * r for r in RETRACEMENT_RATIOS}
        zones.append(
            FibZone(
                kind="retracement",
                direction="bullish" if bullish else "bearish",
                anchor_time=a["ts"],
                levels=retracement_levels,
                label=f"Fib ritracciamento {'rialzista' if bullish else 'ribassista'}",
            )
        )

        # A fib extension is the classic 3-point A-B-C projection: an impulse
        # (A -> B) followed by a pullback that stops at C without breaking
        # back past A, projecting where price might go if the original move
        # resumes. B is already the latest pivot here, so there's no
        # confirmed C after it yet — instead treat *this* leg (a -> b) as
        # the pullback (C) off the *previous* impulse (further_a -> a),
        # i.e. look one leg further back for A.
        if len(pivots) >= 3:
            further_a = pivots[-3]
            impulse_bullish = a["HighLow"] == 1  # further_a (low) -> a (high)
            pullback_holds = (b["Level"] > further_a["Level"]) if impulse_bullish else (b["Level"] < further_a["Level"])
            if pullback_holds and _leg_pct(further_a["Level"], a["Level"]) >= MIN_LEG_PCT:
                leg_size = a["Level"] - further_a["Level"]
                ext_levels = {str(r): b["Level"] + leg_size * r for r in EXTENSION_RATIOS}
                zones.append(
                    FibZone(
                        kind="extension",
                        direction="bullish" if impulse_bullish else "bearish",
                        anchor_time=b["ts"],
                        levels=ext_levels,
                        label=f"Fib estensione {'rialzista' if impulse_bullish else 'ribassista'}",
                    )
                )

    return zones
