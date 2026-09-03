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

# Quante barre indietro un segnale puo' essere e restare degno di una notifica.
# La deduplica da sola non basta a garantirlo: dice se un segnale e' gia' stato
# visto, non se vale ancora la pena mandarlo. Se il suo stato si perde — un
# prune, un file cancellato, o semplicemente piu' segnali storici di prima nella
# stessa risposta — ogni segnale mai notificato diventa "nuovo" e parte tutto
# insieme. E' successo davvero: alzare il tetto dei segnali restituiti da 30 a
# 10 000 (per mostrare i trade vecchi sul grafico, che leggono la stessa
# funzione) ha fatto arrivare una ventina di notifiche con prezzi di anni
# diversi. Un limite d'eta' rende quella classe di guasti impossibile invece che
# improbabile: un segnale del 2022 non e' azionabile oggi, qualunque cosa dica
# la deduplica.
_MAX_SIGNAL_AGE_BARS = 3
_MIN_SIGNAL_AGE_WINDOW_S = 3600          # almeno un'ora, sui timeframe stretti
_MAX_SIGNAL_AGE_WINDOW_S = 7 * 86400     # mai piu' di una settimana

_INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000,
}


def _max_signal_age_s(interval: str) -> int:
    """Finestra entro cui un segnale e' ancora azionabile, per quel timeframe."""
    bar = _INTERVAL_SECONDS.get(interval, 86400)
    return int(min(max(bar * _MAX_SIGNAL_AGE_BARS, _MIN_SIGNAL_AGE_WINDOW_S),
                   _MAX_SIGNAL_AGE_WINDOW_S))


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

    # Guardia d'eta' PRIMA della deduplica, non dopo: i segnali vecchi vanno
    # comunque registrati come visti (cosi' non diventano "nuovi" piu' avanti),
    # ma non devono mai finire in `fresh`.
    cutoff = int(time.time()) - _max_signal_age_s(interval)

    fresh: list[StrategySignal] = []
    for signal in strategy.signals:
        key = _signal_key(symbol, interval, strategy.name, signal)
        too_old = signal.time < cutoff

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
                if not is_first_pass and not too_old:
                    fresh.append(signal)
        else:
            if key in _seen:
                continue
            _seen[key] = int(time.time())
            _additions_since_prune += 1
            if not is_first_pass and not too_old:
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
