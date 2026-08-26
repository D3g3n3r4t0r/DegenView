from typing import Literal

# TradingView-style granularity choices, kept to the intersection of what both
# providers (Twelve Data and MEXC) support natively — no per-provider gaps.
IntervalChoice = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"]
CANONICAL_INTERVALS: tuple[IntervalChoice, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")

DEFAULT_INTERVALS: dict[str, IntervalChoice] = {"htf": "1d", "mtf": "1h", "ltf": "15m"}
