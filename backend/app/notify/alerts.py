"""
Tracks which strategy signals have already been seen, so Telegram alerts fire
only for genuinely new events (never the whole history on first analysis of a
symbol). In-memory only — resets on server restart, consistent with the rest
of this app's caches; acceptable for a single-user local tool.
"""

from app.models import StrategySignal, StrategyState

_seen_signal_keys: set[str] = set()
_seeded_symbol_timeframes: set[str] = set()


def _signal_key(symbol: str, timeframe_key: str, signal: StrategySignal) -> str:
    return f"{symbol}|{timeframe_key}|{signal.time}|{signal.type}"


def find_new_signals(symbol: str, timeframe_key: str, strategy: StrategyState) -> list[StrategySignal]:
    scope_key = f"{symbol}|{timeframe_key}|{strategy.name}"
    is_first_pass = scope_key not in _seeded_symbol_timeframes

    fresh: list[StrategySignal] = []
    for signal in strategy.signals:
        key = _signal_key(symbol, timeframe_key, signal)
        if key in _seen_signal_keys:
            continue
        _seen_signal_keys.add(key)
        if not is_first_pass:
            fresh.append(signal)

    _seeded_symbol_timeframes.add(scope_key)
    return fresh


_LABEL_IT = {"htf": "HTF", "mtf": "MTF", "ltf": "LTF"}


def format_signal_message(symbol: str, timeframe_key: str, strategy_name: str, signal: StrategySignal) -> str:
    tf_label = _LABEL_IT.get(timeframe_key, timeframe_key.upper())
    return (
        f"📊 <b>{symbol}</b> [{tf_label}] — {strategy_name}\n"
        f"{signal.label}\n"
        f"Prezzo: {signal.price:g}\n\n"
        f"<i>Notifica su una condizione tecnica rilevata, non è consulenza finanziaria.</i>"
    )
