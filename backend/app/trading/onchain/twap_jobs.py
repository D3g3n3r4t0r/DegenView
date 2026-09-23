"""Wiring reale del TWAP — dal piano: "un segnale della strategia non
genera un ordine unico ma un job con N fette [...]. Non e' alta frequenza:
3-8 fette, 15-90 secondi di intervallo. Sotto un notional minimo si
esegue in un colpo unico. Un segnale opposto ha sempre precedenza: ferma
le fette non ancora eseguite (mai quelle gia' confermate). Lo stato del
job vive persistito fuori dal processo — un riavvio lo rilegge e riprende,
non duplica."

twap.py calcola solo N e i ritardi (matematica pura, nessun I/O); questo
modulo e' quello che li usa per davvero: persiste il job PRIMA di
eseguire la prima fetta, chiama execute.execute_order() una volta per
fetta, aspetta i ritardi tra una fetta e la successiva, e si ferma al
primo fallimento (mai un errore silenzioso).

Stesso stile di ledger.py: SQLite, thread.Lock, WAL, stesso file DB (una
tabella in piu', non un database separato — un job e' comunque figlio
degli stessi ordini che finiscono in `orders`).

LIMITE NOTO E DICHIARATO: non c'e' uno scheduler in background che, al
riavvio del processo, riprenda da solo i job con status='running' lasciati
a meta'. Il job E' persistito (list_running_jobs() lo ritrova), ma la
ripresa automatica non e' cablata da nessuna parte in questo commit — chi
lo fara' dovra' richiamare execute_twap_job() con lo stesso quote_for_slice
e riprendere da job['slices_done']. Senza tempo per farlo bene (serve
anche capire come si ricostruisce un quote_for_slice per Solana/Robinhood
al riavvio, che dipende da input specifici del segnale originale), meglio
dirlo chiaramente qui che fingere una resume automatica che non c'e'.
"""
import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable

from app.trading.onchain import execute, ledger, twap

# Sotto questo notional, TWAP escluso di proposito (dal piano): il gas per
# fetta costerebbe piu' del risparmio di slippage su un ordine cosi'
# piccolo. plan_slices() gia' collassa a 1 fetta sotto DEFAULT_MIN_SLICE_USD
# per fetta, ma qui e' la soglia sul TOTALE dell'ordine, prima ancora di
# calcolare quante fette servirebbero.
DEFAULT_MIN_TWAP_NOTIONAL_USD = 15.0

# Firma del callback che chi chiama passa per costruire il quote di UNA
# fetta: Solana (amount_lamports) e Robinhood (amount_in) scalano con la
# size della fetta, non con quella totale dell'ordine — costruirlo e'
# responsabilita' di chi conosce la chain, non di questo modulo generico.
QuoteForSlice = Callable[[float], Awaitable[tuple[float, dict]]]


def _connect():
    return ledger._connect()


def _init_db() -> None:
    with ledger._lock, _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS twap_jobs (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                chain TEXT NOT NULL,
                token TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                side TEXT NOT NULL,
                total_usd REAL NOT NULL,
                slices_planned TEXT NOT NULL,
                slices_done INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                reason TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)


_init_db()


def _create_job(
    owner_id: str, chain: str, token: str, strategy_name: str, side: str,
    total_usd: float, slices: list[float],
) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with ledger._lock, _connect() as conn:
        conn.execute(
            "INSERT INTO twap_jobs (id, owner_id, chain, token, strategy_name, side, total_usd, "
            "slices_planned, slices_done, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'running', ?, ?)",
            (job_id, owner_id, chain, token, strategy_name, side, total_usd, json.dumps(slices), now, now),
        )
    return job_id


def get_job(job_id: str) -> dict | None:
    with ledger._lock, _connect() as conn:
        row = conn.execute("SELECT * FROM twap_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        job = dict(row)
        job["slices_planned"] = json.loads(job["slices_planned"])
        return job


def list_running_jobs(owner_id: str | None = None) -> list[dict]:
    """Job lasciati a status='running' — quello che un riavvio a meta'
    lascia indietro. Vedi il limite noto in testa al modulo: e' chi
    riprende (oggi nessuno automaticamente) a doverli richiamare."""
    with ledger._lock, _connect() as conn:
        query = "SELECT * FROM twap_jobs WHERE status = 'running'"
        params: tuple = ()
        if owner_id is not None:
            query += " AND owner_id = ?"
            params = (owner_id,)
        rows = conn.execute(query, params).fetchall()
    jobs = [dict(r) for r in rows]
    for job in jobs:
        job["slices_planned"] = json.loads(job["slices_planned"])
    return jobs


def _update_progress(job_id: str, slices_done: int) -> None:
    with ledger._lock, _connect() as conn:
        conn.execute(
            "UPDATE twap_jobs SET slices_done = ?, updated_at = ? WHERE id = ?",
            (slices_done, time.time(), job_id),
        )


def _set_status(job_id: str, status: str, reason: str | None = None) -> None:
    with ledger._lock, _connect() as conn:
        conn.execute(
            "UPDATE twap_jobs SET status = ?, reason = ?, updated_at = ? WHERE id = ?",
            (status, reason, time.time(), job_id),
        )


def request_cancel(job_id: str) -> bool:
    """Un segnale opposto ha sempre precedenza (dal piano): ferma le fette
    non ancora eseguite, mai quelle gia' confermate — il loop di
    execute_twap_job() controlla questo flag prima di partire con OGNI
    fetta successiva alla prima, mai a meta' di una fetta in corso (che a
    questo punto e' comunque gia' stata firmata/inviata). Ritorna False se
    il job non e' (piu') in stato 'running'."""
    with ledger._lock, _connect() as conn:
        row = conn.execute("SELECT status FROM twap_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None or row["status"] != "running":
            return False
        conn.execute(
            "UPDATE twap_jobs SET status = 'cancel_requested', updated_at = ? WHERE id = ?",
            (time.time(), job_id),
        )
    return True


async def execute_twap_job(
    owner_id: str, chain: str, token: str, strategy_name: str, side: str,
    total_usd: float, price_usd: float, private_key_hex: str,
    pool_liquidity_usd: float, quote_for_slice: QuoteForSlice,
    *, min_twap_notional_usd: float = DEFAULT_MIN_TWAP_NOTIONAL_USD,
    rng=None,
) -> dict:
    """Esegue un segnale come una sola fetta (sotto min_twap_notional_usd,
    o su un pool profondo dove twap.plan_slices() collassa a 1) o come un
    vero TWAP scaglionato. Scrive il job nel ledger PRIMA di firmare la
    prima fetta — e' quello che rende un riavvio ricostruibile (vedi
    list_running_jobs()), non un dict Python che si perde al riavvio.

    Ogni fetta e' semplicemente una execute.execute_order() con
    notional_usd = quella fetta: il quote (che dipende dalla size della
    fetta, non del totale) lo costruisce quote_for_slice(slice_usd), che
    chi chiama fornisce perche' solo lui conosce gli input specifici della
    chain (input/output mint per Solana, token_in/out/fee per Robinhood).

    Al primo fallimento (risk check, firma o invio) si ferma: nessun
    tentativo sulle fette successive, il job va a 'failed' con la ragione,
    e il risultato riporta esattamente quante fette sono state eseguite —
    mai un fallimento silenzioso."""
    if total_usd < min_twap_notional_usd:
        slices = [round(total_usd, 2)]
    else:
        slices = twap.plan_slices(total_usd, pool_liquidity_usd)

    job_id = _create_job(owner_id, chain, token, strategy_name, side, total_usd, slices)
    delays = twap.plan_delays_s(len(slices), rng=rng) if len(slices) > 1 else []

    for i, slice_usd in enumerate(slices):
        if i > 0:
            job = get_job(job_id)
            if job is not None and job["status"] == "cancel_requested":
                _set_status(job_id, "cancelled", f"fermato dopo {i} fette su {len(slices)} (segnale opposto)")
                return {
                    "job_id": job_id, "status": "cancelled",
                    "slices_done": i, "slices_total": len(slices),
                }
            await asyncio.sleep(delays[i - 1])

        try:
            price_impact_pct, quote = await quote_for_slice(slice_usd)
        except Exception as exc:  # noqa: BLE001 - un quote fallito ferma il job, non e' silenzioso
            _set_status(job_id, "failed", f"quote fallito sulla fetta {i + 1}/{len(slices)}: {exc}")
            return {
                "job_id": job_id, "status": "failed",
                "slices_done": i, "slices_total": len(slices),
                "reason": f"quote fallito sulla fetta {i + 1}/{len(slices)}: {exc}",
            }

        result = await execute.execute_order(
            owner_id, chain, token, strategy_name, side, slice_usd,
            price_impact_pct, price_usd, private_key_hex, quote,
        )
        if not result["accepted"]:
            _set_status(job_id, "failed", result["reason"])
            return {
                "job_id": job_id, "status": "failed",
                "slices_done": i, "slices_total": len(slices),
                "reason": result["reason"],
            }
        _update_progress(job_id, i + 1)

    _set_status(job_id, "completed")
    return {"job_id": job_id, "status": "completed", "slices_done": len(slices), "slices_total": len(slices)}
