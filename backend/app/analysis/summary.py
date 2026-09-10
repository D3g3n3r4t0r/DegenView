import math
from typing import Literal

from app.models import AnalysisSummary, Candle, ConfluenceZone, IndicatorSeries, LiquidityLevel, TimeframeAnalysis

Bias = Literal["bullish", "bearish", "neutral"]

_BIAS_IT = {"bullish": "rialzista", "bearish": "ribassista", "neutral": "neutrale"}
_TF_LABEL = {"htf": "HTF", "mtf": "MTF", "ltf": "LTF"}


def _fmt_price(x: float) -> str:
    # Plain-language text for non-quants: never scientific notation (that's what
    # ".4g" gave us for 5+ digit prices like BTC), and Italian punctuation
    # (punto per le migliaia, virgola per i decimali) to match the rest of the app.
    if x == 0:
        s = "0,00"
    elif abs(x) >= 1:
        s = f"{x:,.2f}"
        s = s.replace(",", "\0").replace(".", ",").replace("\0", ".")
    else:
        # Small prices (e.g. a memecoin at 0.00001142) need enough decimals to
        # show a few significant digits instead of rounding straight to 0,00.
        decimals = max(2, -int(math.floor(math.log10(abs(x)))) + 2)
        s = f"{x:.{decimals}f}".replace(".", ",")
    return s


def determine_bias(levels: list[LiquidityLevel]) -> Bias:
    # Purely structural: the direction of the last confirmed break of structure.
    # No indicator fallback here, so this stays one independent fact among many
    # rather than a blended "verdict" that hides what the other indicators show.
    structure_events = [lvl for lvl in levels if lvl.type in ("bos", "choch")]
    if not structure_events:
        return "neutral"
    latest = max(structure_events, key=lambda lvl: lvl.start_time)
    return latest.direction  # type: ignore[return-value]


def _latest_value(values: list[float | None]) -> float | None:
    for v in reversed(values):
        if v is not None:
            return v
    return None


def _indicator_readout(tf_key: str, indicators: list[IndicatorSeries], candles: list[Candle]) -> list[str]:
    by_name = {s.name: s.values for s in indicators}
    close = candles[-1].close if candles else None
    prefix = f"[{_TF_LABEL.get(tf_key, tf_key.upper())}]"
    lines: list[str] = []

    ema20 = _latest_value(by_name.get("EMA20", []))
    ema50 = _latest_value(by_name.get("EMA50", []))
    if ema20 is not None and ema50 is not None:
        rel = "sopra" if ema20 > ema50 else "sotto" if ema20 < ema50 else "allineata a"
        lines.append(f"{prefix} EMA20 {rel} EMA50")

    rsi = _latest_value(by_name.get("RSI14", []))
    if rsi is not None:
        zone = "ipercomprato" if rsi >= 70 else "ipervenduto" if rsi <= 30 else "neutrale"
        lines.append(f"{prefix} RSI(14) a {rsi:.0f} — {zone}")

    macd = _latest_value(by_name.get("MACD", []))
    macd_signal = _latest_value(by_name.get("MACD_signal", []))
    if macd is not None and macd_signal is not None:
        rel = "sopra" if macd > macd_signal else "sotto" if macd < macd_signal else "sulla"
        lines.append(f"{prefix} MACD {rel} la linea segnale")

    bb_upper = _latest_value(by_name.get("BB_upper", []))
    bb_lower = _latest_value(by_name.get("BB_lower", []))
    if close is not None and bb_upper is not None and bb_lower is not None and bb_upper != bb_lower:
        pct = max(0.0, min(100.0, (close - bb_lower) / (bb_upper - bb_lower) * 100))
        lines.append(f"{prefix} Prezzo al {pct:.0f}% della banda di Bollinger")

    vwap = _latest_value(by_name.get("VWAP", []))
    if close is not None and vwap is not None:
        rel = "sopra" if close > vwap else "sotto" if close < vwap else "sul"
        lines.append(f"{prefix} Prezzo {rel} il VWAP")

    return lines


def _long_term_context(current_price: float, htf_analysis: TimeframeAnalysis) -> list[str]:
    lines: list[str] = []

    if htf_analysis.dealing_range is not None:
        low, high = htf_analysis.dealing_range
        pct = max(0.0, min(100.0, (current_price - low) / (high - low) * 100))
        if pct < 45:
            zone = "sconto (discount)"
        elif pct > 55:
            zone = "premio (premium)"
        else:
            zone = "equilibrio"
        lines.append(
            f"Prezzo al {pct:.0f}% del range strutturale HTF ({_fmt_price(low)}–{_fmt_price(high)}) — zona di {zone}."
        )

    zone_types = ("order_block", "fvg", "eqh", "eql")
    unmitigated = [lvl for lvl in htf_analysis.levels if not lvl.mitigated and lvl.type in zone_types]
    below = [lvl for lvl in unmitigated if (lvl.price_high + lvl.price_low) / 2 < current_price]
    above = [lvl for lvl in unmitigated if (lvl.price_high + lvl.price_low) / 2 > current_price]

    if below:
        lvl = max(below, key=lambda l: (l.price_high + l.price_low) / 2)  # noqa: E741
        mid = (lvl.price_high + lvl.price_low) / 2
        dist_pct = (mid - current_price) / current_price * 100
        lines.append(f"Livello HTF non mitigato più vicino sotto: {lvl.label} a {_fmt_price(mid)} ({dist_pct:+.1f}%).")
    if above:
        lvl = min(above, key=lambda l: (l.price_high + l.price_low) / 2)  # noqa: E741
        mid = (lvl.price_high + lvl.price_low) / 2
        dist_pct = (mid - current_price) / current_price * 100
        lines.append(f"Livello HTF non mitigato più vicino sopra: {lvl.label} a {_fmt_price(mid)} ({dist_pct:+.1f}%).")

    return lines


def build_summary(
    current_price: float,
    timeframes: dict[str, TimeframeAnalysis],
    confluence_zones: list[ConfluenceZone],
) -> AnalysisSummary:
    htf_bias = timeframes["htf"].bias
    top_zones = confluence_zones[:5]

    all_unmitigated = [
        level
        for analysis in timeframes.values()
        for level in analysis.levels
        if not level.mitigated
    ]
    unmitigated_gaps = sum(1 for lvl in all_unmitigated if lvl.type == "fvg")

    above = [lvl for lvl in all_unmitigated if (lvl.price_high + lvl.price_low) / 2 > current_price]
    below = [lvl for lvl in all_unmitigated if (lvl.price_high + lvl.price_low) / 2 < current_price]
    nearest_above = min((lvl.price_low for lvl in above), default=None)
    nearest_below = max((lvl.price_high for lvl in below), default=None)

    parts = [f"Ultima rottura di struttura confermata su HTF: {_BIAS_IT[htf_bias]}."]
    if htf_bias == "neutral":
        parts = ["Nessuna rottura di struttura (BOS/CHoCH) recente su HTF."]
    if top_zones:
        z = top_zones[0]
        parts.append(
            f"Zona di confluenza più rilevante ({'/'.join(t.upper() for t in z.timeframes)}) "
            f"tra {_fmt_price(z.price_low)} e {_fmt_price(z.price_high)}: {z.label}."
        )
    parts.append(f"Gap non mitigati attivi su tutti i timeframe: {unmitigated_gaps}.")
    if nearest_above is not None:
        parts.append(f"Prossima zona di liquidità sopra il prezzo corrente: {_fmt_price(nearest_above)}.")
    if nearest_below is not None:
        parts.append(f"Prossima zona di liquidità sotto il prezzo corrente: {_fmt_price(nearest_below)}.")

    indicator_readout: list[str] = []
    for tf_key in ("htf", "mtf", "ltf"):
        analysis = timeframes.get(tf_key)
        if analysis:
            indicator_readout.extend(_indicator_readout(tf_key, analysis.indicators, analysis.candles))

    long_term_context = _long_term_context(current_price, timeframes["htf"])

    return AnalysisSummary(
        htf_bias=htf_bias,
        text=" ".join(parts),
        indicator_readout=indicator_readout,
        long_term_context=long_term_context,
        top_confluence_zones=top_zones,
        unmitigated_gaps=unmitigated_gaps,
        nearest_liquidity_above=nearest_above,
        nearest_liquidity_below=nearest_below,
    )
