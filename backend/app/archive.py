"""
Archivio delle strategie: la fotografia di un backtest, tenuta da parte.

Serve a rispondere a "che cosa avevo attivato, e con quali numeri", mesi dopo.
Un risultato di ottimizzazione vive finche' la pagina resta aperta; l'alert
invece continua a lavorare per settimane, e senza un archivio non resta traccia
della configurazione con cui e' stato acceso ne' di cosa prometteva.

Due decisioni che vale la pena dichiarare:

  * I numeri li calcola il server, non li accetta dal client. Un archivio che
    accetta le metriche che gli vengono passate e' un archivio di affermazioni,
    non di misure.
  * Si conservano parametri e metriche, non l'elenco dei trade. I parametri
    permettono di rieseguire il backtest quando serve; l'elenco dei trade
    sarebbe grande, invecchierebbe (i dati storici si estendono) e darebbe
    l'illusione di un dettaglio che non e' stato verificato di nuovo.

Le voci in stato "in corso" esistono perche' la fotografia si scatta in
background: l'attivazione di un alert non deve aspettare un backtest.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "strategy_archive.json"

_MAX_PER_OWNER = 200

Source = Literal["alert", "manuale", "ottimizzazione"]
State = Literal["in corso", "pronto", "fallito"]

_entries: list[dict] = []


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _entries.clear()
            _entries.extend(x for x in raw if isinstance(x, dict))
    except (json.JSONDecodeError, OSError):
        pass


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_entries, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


_load()


def _trim(owner_id: str) -> None:
    mine = [i for i, e in enumerate(_entries) if e.get("owner_id") == owner_id]
    excess = len(mine) - _MAX_PER_OWNER
    for i in reversed(mine[:excess] if excess > 0 else []):
        del _entries[i]


def create(
    owner_id: str,
    symbol: str,
    asset_type: str,
    exchange: str,
    interval: str,
    strategy_name: str,
    params: dict,
    backtest_params: dict,
    *,
    source: Source = "manuale",
    watchlist_entry_id: str = "",
    note: str = "",
    optimizer: dict | None = None,
) -> dict:
    """Registra la voce subito, senza numeri: li riempie `attach_result`.

    Separati di proposito: l'attivazione di un alert deve restare immediata, e
    una voce "in corso" dice comunque che quella configurazione e' stata
    attivata in quel momento — che e' meta' dell'informazione cercata.
    """
    entry = {
        "id": uuid.uuid4().hex[:12],
        "owner_id": owner_id,
        "created_at": int(time.time()),
        "symbol": symbol.strip().upper(),
        "asset_type": asset_type,
        "exchange": exchange,
        "interval": interval,
        "strategy_name": strategy_name,
        "params": dict(params or {}),
        "backtest_params": dict(backtest_params or {}),
        "source": source,
        "watchlist_entry_id": watchlist_entry_id,
        "note": (note or "").strip()[:500],
        # Come si e' arrivati a questi parametri: modalita', quanti backtest,
        # il verdetto del gate, la stabilita' misurata. Senza, fra sei mesi
        # l'archivio direbbe quali parametri erano attivi ma non se valevano
        # qualcosa — e i due risultati con lo stesso rendimento, uno enumerato
        # e uno sorteggiato, sembrerebbero la stessa cosa.
        "optimizer": dict(optimizer or {}),
        "state": "in corso",
        "metrics": None,
        "error": "",
    }
    _entries.append(entry)
    _trim(owner_id)
    _save()
    return entry


def attach_result(entry_id: str, metrics: dict) -> dict | None:
    for e in _entries:
        if e["id"] != entry_id:
            continue
        e["metrics"] = metrics
        e["state"] = "pronto"
        e["error"] = ""
        _save()
        return e
    return None


def attach_error(entry_id: str, message: str) -> dict | None:
    """Un fallimento resta scritto sulla voce invece di cancellarla.

    Una voce sparita non si distingue da una mai creata; una voce "fallito"
    dice che quella configurazione e' stata attivata e che il backtest, quel
    giorno, non e' riuscito.
    """
    for e in _entries:
        if e["id"] != entry_id:
            continue
        e["state"] = "fallito"
        e["error"] = (message or "")[:300]
        _save()
        return e
    return None


def list_for(owner_id: str) -> list[dict]:
    """Le piu' recenti per prime. A parita' di secondo decide l'ordine di
    inserimento: due voci create nello stesso istante — succede attivando piu'
    strategie insieme — altrimenti uscirebbero in ordine invertito."""
    mine = [(i, e) for i, e in enumerate(_entries) if e.get("owner_id") == owner_id]
    mine.sort(key=lambda t: (t[1].get("created_at", 0), t[0]), reverse=True)
    return [e for _, e in mine]


def ready_entries() -> list[dict]:
    """Every owner's finished snapshots — the radar tests each configuration
    on young on-chain tokens."""
    return [e for e in _entries if e.get("state") == "pronto"]


def get(entry_id: str, owner_id: str) -> dict | None:
    for e in _entries:
        if e["id"] == entry_id and e.get("owner_id") == owner_id:
            return e
    return None


def set_note(entry_id: str, owner_id: str, note: str) -> dict | None:
    e = get(entry_id, owner_id)
    if e is None:
        return None
    e["note"] = (note or "").strip()[:500]
    _save()
    return e


def remove(entry_id: str, owner_id: str) -> bool:
    for i, e in enumerate(_entries):
        if e["id"] == entry_id and e.get("owner_id") == owner_id:
            del _entries[i]
            _save()
            return True
    return False


def already_archived(owner_id: str, watchlist_entry_id: str, strategy_name: str,
                     params: dict, within_s: int = 86400) -> bool:
    """Vero se la stessa attivazione e' gia' stata fotografata di recente.

    Spegnere e riaccendere un alert non deve riempire l'archivio di copie
    identiche; una riattivazione con parametri diversi invece e' una voce
    nuova, perche' e' un'altra strategia.
    """
    cutoff = int(time.time()) - within_s
    for e in _entries:
        if (
            e.get("owner_id") == owner_id
            and e.get("watchlist_entry_id") == watchlist_entry_id
            and e.get("strategy_name") == strategy_name
            and e.get("created_at", 0) >= cutoff
            and e.get("params") == dict(params or {})
        ):
            return True
    return False
