"""
Watchlist: symbols the user explicitly wants background Telegram alerts for,
independent of whatever ticker happens to be open in the browser — the
background loop in main.py checks these every 60s regardless of any open tab.

Persisted to disk (backend/data/watchlist.json) so it survives server
restarts and redeploys — a Fly.io volume is mounted at that path in
production; in local dev it's just a plain file next to the venv.
"""

import json
import uuid
from pathlib import Path

from app.models import AssetType, CryptoExchange, TimeframeKey, WatchlistEntry

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


def add_entry(
    symbol: str,
    asset_type: AssetType,
    strategy_name: str,
    timeframes: list[TimeframeKey],
    exchange: CryptoExchange = "mexc",
) -> WatchlistEntry:
    entry = WatchlistEntry(
        id=uuid.uuid4().hex[:12],
        symbol=symbol.strip().upper(),
        asset_type=asset_type,
        exchange=exchange,
        strategy_name=strategy_name,
        timeframes=timeframes,
        enabled=True,
    )
    _entries[entry.id] = entry
    _save()
    return entry


def remove_entry(entry_id: str) -> None:
    if _entries.pop(entry_id, None) is not None:
        _save()


def set_enabled(entry_id: str, enabled: bool) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    updated = entry.model_copy(update={"enabled": enabled})
    _entries[entry_id] = updated
    _save()
    return updated
