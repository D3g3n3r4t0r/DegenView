"""
Diario degli ordini automatici: cosa e' stato provato, e cosa e' successo.

Esiste per un guasto preciso. Il trading automatico non ha mai piazzato un
ordine e nessuno se n'e' accorto: nessun errore, nessun log visibile, nessuna
notifica — semplicemente niente. Un percorso che, quando funziona, non dice
nulla, e quando e' morto dice la stessa identica cosa.

Qui viene registrato ogni tentativo, compresi quelli che non sono nemmeno
partiti e il motivo. La differenza fra "non ci sono stati segnali" e "c'era un
segnale e l'ordine non e' partito perche' le chiavi mancano" e' l'intera
informazione utile, e prima non era da nessuna parte.

Le voci "saltato" si registrano solo per chi ha davvero configurato l'exchange:
per tutti gli altri non c'e' niente da segnalare, e riempire il diario di
"trading non configurato" lo renderebbe illeggibile proprio a chi lo consulta.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal
from app.atomic_write import write_text_atomic

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "trading_journal.json"

_MAX_PER_OWNER = 200

Outcome = Literal["eseguito", "fallito", "saltato"]

_ENTRY_SIGNALS = {"entry_long", "entry_short", "flip_to_long", "flip_to_short"}
_EXIT_SIGNALS = {"exit_long", "exit_short", "flip_to_long", "flip_to_short"}

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
        write_text_atomic(_STORE_FILE, json.dumps(_entries, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


_load()


def _trim(owner_id: str) -> None:
    mine = [i for i, e in enumerate(_entries) if e.get("owner_id") == owner_id]
    excess = len(mine) - _MAX_PER_OWNER
    for i in reversed(mine[:excess] if excess > 0 else []):
        del _entries[i]


def _find_open_entry(owner_id: str, symbol: str, strategy_name: str) -> dict | None:
    """Trova l'ultima entrata ancora aperta (senza exit_id) per owner+symbol+strategy."""
    for e in reversed(_entries):
        if (
            e.get("owner_id") == owner_id
            and e.get("symbol") == symbol
            and e.get("strategy_name") == strategy_name
            and e.get("signal_type") in _ENTRY_SIGNALS
            and e.get("outcome") == "eseguito"
            and "exit_id" not in e
            and e.get("price")
        ):
            return e
    return None


def record(
    owner_id: str,
    *,
    symbol: str,
    exchange: str,
    strategy_name: str,
    signal_type: str,
    outcome: Outcome,
    detail: str = "",
    price: float | None = None,
) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "owner_id": owner_id,
        "ts": int(time.time()),
        "symbol": symbol,
        "exchange": exchange,
        "strategy_name": strategy_name,
        "signal_type": signal_type,
        "outcome": outcome,
        "detail": (detail or "")[:400],
        "price": price,
    }

    # Collega l'uscita all'entrata aperta e calcola il P&L reale.
    if outcome == "eseguito" and signal_type in _EXIT_SIGNALS and price:
        open_entry = _find_open_entry(owner_id, symbol, strategy_name)
        if open_entry and open_entry.get("price"):
            ep = open_entry["price"]
            # Long: si guadagna salendo. Short: si guadagna scendendo.
            # La direzione la dice il signal_type dell'entrata.
            is_long = open_entry["signal_type"] in ("entry_long", "flip_to_long")
            pnl_pct = ((price - ep) / ep) * (1 if is_long else -1)
            entry["pnl_pct"] = round(pnl_pct * 100, 2)
            entry["entry_price"] = ep
            entry["entry_id"] = open_entry["id"]
            open_entry["exit_id"] = entry["id"]
            open_entry["exit_price"] = price
            open_entry["pnl_pct"] = entry["pnl_pct"]

    _entries.append(entry)
    _trim(owner_id)
    _save()
    return entry


def list_for(owner_id: str, limit: int = 50) -> list[dict]:
    """Le piu' recenti per prime. A parita' di secondo decide l'ordine di
    inserimento: piu' segnali nello stesso giro di controllo condividono il
    timestamp, e invertirli renderebbe illeggibile la sequenza."""
    mine = [(i, e) for i, e in enumerate(_entries) if e.get("owner_id") == owner_id]
    mine.sort(key=lambda t: (t[1].get("ts", 0), t[0]), reverse=True)
    return [e for _, e in mine[:limit]]


def last_activity(owner_id: str) -> dict | None:
    rows = list_for(owner_id, limit=1)
    return rows[0] if rows else None


def clear(owner_id: str) -> int:
    n = 0
    for i in reversed(range(len(_entries))):
        if _entries[i].get("owner_id") == owner_id:
            del _entries[i]
            n += 1
    if n:
        _save()
    return n
