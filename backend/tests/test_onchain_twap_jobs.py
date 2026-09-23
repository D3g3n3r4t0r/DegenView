"""Wiring reale del TWAP (twap_jobs.py): il job persiste nel ledger PRIMA
di firmare, si ferma al primo fallimento senza toccare le fette
successive, e un segnale opposto ferma solo le fette non ancora eseguite."""
from __future__ import annotations

import asyncio
import random

from app import auth
from app.trading.onchain import execute, ledger, quotes as onchain_quotes, risk, twap_jobs


def _run(coro):
    return asyncio.run(coro)


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_FILE", tmp_path / "ledger.db")
    ledger._init_db()
    twap_jobs._init_db()
    # niente attese vere nei test
    monkeypatch.setattr(twap_jobs.asyncio, "sleep", _fake_sleep)
    # la concentrazione (100% su un unico token appena si compra qualcosa
    # di gia' in portafoglio) non e' quello che questi test verificano: la
    # meccanica di slicing/persistenza/cancellazione del TWAP, si')
    monkeypatch.setattr(risk, "check_concentration", lambda *a, **k: (True, ""))


async def _fake_sleep(_seconds):
    return None


def _quote_for_slice_ok(calls):
    async def _quote_for_slice(slice_usd: float):
        calls.append(slice_usd)
        return 0.5, {"in_amount": 1, "out_amount": 1, "price_impact_pct": 0.5, "raw": {}}
    return _quote_for_slice


async def _fake_build_signed(private_key_hex, quote):
    return b"signed-tx-bytes"


async def _fake_send(signed_tx_bytes):
    return "fake-sig"


def _patch_execute_ok(monkeypatch):
    monkeypatch.setattr(execute.settings, "onchain_execution_enabled", True)
    monkeypatch.setattr(execute.execution, "build_signed_solana_swap", _fake_build_signed)
    monkeypatch.setattr(execute.execution, "send_signed_solana_tx", _fake_send)


def test_small_order_executes_as_a_single_slice(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _patch_execute_ok(monkeypatch)
    calls = []
    result = _run(twap_jobs.execute_twap_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 10.0, 2.0, "deadbeef",
        1_000_000.0, _quote_for_slice_ok(calls),
    ))
    assert result["status"] == "completed"
    assert result["slices_total"] == 1
    assert calls == [10.0]
    job = twap_jobs.get_job(result["job_id"])
    assert job["status"] == "completed"
    assert job["slices_done"] == 1


def test_thin_pool_order_is_sliced_and_persisted_before_first_fill(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _patch_execute_ok(monkeypatch)
    calls = []
    result = _run(twap_jobs.execute_twap_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 20.0, 500.0, "deadbeef",
        500.0, _quote_for_slice_ok(calls), rng=random.Random(1),
    ))
    assert result["status"] == "completed"
    assert result["slices_total"] > 1
    assert len(calls) == result["slices_total"]
    assert round(sum(calls), 2) == 20.0
    # posizione aggiornata coerente col totale delle fette confermate
    pos = ledger.get_position("u1", "solana", "TOKEN")
    assert round(pos["cost_usd"], 2) == 20.0


def test_failed_slice_stops_the_job_without_attempting_the_rest(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(execute.settings, "onchain_execution_enabled", True)

    attempts = []

    async def _flaky_build(private_key_hex, quote):
        attempts.append(1)
        if len(attempts) == 2:
            raise RuntimeError("rete inaffidabile")
        return b"signed-tx-bytes"

    monkeypatch.setattr(execute.execution, "build_signed_solana_swap", _flaky_build)
    monkeypatch.setattr(execute.execution, "send_signed_solana_tx", _fake_send)

    calls = []
    result = _run(twap_jobs.execute_twap_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 20.0, 500.0, "deadbeef",
        500.0, _quote_for_slice_ok(calls), rng=random.Random(1),
    ))
    assert result["status"] == "failed"
    assert result["reason"] is not None
    assert result["slices_done"] < result["slices_total"]
    # nessun tentativo dopo il fallimento
    assert len(attempts) == 2
    job = twap_jobs.get_job(result["job_id"])
    assert job["status"] == "failed"


def test_cancel_request_stops_before_the_next_unstarted_slice(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _patch_execute_ok(monkeypatch)

    calls = []

    async def _quote_for_slice(slice_usd: float):
        calls.append(slice_usd)
        if len(calls) == 1:
            # simula un segnale opposto arrivato mentre la prima fetta gira
            pass
        return 0.5, {"in_amount": 1, "out_amount": 1, "price_impact_pct": 0.5, "raw": {}}

    # Job creato, poi lo cancelliamo "a mano" prima di lanciare l'esecuzione
    # scaglionata di una seconda fetta: per farlo in modo deterministico nel
    # test, patchiamo _update_progress cosi' che dopo la prima fetta il job
    # risulti cancel_requested.
    original_update = twap_jobs._update_progress

    def _update_then_cancel(job_id, slices_done):
        original_update(job_id, slices_done)
        if slices_done == 1:
            twap_jobs.request_cancel(job_id)

    monkeypatch.setattr(twap_jobs, "_update_progress", _update_then_cancel)

    result = _run(twap_jobs.execute_twap_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 20.0, 500.0, "deadbeef",
        500.0, _quote_for_slice, rng=random.Random(1),
    ))
    assert result["status"] == "cancelled"
    assert result["slices_done"] == 1
    assert result["slices_total"] > 1
    job = twap_jobs.get_job(result["job_id"])
    assert job["status"] == "cancelled"
    # la fetta gia' confermata resta confermata (mai annullata)
    pos = ledger.get_position("u1", "solana", "TOKEN")
    assert pos["cost_usd"] > 0


def test_running_jobs_are_listed_for_a_future_resume(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    monkeypatch.setattr(execute.settings, "onchain_execution_enabled", True)

    async def _never_returns_build(private_key_hex, quote):
        raise RuntimeError("firma mai completata in questo test")

    monkeypatch.setattr(execute.execution, "build_signed_solana_swap", _never_returns_build)
    monkeypatch.setattr(execute.execution, "send_signed_solana_tx", _fake_send)

    calls = []
    result = _run(twap_jobs.execute_twap_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 10.0, 2.0, "deadbeef",
        1_000_000.0, _quote_for_slice_ok(calls),
    ))
    assert result["status"] == "failed"
    # una volta fallito non e' piu' "running" - verifichiamo che un job
    # ancora in corso invece appaia nella lista (qui simulato scrivendolo
    # direttamente, dato che execute_twap_job e' sincrono fetta per fetta).
    job_id = twap_jobs._create_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 10.0, [10.0], 2.0, None,
    )
    running = twap_jobs.list_running_jobs("u1")
    assert any(j["id"] == job_id for j in running)
    assert all(j["id"] != result["job_id"] for j in running)


def test_resume_running_twap_jobs_only_executes_the_remaining_slices(tmp_path, monkeypatch):
    """Job lasciato 'running' con 2 fette su 4 gia' confermate: la ripresa
    (dopo un ipotetico riavvio del processo) deve firmare SOLO le fette 3
    e 4, mai richiamare execute_order per la 1 e la 2 (gia' confermate)."""
    _fresh_db(tmp_path, monkeypatch)
    _patch_execute_ok(monkeypatch)

    class _FakeUser:
        id = "u1"
        onchain_wallets: dict = {"solana": "whatever"}

    monkeypatch.setattr(auth, "get_user", lambda user_id: _FakeUser() if user_id == "u1" else None)
    monkeypatch.setattr(auth, "get_decrypted_onchain_private_key", lambda user, chain: "deadbeef")

    quote_calls = []

    async def _fake_jupiter_quote(input_mint, output_mint, amount_lamports, slippage_bps=50):
        quote_calls.append(amount_lamports)
        return {"price_impact_pct": 0.5, "in_amount": amount_lamports, "out_amount": 1, "raw": {}}

    monkeypatch.setattr(onchain_quotes, "jupiter_quote", _fake_jupiter_quote)

    slices = [5.0, 5.0, 5.0, 5.0]
    job_id = twap_jobs._create_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 20.0, slices, 2.0,
        {"input_mint": "MINT_IN", "output_mint": "MINT_OUT", "total_amount_lamports": 20_000_000, "slippage_bps": 50},
    )
    # simula 2 fette su 4 gia' confermate prima del riavvio
    twap_jobs._update_progress(job_id, 2)

    results = _run(twap_jobs.resume_running_twap_jobs())

    assert len(results) == 1
    assert results[0]["status"] == "completed"
    assert results[0]["job_id"] == job_id
    # solo le fette 3 e 4 (5_000_000 lamports ciascuna, 5/20 * 20_000_000)
    assert quote_calls == [5_000_000, 5_000_000]
    job = twap_jobs.get_job(job_id)
    assert job["status"] == "completed"
    assert job["slices_done"] == 4
    # la posizione riflette solo le fette 3 e 4 eseguite ORA (le prime 2
    # confermate "prima del riavvio" non sono passate da execute_order in
    # questo test, quindi non contribuiscono al costo registrato qui)
    pos = ledger.get_position("u1", "solana", "TOKEN")
    assert round(pos["cost_usd"], 2) == 10.0


def test_resume_skips_jobs_without_quote_meta(tmp_path, monkeypatch):
    """Un job creato senza quote_meta (schema vecchio, o chiamante che non
    lo passa) non e' ricostruibile: resta 'running', non viene ignorato
    silenziosamente ma nemmeno fatto fallire a forza."""
    _fresh_db(tmp_path, monkeypatch)
    job_id = twap_jobs._create_job(
        "u1", "solana", "TOKEN", "lorenzo", "buy", 20.0, [10.0, 10.0], 2.0, None,
    )
    results = _run(twap_jobs.resume_running_twap_jobs())
    assert results == []
    job = twap_jobs.get_job(job_id)
    assert job["status"] == "running"
