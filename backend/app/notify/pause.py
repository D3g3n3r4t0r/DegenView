"""Telegram notifications paused per chat, for a while or until resumed.

Asked on 23/10: "dei pulsanti attiva/disattiva notifiche Telegram sul sito
classico con l'obiettivo di poter mettere temporaneamente in pausa le
notifiche dei diversi gruppi". A pause is per chat id, so a group shared by
several accounts is quiet for all of them. Messages are not queued: they
are counted, and the resume says how many were skipped. Answers to what
someone writes to the bot still go out (telegram.send_to(force=True)).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.atomic_write import write_text_atomic

_STORE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "telegram_pauses.json"
_store: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _store
    if _store is None:
        try:
            _store = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _store = {}
    return _store


def _save() -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(_STORE_FILE, json.dumps(_load(), separators=(",", ":")))


def state(chat_id: str) -> dict | None:
    """The pause on this chat, or None. An expired one is still returned
    once with "expired": True, so the caller can say how much was skipped."""
    row = _load().get(str(chat_id))
    if not row:
        return None
    if row.get("until") and time.time() >= row["until"]:
        return {**row, "expired": True}
    return row


def is_paused(chat_id: str) -> bool:
    row = state(chat_id)
    return bool(row) and not row.get("expired")


def pause(chat_id: str, by: str, minutes: int | None) -> dict:
    row = {"since": time.time(), "until": time.time() + minutes * 60 if minutes else 0,
           "by": by, "skipped": _load().get(str(chat_id), {}).get("skipped", 0)}
    _load()[str(chat_id)] = row
    _save()
    return row


def resume(chat_id: str) -> dict | None:
    """Lift the pause; returns what it was (with its skipped count) or None."""
    row = _load().pop(str(chat_id), None)
    if row is not None:
        _save()
    return row


def skipped(chat_id: str) -> None:
    row = _load().get(str(chat_id))
    if row is not None:
        row["skipped"] = row.get("skipped", 0) + 1
        _save()


def resume_notice(row: dict) -> str:
    n = row.get("skipped", 0)
    if not n:
        return "▶️ Notifiche riprese."
    return f"▶️ Notifiche riprese: {n} {'messaggio non inviato' if n == 1 else 'messaggi non inviati'} durante la pausa."
