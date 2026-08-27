"""
Watchlist: tickers the user explicitly wants background Telegram alerts for,
independent of whatever ticker happens to be open in the browser — the
background loop in main.py checks these every 60s regardless of any open tab.
Each ticker can have multiple strategies watched independently (a checkbox
per strategy in the Alert tab), not just one.

Persisted to disk (backend/data/watchlist.json) so it survives server
restarts and redeploys — a Fly.io volume is mounted at that path in
production; in local dev it's just a plain file next to the venv.
"""

import json
import uuid
from pathlib import Path

from app.models import AssetType, CryptoExchange, WatchlistEntry

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


def list_entries() -> list[WatchlistEntry]:
    return list(_entries.values())


def add_entry(symbol: str, asset_type: AssetType, exchange: CryptoExchange = "mexc") -> WatchlistEntry:
    """Upsert: adding a ticker that's already tracked just returns the
    existing entry (with whatever strategies are already on it) instead of
    creating a duplicate row."""
    symbol = symbol.strip().upper()
    for entry in _entries.values():
        if entry.symbol == symbol and entry.asset_type == asset_type and entry.exchange == exchange:
            return entry

    entry = WatchlistEntry(
        id=uuid.uuid4().hex[:12],
        symbol=symbol,
        asset_type=asset_type,
        exchange=exchange,
        strategies=[],
        timeframes=["htf", "mtf", "ltf"],
    )
    _entries[entry.id] = entry
    _save()
    return entry


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
