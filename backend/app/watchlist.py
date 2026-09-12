"""
Watchlist: tickers a user explicitly wants background Telegram alerts for,
independent of whatever ticker happens to be open in the browser — the
background loop in main.py checks these every 60s regardless of any open
tab. Each ticker can have multiple strategies watched independently (a
checkbox per strategy in the Alert tab), not just one. Every entry belongs
to one owner_id (a logged-in user) — alerts route to that user's own
Telegram chat_id, not a single shared broadcast list.

Persisted to disk (backend/data/watchlist.json) so it survives server
restarts and redeploys — a Fly.io volume is mounted at that path in
production; in local dev it's just a plain file next to the venv.
"""

import json
import uuid
from pathlib import Path

from app.models import AssetType, CryptoExchange, WatchlistEntry
from app.timeframes import IntervalChoice

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "watchlist.json"

_entries: dict[str, WatchlistEntry] = {}


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for item in raw:
        try:
            entry = WatchlistEntry(**item)
            _entries[entry.id] = entry
        except (TypeError, ValueError):
            continue


def _save() -> None:
    payload = [e.model_dump() for e in _entries.values()]
    _STORE_FILE.write_text(json.dumps(payload), encoding="utf-8")


_load()


def list_entries(owner_id: str | None = None) -> list[WatchlistEntry]:
    entries = list(_entries.values())
    if owner_id is not None:
        entries = [e for e in entries if e.owner_id == owner_id]
    return entries


def get_entry(entry_id: str) -> WatchlistEntry | None:
    return _entries.get(entry_id)


def add_entry(
    owner_id: str,
    symbol: str,
    asset_type: AssetType,
    exchange: CryptoExchange = "mexc",
    interval: IntervalChoice = "1d",
    on_close: bool = True,
) -> WatchlistEntry:
    """Upsert: adding a ticker that's already tracked by this owner just
    returns the existing entry (with whatever strategies/interval are
    already on it) instead of creating a duplicate row."""
    symbol = symbol.strip().upper()
    for entry in _entries.values():
        if (
            entry.owner_id == owner_id
            and entry.symbol == symbol
            and entry.asset_type == asset_type
            and entry.exchange == exchange
        ):
            return entry

    entry = WatchlistEntry(
        id=uuid.uuid4().hex[:12],
        owner_id=owner_id,
        symbol=symbol,
        asset_type=asset_type,
        exchange=exchange,
        strategies=[],
        interval=interval,
        on_close=on_close,
    )
    _entries[entry.id] = entry
    _save()
    return entry


def set_interval(entry_id: str, interval: IntervalChoice) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    updated = entry.model_copy(update={"interval": interval})
    _entries[entry_id] = updated
    _save()
    return updated


def remove_entry(entry_id: str) -> None:
    if _entries.pop(entry_id, None) is not None:
        _save()


def set_strategy_enabled(entry_id: str, strategy_name: str, enabled: bool) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    strategies = list(entry.strategies)
    if enabled and strategy_name not in strategies:
        strategies.append(strategy_name)
    elif not enabled and strategy_name in strategies:
        strategies.remove(strategy_name)
    else:
        return entry  # no-op, already in the requested state
    updated = entry.model_copy(update={"strategies": strategies})
    _entries[entry_id] = updated
    _save()
    return updated


def set_on_close(entry_id: str, on_close: bool) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    updated = entry.model_copy(update={"on_close": on_close})
    _entries[entry_id] = updated
    _save()
    return updated


def set_strategy_params(entry_id: str, strategy_name: str, params: dict | None) -> WatchlistEntry | None:
    """params=None (or {}) resets this strategy back to its global defaults."""
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    strategy_params = dict(entry.strategy_params)
    if params:
        strategy_params[strategy_name] = params
    else:
        strategy_params.pop(strategy_name, None)
    updated = entry.model_copy(update={"strategy_params": strategy_params})
    _entries[entry_id] = updated
    _save()
    return updated


def set_alert_frequency(entry_id: str, strategy_name: str, frequency: str) -> WatchlistEntry | None:
    """frequency: "once" | "every". None resets to default ("every")."""
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    freq_map = dict(entry.alert_frequency)
    if frequency in ("once", "every"):
        freq_map[strategy_name] = frequency
    else:
        freq_map.pop(strategy_name, None)
    updated = entry.model_copy(update={"alert_frequency": freq_map})
    _entries[entry_id] = updated
    _save()
    return updated


def set_auto_trade(entry_id: str, strategy_name: str, enabled: bool) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    auto_trade = dict(entry.auto_trade)
    if enabled:
        auto_trade[strategy_name] = True
    else:
        auto_trade.pop(strategy_name, None)
    updated = entry.model_copy(update={"auto_trade": auto_trade})
    _entries[entry_id] = updated
    _save()
    return updated


def set_size_cap(entry_id: str, strategy_name: str, cap_usdt: float | None) -> WatchlistEntry | None:
    """cap_usdt None o <= 0 rimuove il tetto (torna al comportamento di
    sempre: usa il size_mode/size_value della credenziale exchange senza
    limiti aggiuntivi)."""
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    caps = dict(entry.size_cap_usdt)
    if cap_usdt and cap_usdt > 0:
        caps[strategy_name] = cap_usdt
    else:
        caps.pop(strategy_name, None)
    updated = entry.model_copy(update={"size_cap_usdt": caps})
    _entries[entry_id] = updated
    _save()
    return updated


def set_market(entry_id: str, strategy_name: str, market: str) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    markets = dict(entry.market)
    if market == "spot":
        markets.pop(strategy_name, None)  # spot e' il default implicito
    else:
        markets[strategy_name] = market
    updated = entry.model_copy(update={"market": markets})
    _entries[entry_id] = updated
    _save()
    return updated


def set_strategy_interval(entry_id: str, strategy_name: str, interval: str | None) -> WatchlistEntry | None:
    """interval=None resets this strategy to use the entry's default interval."""
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    si = dict(entry.strategy_intervals)
    if interval:
        si[strategy_name] = interval
    else:
        si.pop(strategy_name, None)
    updated = entry.model_copy(update={"strategy_intervals": si})
    _entries[entry_id] = updated
    _save()
    return updated
