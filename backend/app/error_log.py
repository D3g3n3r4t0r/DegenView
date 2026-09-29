"""
Registro degli errori non gestiti — 500 veri, non i 4xx voluti dall'endpoint.

Vive sul volume (come issues.json), non in git: e' cronaca di quello che e'
successo davvero in produzione, non qualcosa che un deploy dovrebbe portare
o cancellare. Letto da un endpoint protetto (nessuna voce in _PUBLIC_PATHS,
quindi il cancello di seed-0031 lo copre gia') cosi' una sessione futura di
Claude puo' consultarlo con una sola richiesta HTTP, senza bisogno di SSH
sul server: lo stesso principio della bacheca segnalazioni, applicato agli
errori che nessuno ha ancora segnalato.
"""
from __future__ import annotations

import json
import time
import traceback
import uuid
from pathlib import Path
from app.atomic_write import write_text_atomic

_DATA_DIR = Path(__file__).resolve().parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "server_errors.json"

_MAX_ENTRIES = 200
# Non un errore per richiesta se lo stesso bug rifiorisce a ogni retry:
# stessa via + stesso tipo di eccezione non manda un secondo avviso Telegram
# prima che passi questa finestra, ma resta comunque scritta nel registro.
_ALERT_COOLDOWN_S = 5 * 60

_errors: list[dict] = []
_last_alerted: dict[str, float] = {}


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _errors.clear()
            _errors.extend(raw)
    except (json.JSONDecodeError, OSError):
        pass


def _save() -> None:
    try:
        write_text_atomic(_STORE_FILE, json.dumps(_errors[-_MAX_ENTRIES:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


_load()


def record(*, method: str, path: str, exc: Exception, user_id: str | None) -> tuple[dict, bool]:
    """Registra l'errore. Ritorna (voce, should_alert) — should_alert e' False
    se lo stesso tipo di errore sulla stessa via ha gia' avvisato di recente,
    cosi' un bug che rifiorisce a ogni richiesta non manda un Telegram al
    secondo invece di uno ogni cinque minuti."""
    entry = {
        "id": uuid.uuid4().hex[:8],
        "at": int(time.time()),
        "method": method,
        "path": path,
        "exc_type": type(exc).__name__,
        "message": str(exc)[:500],
        # Le ultime righe bastano a capire dove si e' rotto senza portarsi
        # dietro chilometri di stack di librerie terze.
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:],
        "user_id": user_id,
    }
    _errors.append(entry)
    _save()

    key = f"{method} {path} {entry['exc_type']}"
    now = time.time()
    should_alert = now - _last_alerted.get(key, 0) > _ALERT_COOLDOWN_S
    if should_alert:
        _last_alerted[key] = now
    return entry, should_alert


def recent(limit: int = 50) -> list[dict]:
    return list(reversed(_errors[-limit:]))
