"""Chart drawings per account, so they follow the user across devices.

Before this they lived only in the browser's localStorage: a phone and a
computer never showed the same lines, and private browsing lost them
(drawing tools plan, phase 4). The browser keeps its copy as a fast cache;
this store is the one that survives. One document per (user, chart key),
the newest `updated_at` wins.

Persisted to backend/data/drawings.json, same convention as favorites.py.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from app.atomic_write import write_text_atomic

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "drawings.json"

MAX_KEYS_PER_USER = 300
MAX_DRAWINGS_PER_KEY = 400
MAX_BYTES_PER_KEY = 200_000
_KEY_RE = re.compile(r"^(draw|fractal):[A-Za-z0-9_.:@/\-]{1,120}$")

_lock = threading.Lock()
_store: dict[str, dict[str, dict]] = {}


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(raw, dict):
        _store.update({u: v for u, v in raw.items() if isinstance(v, dict)})


def _save() -> None:
    write_text_atomic(_STORE_FILE, json.dumps(_store, separators=(",", ":")))


def valid_key(key: str) -> bool:
    return bool(_KEY_RE.match(key or ""))


def get(user_id: str, key: str) -> dict | None:
    doc = _store.get(user_id, {}).get(key)
    return dict(doc) if doc else None


def put(user_id: str, key: str, drawings: list, updated_at: int | None = None) -> dict:
    """Store `drawings` under `key` unless a newer copy is already there.
    Returns the copy that is now stored (the caller's or the newer one)."""
    if not valid_key(key):
        raise ValueError("invalid key")
    if not isinstance(drawings, list) or len(drawings) > MAX_DRAWINGS_PER_KEY:
        raise ValueError("too many drawings")
    body = json.dumps(drawings, separators=(",", ":"))
    if len(body) > MAX_BYTES_PER_KEY:
        raise ValueError("drawings too large")
    stamp = int(updated_at or time.time() * 1000)
    with _lock:
        mine = _store.setdefault(user_id, {})
        current = mine.get(key)
        if current and int(current.get("updated_at", 0)) > stamp:
            return dict(current)
        if key not in mine and len(mine) >= MAX_KEYS_PER_USER:
            oldest = min(mine, key=lambda k: int(mine[k].get("updated_at", 0)))
            mine.pop(oldest, None)
        mine[key] = {"drawings": json.loads(body), "updated_at": stamp}
        _save()
        return dict(mine[key])


_load()
