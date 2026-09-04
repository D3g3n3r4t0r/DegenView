"""
Lavori lunghi seguiti da fuori, invece che dentro una richiesta HTTP.

L'ottimizzazione "stabile" puo' durare minuti. Tenuta dentro una GET, quella
richiesta deve restare aperta per tutto il tempo, e non e' una cosa che
sopravvive alla catena: il proxy davanti all'app la chiude, il browser la
lascia cadere, e quello che torna non e' piu' JSON ma una pagina d'errore.
Safari, a quel punto, prova a leggerla come JSON e dice "The string did not
match the expected pattern" — il messaggio arrivato sulla bacheca, che non
parla di ottimizzazione perche' non e' l'ottimizzazione ad aver fallito.

Qui la richiesta apre un lavoro e torna subito. Il lavoro va avanti per conto
suo e accumula righe di log; il client le chiede quando vuole. Nessuna
richiesta lunga, e in piu' si vede cosa sta succedendo — che era la seconda
meta' della segnalazione: capire se sta lavorando.

I lavori vivono in memoria: sono in corso o appena finiti, e un riavvio li
annulla comunque. Persisterli darebbe un elenco di lavori che nessun processo
sta piu' portando avanti.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Literal

State = Literal["in corso", "finito", "fallito"]

_MAX_LOG_LINES = 400
_KEEP_FINISHED_S = 900          # un quarto d'ora: il tempo di leggere il risultato
_MAX_JOBS = 60

_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _prune() -> None:
    now = time.time()
    stale = [
        jid for jid, j in _jobs.items()
        if j["state"] != "in corso" and now - j["finished_at"] > _KEEP_FINISHED_S
    ]
    for jid in stale:
        del _jobs[jid]
    if len(_jobs) > _MAX_JOBS:
        oldest = sorted(_jobs.items(), key=lambda kv: kv[1]["created_at"])
        for jid, _ in oldest[: len(_jobs) - _MAX_JOBS]:
            del _jobs[jid]


def create(owner_id: str, kind: str, title: str) -> str:
    with _lock:
        _prune()
        jid = uuid.uuid4().hex[:12]
        _jobs[jid] = {
            "id": jid,
            "owner_id": owner_id,
            "kind": kind,
            "title": title,
            "state": "in corso",
            "created_at": time.time(),
            "finished_at": 0.0,
            "log": [],
            "result": None,
            "error": "",
        }
    return jid


def log(job_id: str, message: str) -> None:
    """Una riga di avanzamento. Chiamata dal thread di lavoro, quindi sotto lock.

    Il tetto sulle righe non e' cosmetico: una ricerca puo' emetterne migliaia,
    e una lista che cresce senza limite dentro un processo che serve anche le
    altre richieste e' un modo lento di far cadere il server. Si tengono le
    ultime, che sono quelle che dicono a che punto siamo.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["log"].append({"t": round(time.time() - job["created_at"], 1), "m": message[:300]})
        if len(job["log"]) > _MAX_LOG_LINES:
            del job["log"][: len(job["log"]) - _MAX_LOG_LINES]


def finish(job_id: str, result: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["state"] = "finito"
        job["result"] = result
        job["finished_at"] = time.time()


def fail(job_id: str, error: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["state"] = "fallito"
        job["error"] = error[:600]
        job["finished_at"] = time.time()


def get(job_id: str, owner_id: str | None = None, since: int = 0) -> dict | None:
    """Lo stato piu' le righe di log dalla posizione `since` in poi.

    Il client manda quante ne ha gia': cosi' ogni richiesta porta solo le
    novita' invece di ritrasmettere tutto il log a ogni giro.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        if owner_id is not None and job["owner_id"] not in ("", owner_id):
            return None
        lines = job["log"][max(0, since):]
        return {
            "id": job["id"],
            "kind": job["kind"],
            "title": job["title"],
            "state": job["state"],
            "elapsed_s": round((job["finished_at"] or time.time()) - job["created_at"], 1),
            "log": lines,
            "log_total": len(job["log"]),
            "result": job["result"] if job["state"] == "finito" else None,
            "error": job["error"],
        }


def cancel_requested(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job.get("cancel"))


def request_cancel(job_id: str, owner_id: str | None = None) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or (owner_id is not None and job["owner_id"] not in ("", owner_id)):
            return False
        job["cancel"] = True
        return True
