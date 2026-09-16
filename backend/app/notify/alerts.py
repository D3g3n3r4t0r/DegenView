"""
Tracks which strategy signals have already been seen so Telegram alerts fire
only for genuinely new events. Persisted to disk so dedup survives restarts.
Also tracks last-alert time and total count per (entry_id, strategy_name).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.models import StrategySignal, StrategyState

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_SEEN_FILE = _DATA_DIR / "seen_signals.json"
_STATS_FILE = _DATA_DIR / "alert_stats.json"
_ARMED_FILE = _DATA_DIR / "armed_alerts.json"

# { "symbol|interval|strategy_name|signal_time|signal_type" -> unix_seconds_ts }
_seen: dict[str, int] = {}

# { "entry_id|strategy_name" -> {"last_ts": int, "count": int} }
_stats: dict[str, dict] = {}

# { "entry_id|strategy_name" -> unix_seconds } — quando quell'alert e' stato armato.
# Un alert notifica solo cio' che accade DOPO che l'hai chiesto: un segnale di
# ieri non diventa una notifica solo perche' oggi hai attivato la strategia.
# Persistito, perche' un riavvio non deve riaprire il passato.
_armed: dict[str, int] = {}

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
    if _ARMED_FILE.exists():
        try:
            raw = json.loads(_ARMED_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _armed.update({k: int(v) for k, v in raw.items()})
        except (json.JSONDecodeError, OSError, ValueError):
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


def _save_armed() -> None:
    try:
        _ARMED_FILE.write_text(json.dumps(_armed), encoding="utf-8")
    except OSError:
        pass


def armed_at(entry_id: str, strategy_name: str) -> int:
    """Da quando quell'alert e' attivo, registrandolo alla prima chiamata.

    Restituisce 0 senza entry_id: senza una coppia da identificare non c'e'
    nulla da armare, e resta valida la sola finestra d'eta'.
    """
    if not entry_id:
        return 0
    key = f"{entry_id}|{strategy_name}"
    ts = _armed.get(key)
    if ts is None:
        ts = int(time.time())
        _armed[key] = ts
        _save_armed()
    return ts


def disarm(entry_id: str, strategy_name: str = "") -> None:
    """Dimentica l'armamento quando l'alert viene tolto, cosi' riattivarlo
    riparte da adesso invece che dalla prima volta."""
    prefix = f"{entry_id}|"
    keys = [k for k in _armed
            if k == f"{entry_id}|{strategy_name}" or (not strategy_name and k.startswith(prefix))]
    for k in keys:
        del _armed[k]
    if keys:
        _save_armed()


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

    # Due sbarramenti, contro due guasti diversi, entrambi prima della deduplica.
    # I segnali esclusi vanno comunque registrati come visti, o tornerebbero a
    # sembrare nuovi appena una delle due soglie si sposta.
    #
    #  - armed_at: un alert notifica solo cio' che accade DOPO che l'hai
    #    chiesto. Un segnale di ieri non diventa una notifica perche' oggi hai
    #    attivato la strategia.
    #  - finestra d'eta': se il servizio e' stato fermo una settimana, alla
    #    ripartenza non deve arrivare tutto l'arretrato in blocco, per quanto
    #    successivo all'armamento.
    now = int(time.time())
    cutoff_age = now - _max_signal_age_s(interval)
    cutoff_armed = armed_at(entry_id, strategy.name)
    cutoff = max(cutoff_age, cutoff_armed)

    fresh: list[StrategySignal] = []
    for signal in strategy.signals:
        key = _signal_key(symbol, interval, strategy.name, signal)
        too_old = signal.time <= cutoff

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

_MONTHS_IT = ["gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic"]


def _when_phrase(ts: int, interval: str, now: int) -> str:
    """Quando e' successo, in data e in "quanto fa".

    Le due cose insieme perche' rispondono a domande diverse: la data dice su
    quale candela, "due giorni fa" dice se ha ancora senso guardarla.
    """
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    stamp = f"{d.day} {_MONTHS_IT[d.month - 1]}"
    # Sui timeframe intraday l'ora e' meta' dell'informazione; su daily e oltre
    # e' rumore (la candela e' il giorno).
    if _INTERVAL_SECONDS.get(interval, 86400) < 86400:
        stamp += f" {d:%H:%M} UTC"

    delta = max(0, now - ts)
    if delta < 3600:
        rel = "meno di un'ora fa"
    elif delta < 86400:
        hours = delta // 3600
        rel = "un'ora fa" if hours == 1 else f"{hours} ore fa"
    else:
        days = delta // 86400
        rel = "un giorno fa" if days == 1 else f"{days} giorni fa"
    return f"{stamp}, {rel}"


def format_signal_message(
    symbol: str,
    interval: str,
    strategy_name: str,
    signal: StrategySignal,
    current_price: float | None = None,
    now: int | None = None,
) -> str:
    """Il messaggio dice sempre QUANDO, non solo quanto.

    Prima mostrava `signal.price` da solo: il prezzo della candela del
    segnale, presentato come se fosse quello di adesso. Un segnale puo'
    arrivare fino a _MAX_SIGNAL_AGE_BARS barre dopo essersi formato — su un
    daily, giorni — e in mezzo il prezzo si muove. E' successo davvero su
    INJUSDT: notifica con "Prezzo: 6.285", che era la chiusura di due giorni
    prima, mentre il mercato stava a 5.42 dopo un -13,5%. Letto cosi'
    sembrava una strategia che compra dentro una correzione; era invece un
    ingresso generato prima della correzione e consegnato dopo.
    """
    now = int(time.time()) if now is None else now
    tf_label = _LABEL_IT.get(interval, interval.upper())
    lines = [
        f"📊 <b>{symbol}</b> [{tf_label}] — {strategy_name}",
        signal.label,
        f"Prezzo al segnale: {signal.price:g} — {_when_phrase(signal.time, interval, now)}",
    ]
    # Il prezzo di adesso solo quando dice qualcosa: su un segnale appena nato
    # ripetere lo stesso numero due volte e' rumore, non trasparenza.
    if current_price and signal.price:
        drift = (current_price - signal.price) / signal.price
        if abs(drift) >= 0.002:
            lines.append(f"Prezzo ora: {current_price:g} ({drift * 100:+.1f}%)")
    lines.append("")
    lines.append("<i>Notifica su una condizione tecnica rilevata, non è consulenza finanziaria.</i>")
    return "\n".join(lines)
