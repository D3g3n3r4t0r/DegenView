"""
Segnalazioni dei problemi, scritte dall'app.

Chi scrive cosa è separato di proposito, come per i file nel repo:

  * Le SEGNALAZIONI le scrivete voi dall'interfaccia. Vivono nel volume Fly, in
    `data/issues.json`, e sopravvivono ai deploy.
  * Le RISOLUZIONI le scrive Claude, in `app/data/resolutions.json`, che è
    versionato in git e viaggia con il deploy.

Nessuno dei due lati può quindi sovrascrivere l'altro, e ogni risoluzione porta
con sé la storia del commit che l'ha introdotta invece di un campo "data" che
qualcuno deve ricordarsi di compilare.

L'unione avviene in lettura, agganciando la risoluzione all'id della
segnalazione: gli id sono generati dal server e restano stabili, quindi il
riferimento regge anche se l'elenco viene riordinato o filtrato.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "issues.json"

# Versionato in git e distribuito col deploy: è il lato di Claude.
_RESOLUTIONS_FILE = Path(__file__).resolve().parent / "data" / "resolutions.json"

_MAX_ISSUES = 500

Status = Literal["aperto", "in corso", "risolto", "scartato"]
Priority = Literal["alta", "media", "bassa"]

_VALID_STATUS = {"aperto", "in corso", "risolto", "scartato"}
_VALID_PRIORITY = {"alta", "media", "bassa"}

_issues: list[dict] = []


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _issues.clear()
            _issues.extend(raw)
    except (json.JSONDecodeError, OSError):
        pass


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_issues, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _resolutions() -> dict[str, dict]:
    """Le risoluzioni scritte da Claude, lette a ogni richiesta.

    Rilette ogni volta anziché memorizzate all'avvio: il file arriva col deploy,
    e un processo che sopravvive a più deploy servirebbe altrimenti le
    risoluzioni della versione con cui è partito.
    """
    try:
        raw = json.loads(_RESOLUTIONS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


_SEED = [
    ("seed-0001", "Bug grafico sui trade del backtest", "", "media"),
    ("seed-0002", "Salvare il backtest in database quando si attiva un alert",
     "Una volta attivato l'alert di una strategia bisogna poter accedere al backtesting e salvarlo, "
     "per avere un archivio consultabile delle strategie generate dall'ottimizzazione.", "alta"),
    ("seed-0003", "Strategia Gabriele 2 con movimento short",
     "Da testare e applicare poi sui futures.", "media"),
    ("seed-0004", "Graficare l'imbalance FVG in stile TradingView",
     "Zone d'interesse a barre orizzontali.", "media"),
    ("seed-0005", "Valore RSI sul pallino blu invece che sulla freccia del cursore", "", "bassa"),
    ("seed-0006", "Pulsante per attivare/disattivare modalita' black", "", "bassa"),
    ("seed-0007", "Discrepanza nel numero di trade fra ottimizzazione e manuale",
     "Con gli stessi valori impostati a mano si ottengono risultati simili ma quantita' di trade molto "
     "diverse rispetto alla modalita' automatica. Ogni variabile aggiuntiva usata dalla logica automatica "
     "deve essere parametrizzata e visibile dopo l'ottimizzazione, per rendere il risultato replicabile "
     "a mano e verificabile.", "alta"),
    ("seed-0008", "Venti notifiche Telegram con prezzi disparati dopo aver attivato un alert", "", "alta"),
    ("seed-0009", "Filtri di ottimizzazione su trade in perdita e drawdown",
     "Poter selezionare solo strategie con un minimo/massimo di trade in perdita (compreso 0) "
     "o una percentuale di drawdown (compreso 0%).", "media"),
    ("seed-0010", "Dubbi sui dati non usati in ottimizzazione nel backtest",
     "Verificare che non escluda trade 'a giochi fatti' per gonfiare la performance, e che quei trade "
     "sarebbero davvero stati aperti o chiusi dal bot in tempo reale.", "alta"),
    ("seed-0011", "Il trading automatico non ha mai piazzato un ordine",
     "Trovato lavorando sugli alert, non segnalato: non c'era modo di accorgersene. "
     "Nessun errore, nessun log, semplicemente nessun ordine.", "alta"),
]


def _seed() -> None:
    """Popola l'elenco al primo avvio, senza toccare quello che c'e' gia'.

    Gli id sono fissi e non generati: le risoluzioni scritte da Claude si
    agganciano per id, e un id casuale al primo avvio scollegherebbe le
    diagnosi gia' scritte da queste voci.
    """
    if _issues:
        return
    now = int(time.time())
    for i, (iid, title, detail, prio) in enumerate(_SEED):
        _issues.append({
            "id": iid, "title": title, "detail": detail, "priority": prio,
            "status": "aperto", "author": "lista iniziale",
            "created_at": now - (len(_SEED) - i),
        })
    _save()


_load()
_seed()


def list_issues() -> list[dict]:
    """Segnalazioni con la risoluzione agganciata, le più recenti per prime."""
    res = _resolutions()
    out = []
    for it in _issues:
        merged = dict(it)
        r = res.get(it["id"])
        if r:
            merged["resolution"] = r
            # La risoluzione è la fonte di verità sullo stato: se Claude l'ha
            # segnata risolta, l'elenco non deve continuare a mostrarla aperta
            # solo perché nessuno ha aggiornato il campo a mano.
            if r.get("status") in _VALID_STATUS:
                merged["status"] = r["status"]
        out.append(merged)
    return sorted(out, key=lambda x: x.get("created_at", 0), reverse=True)


def add_issue(title: str, detail: str = "", priority: str = "media",
              author: str = "") -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("Titolo mancante")
    entry = {
        "id": uuid.uuid4().hex[:8],
        "title": title[:300],
        "detail": (detail or "").strip()[:4000],
        "priority": priority if priority in _VALID_PRIORITY else "media",
        "status": "aperto",
        "author": (author or "").strip()[:120],
        "created_at": int(time.time()),
    }
    _issues.append(entry)
    if len(_issues) > _MAX_ISSUES:
        del _issues[: len(_issues) - _MAX_ISSUES]
    _save()
    return entry


def update_issue(issue_id: str, *, status: str | None = None,
                 priority: str | None = None, detail: str | None = None) -> dict | None:
    for it in _issues:
        if it["id"] != issue_id:
            continue
        if status is not None:
            if status not in _VALID_STATUS:
                raise ValueError(f"Stato non valido: {status}")
            it["status"] = status
        if priority is not None:
            if priority not in _VALID_PRIORITY:
                raise ValueError(f"Priorità non valida: {priority}")
            it["priority"] = priority
        if detail is not None:
            it["detail"] = detail.strip()[:4000]
        _save()
        return it
    return None


def delete_issue(issue_id: str) -> bool:
    for i, it in enumerate(_issues):
        if it["id"] == issue_id:
            del _issues[i]
            _save()
            return True
    return False
