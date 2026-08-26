"""
In-memory watchlist: symbols the user explicitly wants background Telegram
alerts for, independent of whatever ticker happens to be open in the browser.
Resets on server restart, consistent with the rest of this app's state.
"""

import uuid

from app.models import AssetType, TimeframeKey, WatchlistEntry

_entries: dict[str, WatchlistEntry] = {}


def list_entries() -> list[WatchlistEntry]:
    return list(_entries.values())


def add_entry(
    symbol: str,
    asset_type: AssetType,
    strategy_name: str,
    timeframes: list[TimeframeKey],
) -> WatchlistEntry:
    entry = WatchlistEntry(
        id=uuid.uuid4().hex[:12],
        symbol=symbol.strip().upper(),
        asset_type=asset_type,
        strategy_name=strategy_name,
        timeframes=timeframes,
        enabled=True,
    )
    _entries[entry.id] = entry
    return entry


def remove_entry(entry_id: str) -> None:
    _entries.pop(entry_id, None)


def set_enabled(entry_id: str, enabled: bool) -> WatchlistEntry | None:
    entry = _entries.get(entry_id)
    if entry is None:
        return None
    updated = entry.model_copy(update={"enabled": enabled})
    _entries[entry_id] = updated
    return updated
