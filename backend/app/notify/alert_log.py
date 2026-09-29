"""
Storico persistente degli alert inviati via Telegram.
Limite: 500 voci per utente (FIFO). Sopravvive ai restart.
"""

import json
import time
import uuid
from pathlib import Path
from app.atomic_write import write_text_atomic

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "alert_log.json"

_MAX_PER_USER = 500

# { owner_id: [entry, ...] }  newest-last
_log: dict[str, list[dict]] = {}


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            _log.update(raw)
    except (json.JSONDecodeError, OSError):
        pass


def _save() -> None:
    try:
        write_text_atomic(_STORE_FILE, json.dumps(_log), encoding="utf-8")
    except OSError:
        pass


_load()


def append_entry(
    owner_id: str,
    symbol: str,
    interval: str,
    strategy_name: str,
    signal_type: str,
    price: float,
    label: str,
    chat_id: str = "",
) -> None:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": int(time.time()),
        "symbol": symbol,
        "interval": interval,
        "strategy_name": strategy_name,
        "signal_type": signal_type,
        "price": price,
        "label": label,
        "chat_id": chat_id,
    }
    bucket = _log.setdefault(owner_id, [])
    bucket.append(entry)
    if len(bucket) > _MAX_PER_USER:
        _log[owner_id] = bucket[-_MAX_PER_USER:]
    _save()


def list_entries(owner_id: str, limit: int = 100, since: int = 0) -> list[dict]:
    bucket = _log.get(owner_id, [])
    if since:
        bucket = [e for e in bucket if e["ts"] > since]
    return list(reversed(bucket[-limit:]))  # newest first


def clear(owner_id: str) -> None:
    _log.pop(owner_id, None)
    _save()
