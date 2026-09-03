"""
Tracks which strategy signals have already been seen so Telegram alerts fire
only for genuinely new events. Persisted to disk so dedup survives restarts.
Also tracks last-alert time and total count per (entry_id, strategy_name).
"""

import json
import time
from pathlib import Path

from app.models import StrategySignal, StrategyState

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_SEEN_FILE = _DATA_DIR / "seen_signals.json"
_STATS_FILE = _DATA_DIR / "alert_stats.json"

# { "symbol|interval|strategy_name|signal_time|signal_type" -> unix_seconds_ts }
_seen: dict[str, int] = {}

# { "entry_id|strategy_name" -> {"last_ts": int, "count": int} }
_stats: dict[str, dict] = {}

_seeded_scopes: set[str] = set()

_MAX_SEEN_AGE_DAYS = 45
_PRUNE_EVERY = 200   # prune after this many additions


def _load() -> None:
    if _SEEN_FILE.exists():
        try:
            raw = json.loads(_SEEN_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _seen.update(raw)
        except (json.JSONDecodeError, OSError):
            pass
    if _STATS_FILE.exists():
        try:
            raw = json.loads(_STATS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _stats.update(raw)
        except (json.JSONDecodeError, OSError):
            pass


def _prune() -> None:
    cutoff = time.time() - _MAX_SEEN_AGE_DAYS * 86400
    stale = [k for k, ts in _seen.items() if ts < cutoff]
    for k in stale:
        del _seen[k]


def _save_seen() -> None:
    try:
        _SEEN_FILE.write_text(json.dumps(_seen), encoding="utf-8")
    except OSError:
        pass


def _save_stats() -> None:
    try:
        _STATS_FILE.write_text(json.dumps(_stats), encoding="utf-8")
    except OSError:
        pass


_load()
_additions_since_prune = 0


def _signal_key(symbol: str, interval: str, strategy_name: str, signal: StrategySignal) -> str:
    return f"{symbol}|{interval}|{strategy_name}|{signal.time}|{signal.type}"


def find_new_signals(
    symbol: str,
    interval: str,
    strategy: StrategyState,
    frequency: str = "every",
    entry_id: str = "",
) -> list[StrategySignal]:
    """Return signals that haven't been seen before.

    frequency:
      "every"  — alert every time the signal appears (default)
      "once"   — alert only the first time per (symbol, interval, strategy, signal_type)
    """
    global _additions_since_prune
    scope_key = f"{symbol}|{interval}|{strategy.name}"
    is_first_pass = scope_key not in _seeded_scopes

    fresh: list[StrategySignal] = []
    for signal in strategy.signals:
        key = _signal_key(symbol, interval, strategy.name, signal)

        if frequency == "once":
            # For "once", use a type-level key (ignore signal.time) so we
            # never re-alert for the same signal direction.
            once_key = f"{symbol}|{interval}|{strategy.name}|ONCE|{signal.type}"
            if once_key in _seen:
                continue
            if key not in _seen:
                _seen[key] = int(time.time())
                _seen[once_key] = int(time.time())
                _additions_since_prune += 1
                if not is_first_pass:
                    fresh.append(signal)
        else:
            if key in _seen:
                continue
            _seen[key] = int(time.time())
            _additions_since_prune += 1
            if not is_first_pass:
                fresh.append(signal)

    _seeded_scopes.add(scope_key)

    if fresh:
        if _additions_since_prune >= _PRUNE_EVERY:
            _prune()
            _additions_since_prune = 0
        _save_seen()

    return fresh


def record_alert_sent(entry_id: str, strategy_name: str) -> None:
    """Update last-trigger time and count for a watchlist entry+strategy pair."""
    key = f"{entry_id}|{strategy_name}"
    bucket = _stats.get(key, {"last_ts": 0, "count": 0})
    bucket["last_ts"] = int(time.time())
    bucket["count"] = bucket.get("count", 0) + 1
    _stats[key] = bucket
    _save_stats()


def get_alert_stats(entry_id: str, strategy_name: str) -> dict:
    """Return {"last_ts": int, "count": int} for a watchlist entry+strategy."""
    return _stats.get(f"{entry_id}|{strategy_name}", {"last_ts": 0, "count": 0})


def get_all_stats_for_entry(entry_id: str) -> dict[str, dict]:
    """Return all strategy stats for a given watchlist entry."""
    prefix = f"{entry_id}|"
    return {
        k[len(prefix):]: v
        for k, v in _stats.items()
        if k.startswith(prefix)
    }


_LABEL_IT = {"htf": "HTF", "mtf": "MTF", "ltf": "LTF"}


def format_signal_message(symbol: str, interval: str, strategy_name: str, signal: StrategySignal) -> str:
    tf_label = _LABEL_IT.get(interval, interval.upper())
    return (
        f"📊 <b>{symbol}</b> [{tf_label}] — {strategy_name}\n"
        f"{signal.label}\n"
        f"Prezzo: {signal.price:g}\n\n"
        f"<i>Notifica su una condizione tecnica rilevata, non è consulenza finanziaria.</i>"
    )
