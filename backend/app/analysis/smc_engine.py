import pandas as pd
from smartmoneyconcepts import smc

from app.models import LiquidityLevel

# Swing lookback (candles each side) tuned per timeframe: higher timeframes need
# fewer candles to define a meaningful swing, lower timeframes are noisier.
SWING_LENGTH_BY_TIMEFRAME = {"htf": 5, "mtf": 8, "ltf": 12}
LIQUIDITY_RANGE_PERCENT = 0.01

# Without a cap, every BOS/CHoCH/OB/FVG/EQH/EQL ever detected across the whole
# fetched history (hundreds of candles) becomes a permanent chart label —
# unreadable, especially on narrow mobile screens. Keep only the most recent
# few per type; older structure is no longer actionable anyway.
_LEVEL_LIMIT_PER_TYPE = {"bos": 6, "choch": 6, "order_block": 5, "fvg": 6, "eqh": 5, "eql": 5}

# Bounded content-fingerprinted caches for SMC swings and structural levels.
# Keyed by (timeframe_key/swing_len, n, first_ts, last_ts, last_close, last_high, last_low)
# so any new bar or live unclosed bar price change invalidates immediately, while
# repeated /api/analyze requests (or strategy/parameter toggles on the same chart)
# skip ~180 ms of O(N^2) Python loops in `smartmoneyconcepts`.
_SMC_CACHE_MAX = 192
_SWINGS_CACHE: dict[tuple, pd.DataFrame] = {}
_LEVELS_CACHE: dict[tuple, list[LiquidityLevel]] = {}
_SMC_STATS = {"swings_hits": 0, "swings_misses": 0, "levels_hits": 0, "levels_misses": 0}


def _df_smc_key(df: pd.DataFrame, extra: str | int = "") -> tuple | None:
    n = len(df)
    if n == 0:
        return None
    try:
        idx = df.index
        first_ts = int(idx[0].value) if hasattr(idx[0], "value") else hash(idx[0])
        last_ts = int(idx[-1].value) if hasattr(idx[-1], "value") else hash(idx[-1])
        c_last = round(float(df["close"].iloc[-1]), 8)
        h_last = round(float(df["high"].iloc[-1]), 8)
        l_last = round(float(df["low"].iloc[-1]), 8)
        return (extra, n, first_ts, last_ts, c_last, h_last, l_last)
    except Exception:
        return None


def smc_cache_stats() -> dict[str, int]:
    return {
        **_SMC_STATS,
        "swings_cached": len(_SWINGS_CACHE),
        "levels_cached": len(_LEVELS_CACHE),
    }


def _cap_recent_per_type(levels: list[LiquidityLevel]) -> list[LiquidityLevel]:
    grouped: dict[str, list[LiquidityLevel]] = {}
    for lvl in levels:
        grouped.setdefault(lvl.type, []).append(lvl)
    out: list[LiquidityLevel] = []
    for level_type, group in grouped.items():
        if level_type == "fvg":
            # Fra le imbalance, quelle non ancora riempite vengono prima delle
            # riempite anche se piu' vecchie: una zona ancora aperta e' un
            # livello che il prezzo puo' tornare a cercare, una gia' richiusa
            # e' cronaca. Tenendo solo le piu' recenti, un vuoto aperto da
            # mesi — esattamente quello che si guarda — spariva dal grafico
            # perche' nel frattempo se ne erano formate e richiuse altre sei.
            group.sort(key=lambda l: (l.mitigated, -l.start_time))  # noqa: E741
        else:
            group.sort(key=lambda l: l.start_time, reverse=True)  # noqa: E741
        out.extend(group[: _LEVEL_LIMIT_PER_TYPE.get(level_type, 6)])
    return out


def _ts(df: pd.DataFrame, pos) -> int:
    return int(df.index[int(pos)].timestamp())


def _ts_or_none(df: pd.DataFrame, pos) -> int | None:
    # These SMC functions use 0 as a sentinel meaning "not yet resolved", not a real index.
    if pos is None or pd.isna(pos) or int(pos) <= 0:
        return None
    return _ts(df, pos)


def compute_swings(df: pd.DataFrame, timeframe_key: str) -> pd.DataFrame:
    """The one swing-high/low pass every other function here (and the fib
    engine) builds on. Called once per timeframe in main.py and threaded
    through — swing_highs_lows is a non-trivial rolling-window pass over the
    full candle history, and computing it separately per consumer (levels,
    dealing range, fib zones) tripled the work for identical output."""
    swing_length = SWING_LENGTH_BY_TIMEFRAME.get(timeframe_key, 8)
    key = _df_smc_key(df, swing_length)
    if key is not None:
        cached = _SWINGS_CACHE.get(key)
        if cached is not None:
            _SMC_STATS["swings_hits"] += 1
            return cached
    _SMC_STATS["swings_misses"] += 1
    res = smc.swing_highs_lows(df, swing_length=swing_length)
    if key is not None:
        if len(_SWINGS_CACHE) >= _SMC_CACHE_MAX:
            _SWINGS_CACHE.pop(next(iter(_SWINGS_CACHE)), None)
        _SWINGS_CACHE[key] = res
    return res


def compute_dealing_range(df: pd.DataFrame, swings: pd.DataFrame) -> tuple[float, float] | None:
    """Current structural range (most recent swing low -> most recent swing high),
    used to place price in a premium/discount/equilibrium context."""
    valid = swings.dropna(subset=["HighLow"])
    highs = valid[valid["HighLow"] == 1]
    lows = valid[valid["HighLow"] == -1]
    if highs.empty or lows.empty:
        return None
    last_high = float(highs.iloc[-1]["Level"])
    last_low = float(lows.iloc[-1]["Level"])
    if last_high <= last_low:
        return None
    return last_low, last_high


def compute_levels(df: pd.DataFrame, swings: pd.DataFrame) -> list[LiquidityLevel]:
    # Include the last non-null swing level in the key so different `swings` frames
    # on the same `df` never collide.
    valid_sw = swings.dropna(subset=["HighLow"]) if len(swings) else swings
    sw_tag = (
        f"{len(valid_sw)}:{float(valid_sw.iloc[-1]['Level']):.6g}"
        if not valid_sw.empty
        else "0"
    )
    key = _df_smc_key(df, sw_tag)
    if key is not None:
        cached = _LEVELS_CACHE.get(key)
        if cached is not None:
            _SMC_STATS["levels_hits"] += 1
            return list(cached)
    _SMC_STATS["levels_misses"] += 1
    levels: list[LiquidityLevel] = []
    levels.extend(_bos_choch_levels(df, swings))
    levels.extend(_order_block_levels(df, swings))
    levels.extend(_fvg_levels(df))
    levels.extend(_liquidity_levels(df, swings))
    capped = _cap_recent_per_type(levels)
    if key is not None:
        if len(_LEVELS_CACHE) >= _SMC_CACHE_MAX:
            _LEVELS_CACHE.pop(next(iter(_LEVELS_CACHE)), None)
        _LEVELS_CACHE[key] = capped
    return list(capped)


def _bos_choch_levels(df: pd.DataFrame, swings: pd.DataFrame) -> list[LiquidityLevel]:
    bos = smc.bos_choch(df, swings, close_break=True)
    out = []
    for pos, row in bos.dropna(subset=["BOS", "CHOCH"], how="all").iterrows():
        is_bos = pd.notna(row["BOS"])
        value = row["BOS"] if is_bos else row["CHOCH"]
        direction = "bullish" if value > 0 else "bearish"
        kind = "bos" if is_bos else "choch"
        out.append(
            LiquidityLevel(
                type=kind,
                direction=direction,
                price_high=float(row["Level"]),
                price_low=float(row["Level"]),
                start_time=_ts(df, pos),
                end_time=_ts_or_none(df, row.get("BrokenIndex")),
                mitigated=True,
                label=f"{'BOS' if is_bos else 'CHoCH'} {'bullish' if direction == 'bullish' else 'bearish'}",
            )
        )
    return out


def _order_block_levels(df: pd.DataFrame, swings: pd.DataFrame) -> list[LiquidityLevel]:
    ob = smc.ob(df, swings, close_mitigation=False)
    out = []
    for pos, row in ob.dropna(subset=["OB"]).iterrows():
        direction = "bullish" if row["OB"] > 0 else "bearish"
        mitigated_ts = _ts_or_none(df, row.get("MitigatedIndex"))
        out.append(
            LiquidityLevel(
                type="order_block",
                direction=direction,
                price_high=float(row["Top"]),
                price_low=float(row["Bottom"]),
                start_time=_ts(df, pos),
                end_time=mitigated_ts,
                mitigated=mitigated_ts is not None,
                label=f"Order Block {'bullish' if direction == 'bullish' else 'bearish'} ({row['Percentage']:.0f}% strength)",
            )
        )
    return out


def _fvg_levels(df: pd.DataFrame) -> list[LiquidityLevel]:
    # Ogni vuoto per conto suo, non fusi. L'unione dei consecutivi produceva un
    # box alto quanto due o tre imbalance messe insieme — un intervallo di
    # prezzo che come vuoto non e' mai esistito, e che si richiude "a meta'"
    # quando il prezzo rientra nel primo dei gap fusi. TradingView ne disegna
    # uno per gap, ed e' anche l'unico modo in cui l'altezza del box significa
    # qualcosa.
    fvg = smc.fvg(df, join_consecutive=False)
    out = []
    for pos, row in fvg.dropna(subset=["FVG"]).iterrows():
        direction = "bullish" if row["FVG"] > 0 else "bearish"
        mitigated_ts = _ts_or_none(df, row.get("MitigatedIndex"))
        out.append(
            LiquidityLevel(
                type="fvg",
                direction=direction,
                price_high=float(row["Top"]),
                price_low=float(row["Bottom"]),
                # La libreria segna la candela di mezzo, ma il vuoto e' fra la
                # PRIMA e la TERZA: un box che parte da quella di mezzo copre
                # meta' del movimento che l'ha creato e comincia una barra dopo
                # rispetto a come lo disegna TradingView.
                start_time=_ts(df, max(int(pos) - 1, 0)),
                end_time=mitigated_ts,
                mitigated=mitigated_ts is not None,
                label=f"Fair Value Gap {'bullish' if direction == 'bullish' else 'bearish'}",
            )
        )
    return out


def _liquidity_levels(df: pd.DataFrame, swings: pd.DataFrame) -> list[LiquidityLevel]:
    liq = smc.liquidity(df, swings, range_percent=LIQUIDITY_RANGE_PERCENT)
    out = []
    for pos, row in liq.dropna(subset=["Liquidity"]).iterrows():
        is_high_pool = row["Liquidity"] > 0
        level_type = "eqh" if is_high_pool else "eql"
        direction = "bullish" if is_high_pool else "bearish"
        swept_ts = _ts_or_none(df, row.get("Swept"))
        out.append(
            LiquidityLevel(
                type=level_type,
                direction=direction,
                price_high=float(row["Level"]),
                price_low=float(row["Level"]),
                start_time=_ts(df, pos),
                end_time=swept_ts,
                mitigated=swept_ts is not None,
                label=("Equal Highs (buy-side liquidity)" if is_high_pool else "Equal Lows (sell-side liquidity)"),
            )
        )
    return out
