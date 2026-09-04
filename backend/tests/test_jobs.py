"""Lavori lunghi seguiti da fuori.

Il guasto che questo evita è arrivato dalla bacheca come "Errore ottimizzazione:
The string did not match the expected pattern": Safari che legge come JSON una
pagina d'errore, perché la richiesta lunga era caduta prima di rispondere. Non
era l'ottimizzazione ad aver fallito — era la richiesta a non essere sopravvissuta.
"""

from __future__ import annotations

import time

import pytest

from app import jobs


@pytest.fixture(autouse=True)
def _isolate():
    jobs._jobs.clear()


def test_a_job_starts_running_and_carries_its_title():
    jid = jobs.create("u1", "optimize", "KASUSDT · Lorenzo · plateau")
    j = jobs.get(jid, "u1")
    assert j["state"] == "in corso"
    assert "KASUSDT" in j["title"]


def test_the_log_only_returns_what_is_new():
    """Il client manda quante righe ha già: ogni giro porta le novità, non
    l'intero log da capo."""
    jid = jobs.create("u1", "optimize", "x")
    jobs.log(jid, "prima")
    jobs.log(jid, "seconda")
    first = jobs.get(jid, "u1", since=0)
    assert [line["m"] for line in first["log"]] == ["prima", "seconda"]
    jobs.log(jid, "terza")
    nxt = jobs.get(jid, "u1", since=first["log_total"])
    assert [line["m"] for line in nxt["log"]] == ["terza"]


def test_the_log_is_capped(monkeypatch):
    """Una ricerca può emettere migliaia di righe: una lista senza tetto dentro
    il processo che serve anche le altre richieste è un modo lento di cadere."""
    monkeypatch.setattr(jobs, "_MAX_LOG_LINES", 10)
    jid = jobs.create("u1", "optimize", "x")
    for i in range(50):
        jobs.log(jid, f"riga {i}")
    j = jobs.get(jid, "u1")
    assert len(j["log"]) == 10
    assert j["log"][-1]["m"] == "riga 49", "si tengono le ultime, non le prime"


def test_a_finished_job_carries_its_result():
    jid = jobs.create("u1", "optimize", "x")
    jobs.finish(jid, {"params": {"a": 1}})
    j = jobs.get(jid, "u1")
    assert j["state"] == "finito"
    assert j["result"]["params"] == {"a": 1}


def test_a_running_job_does_not_leak_a_partial_result():
    jid = jobs.create("u1", "optimize", "x")
    assert jobs.get(jid, "u1")["result"] is None


def test_a_failure_keeps_the_reason():
    jid = jobs.create("u1", "optimize", "x")
    jobs.fail(jid, "Nessun dato per XYZ")
    j = jobs.get(jid, "u1")
    assert j["state"] == "fallito"
    assert "Nessun dato" in j["error"]


def test_another_user_cannot_read_the_job():
    jid = jobs.create("u1", "optimize", "x")
    assert jobs.get(jid, "u2") is None


def test_an_anonymous_job_is_readable_without_a_user():
    """Il Laboratorio funziona anche senza login: un lavoro senza proprietario
    non deve diventare irraggiungibile a chi l'ha appena avviato."""
    jid = jobs.create("", "optimize", "x")
    assert jobs.get(jid, "u1") is not None
    assert jobs.get(jid, None) is not None


def test_an_unknown_job_is_none_not_an_exception():
    assert jobs.get("non-esiste", "u1") is None


def test_writing_to_a_vanished_job_is_harmless():
    """Un lavoro scaduto mentre il thread scriveva non deve far cadere il thread."""
    jobs.log("non-esiste", "x")
    jobs.finish("non-esiste", {})
    jobs.fail("non-esiste", "x")


def test_finished_jobs_are_eventually_dropped(monkeypatch):
    monkeypatch.setattr(jobs, "_KEEP_FINISHED_S", 0)
    old = jobs.create("u1", "optimize", "vecchio")
    jobs.finish(old, {})
    jobs._jobs[old]["finished_at"] = time.time() - 10
    jobs.create("u1", "optimize", "nuovo")      # una create fa il prune
    assert jobs.get(old, "u1") is None


def test_a_running_job_is_never_dropped_by_the_prune(monkeypatch):
    monkeypatch.setattr(jobs, "_KEEP_FINISHED_S", 0)
    running = jobs.create("u1", "optimize", "in corso")
    jobs._jobs[running]["created_at"] = time.time() - 10_000
    jobs.create("u1", "optimize", "nuovo")
    assert jobs.get(running, "u1") is not None


def test_cancellation_is_recorded_and_owner_scoped():
    jid = jobs.create("u1", "optimize", "x")
    assert jobs.request_cancel(jid, "u2") is False
    assert jobs.request_cancel(jid, "u1") is True
    assert jobs.cancel_requested(jid) is True
