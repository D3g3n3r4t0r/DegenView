"""Catalogo dei 151 indicatori di pandas-ta, con classificazione per il grafico.

pandas-ta e' gia' una dipendenza (vedi indicators.py, che ne usa solo 6 dei
151 disponibili). Questo modulo espone gli altri: un registro che dice per
ciascuno come chiamarlo, se va disegnato sul prezzo o in un riquadro separato,
e quali parametri ha senso esporre in UI. Il frontend lo usa per popolare la
libreria a tendina; nessun indicatore viene calcolato finche' l'utente non lo
sceglie esplicitamente, cosi' /api/analyze non si appesantisce.
"""
from __future__ import annotations

import pandas as pd
import pandas_ta  # noqa: F401  (registra l'accessor .ta)

from app.models import IndicatorSeries

Param = dict  # {"name": str, "label": str, "default": float, "min": float, "max": float}


class IndicatorSpec:
    __slots__ = ("id", "label", "category", "kind", "params", "output_labels")

    def __init__(self, id_: str, label: str, category: str, kind: str,
                 params: list[Param] | None = None, output_labels: list[str] | None = None):
        self.id = id_
        self.label = label
        self.category = category
        self.kind = kind  # "overlay" (sul prezzo) o "oscillator" (riquadro proprio)
        self.params = params or []
        self.output_labels = output_labels  # nomi delle colonne quando l'output ha piu' linee


def _p(name: str, label: str, default: float, lo: float, hi: float) -> Param:
    return {"name": name, "label": label, "default": default, "min": lo, "max": hi}


LENGTH = lambda d=14: [_p("length", "Periodo", d, 2, 400)]  # noqa: E731

CATEGORY_LABELS = {
    "candle": "Pattern candele",
    "cycle": "Cicli",
    "momentum": "Momentum",
    "overlap": "Medie e overlay",
    "performance": "Performance",
    "statistics": "Statistiche",
    "trend": "Trend",
    "volatility": "Volatilita'",
    "volume": "Volume",
}

# Indicatori con parametri o output non banali: classificazione a mano.
# Tutto il resto (la stragrande maggioranza) prende un default ragionevole
# per categoria (vedi _default_kind_for_category) e un solo parametro
# "length" quando la funzione lo accetta.
OVERRIDES: dict[str, IndicatorSpec] = {
    "supertrend": IndicatorSpec("supertrend", "SuperTrend", "overlap", "overlay",
        [_p("length", "Periodo", 10, 2, 100), _p("multiplier", "Moltiplicatore ATR", 3.0, 0.5, 10)],
        ["SUPERT", "SUPERTd"]),
    "ichimoku": IndicatorSpec("ichimoku", "Ichimoku Kinko Hyo", "overlap", "overlay",
        [_p("tenkan", "Tenkan", 9, 2, 60), _p("kijun", "Kijun", 26, 2, 120), _p("senkou", "Senkou", 52, 2, 200)]),
    "vwma": IndicatorSpec("vwma", "VWMA", "overlap", "overlay", LENGTH(20)),
    "hilo": IndicatorSpec("hilo", "Gann HiLo", "overlap", "overlay",
        [_p("high_length", "Periodo massimi", 13, 2, 100), _p("low_length", "Periodo minimi", 21, 2, 100)]),
    "hl2": IndicatorSpec("hl2", "HL2", "overlap", "overlay", []),
    "hlc3": IndicatorSpec("hlc3", "HLC3", "overlap", "overlay", []),
    "ohlc4": IndicatorSpec("ohlc4", "OHLC4", "overlap", "overlay", []),
    "donchian": IndicatorSpec("donchian", "Canale di Donchian", "volatility", "overlay",
        [_p("lower_length", "Periodo minimo", 20, 2, 200), _p("upper_length", "Periodo massimo", 20, 2, 200)],
        ["DCL", "DCM", "DCU"]),
    "kc": IndicatorSpec("kc", "Canale di Keltner", "volatility", "overlay", LENGTH(20),
        ["KCL", "KCB", "KCU"]),
    "bbands": IndicatorSpec("bbands", "Bande di Bollinger", "volatility", "overlay", LENGTH(20),
        ["BBL", "BBM", "BBU"]),
    "accbands": IndicatorSpec("accbands", "Acceleration Bands", "volatility", "overlay", LENGTH(20),
        ["ACCBL", "ACCBM", "ACCBU"]),
    "chandelier_exit": IndicatorSpec("chandelier_exit", "Chandelier Exit", "volatility", "overlay",
        [_p("length", "Periodo", 22, 2, 100), _p("multiplier", "Moltiplicatore ATR", 3.0, 0.5, 10)]),
    "psar": IndicatorSpec("psar", "Parabolic SAR", "trend", "overlay",
        [_p("af0", "Accelerazione iniziale", 0.02, 0.001, 0.5), _p("max_af", "Accelerazione massima", 0.2, 0.01, 1)]),
    "vwap": IndicatorSpec("vwap", "VWAP", "overlap", "overlay", []),
    "alligator": IndicatorSpec("alligator", "Alligator (Williams)", "overlap", "overlay", []),
    "adx": IndicatorSpec("adx", "ADX / Directional Movement", "trend", "oscillator", LENGTH(14),
        ["ADX", "DMP", "DMN"]),
    "aroon": IndicatorSpec("aroon", "Aroon", "trend", "oscillator", LENGTH(14), ["AROOND", "AROONU"]),
    "macd": IndicatorSpec("macd", "MACD", "momentum", "oscillator",
        [_p("fast", "Veloce", 12, 2, 100), _p("slow", "Lenta", 26, 2, 200), _p("signal", "Segnale", 9, 2, 100)],
        ["MACD", "MACDh", "MACDs"]),
    "stoch": IndicatorSpec("stoch", "Stocastico", "momentum", "oscillator",
        [_p("k", "%K", 14, 2, 100), _p("d", "%D", 3, 2, 50)], ["STOCHk", "STOCHd"]),
    "rsi": IndicatorSpec("rsi", "RSI", "momentum", "oscillator", LENGTH(14)),
    "cci": IndicatorSpec("cci", "CCI", "momentum", "oscillator", LENGTH(20)),
    "willr": IndicatorSpec("willr", "Williams %R", "momentum", "oscillator", LENGTH(14)),
    "mfi": IndicatorSpec("mfi", "Money Flow Index", "volume", "oscillator", LENGTH(14)),
    "obv": IndicatorSpec("obv", "On Balance Volume", "volume", "oscillator", []),
    "cmf": IndicatorSpec("cmf", "Chaikin Money Flow", "volume", "oscillator", LENGTH(20)),
    "atr": IndicatorSpec("atr", "ATR", "volatility", "oscillator", LENGTH(14)),
    "chop": IndicatorSpec("chop", "Choppiness Index", "trend", "oscillator", LENGTH(14)),
    "vortex": IndicatorSpec("vortex", "Vortex Indicator", "trend", "oscillator", LENGTH(14), ["VTXP", "VTXM"]),
    "cdl_pattern": IndicatorSpec("cdl_pattern", "Pattern candlestick (tutti)", "candle", "overlay", []),
}

_OSCILLATOR_CATEGORIES = {"momentum", "trend", "volatility", "volume", "cycle", "performance", "statistics"}


def _default_kind_for(category: str) -> str:
    return "overlay" if category == "overlap" else "oscillator"


def _humanize(fn_name: str) -> str:
    return fn_name.replace("_", " ").upper()


def build_catalog() -> list[IndicatorSpec]:
    """Introspeziona pandas_ta.Category e produce una voce per ogni funzione,
    usando OVERRIDES dove serve una definizione precisa e un default
    ragionevole ovunque altro."""
    out: list[IndicatorSpec] = []
    seen: set[str] = set()
    for category, names in pandas_ta.Category.items():
        for name in names:
            if name in seen or name.startswith("_"):
                continue
            seen.add(name)
            if name in OVERRIDES:
                out.append(OVERRIDES[name])
                continue
            fn = getattr(pandas_ta, name, None)
            has_length = False
            if fn is not None:
                try:
                    has_length = "length" in fn.__code__.co_varnames
                except AttributeError:
                    has_length = False
            out.append(IndicatorSpec(
                id_=name,
                label=_humanize(name),
                category=category,
                kind=_default_kind_for(category),
                params=LENGTH() if has_length else [],
            ))
    out.sort(key=lambda s: (s.category, s.label))
    return out


CATALOG: list[IndicatorSpec] = build_catalog()
CATALOG_BY_ID: dict[str, IndicatorSpec] = {s.id: s for s in CATALOG}


def catalog_payload() -> list[dict]:
    return [
        {
            "id": s.id,
            "label": s.label,
            "category": s.category,
            "category_label": CATEGORY_LABELS.get(s.category, s.category),
            "kind": s.kind,
            "params": s.params,
        }
        for s in CATALOG
    ]


def compute_indicator(df: pd.DataFrame, indicator_id: str, params: dict) -> list[IndicatorSeries]:
    """Calcola un indicatore del catalogo e lo riporta nella stessa forma di
    compute_indicators(): una IndicatorSeries per ciascuna linea d'uscita,
    allineata per indice alle candele di df."""
    spec = CATALOG_BY_ID.get(indicator_id)
    if spec is None:
        raise ValueError(f"Indicatore sconosciuto: {indicator_id}")
    fn = getattr(df.ta, indicator_id, None)
    if fn is None:
        raise ValueError(f"pandas-ta non espone '{indicator_id}'")
    # Parte dai default dichiarati nello spec (senza, un indicatore invocato
    # senza parametri prenderebbe quelli di default di pandas-ta, che spesso
    # non coincidono con i nostri — es. supertrend length=7 contro il nostro 10).
    clean_params = {p["name"]: p["default"] for p in spec.params}
    allowed = {p["name"] for p in spec.params}
    for k, v in (params or {}).items():
        if k in allowed:
            clean_params[k] = v
    result = fn(**clean_params)
    n = len(df)
    # Alcuni indicatori (ichimoku) restituiscono una tupla di dataframe — il
    # secondo e' la proiezione futura fuori dall'asse delle candele attuali,
    # non allineabile 1:1: si prende solo il primo, l'unico della stessa
    # lunghezza della serie richiesta.
    if isinstance(result, tuple):
        result = next((r for r in result if hasattr(r, "__len__") and len(r) == n), result[0])
    out: list[IndicatorSeries] = []
    if isinstance(result, pd.Series) and len(result) == n:
        out.append(IndicatorSeries(
            name=spec.label,
            values=[None if pd.isna(v) else float(v) for v in result],
        ))
    elif isinstance(result, pd.DataFrame) and len(result) == n:
        wanted = spec.output_labels
        cols = result.columns
        if wanted:
            for w in wanted:
                col = next((c for c in cols if c.upper().startswith(w.upper())), None)
                if col is not None:
                    s = result[col]
                    out.append(IndicatorSeries(name=f"{spec.label} ({col})",
                                                values=[None if pd.isna(v) else float(v) for v in s]))
        else:
            for col in cols:
                s = result[col]
                if pd.api.types.is_numeric_dtype(s):
                    out.append(IndicatorSeries(name=f"{spec.label} ({col})",
                                                values=[None if pd.isna(v) else float(v) for v in s]))
    return out
