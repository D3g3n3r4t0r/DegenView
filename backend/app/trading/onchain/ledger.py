"""Fonte di verita' per size e stato di ogni ordine on-chain — la parte del
piano "mai sbagliare size, mai duplicare un ordine".

SQLite, non JSON come issues.py/auth.py: qui serve un vincolo UNIQUE vero a
livello database (idempotenza) e scritture atomiche, non un file riscritto
per intero ad ogni salvataggio. Un thread.Lock protegge le scritture perche'
il resto dell'app e' async ma sqlite3 e' sincrona — a questa scala (un
processo, un server) e' l'attrito giusto, non serve un pool di connessioni.

Sequenza obbligata per ogni ordine, sempre in questo ordine:
  1. reserve()       — scrive "pending" PRIMA di firmare qualunque cosa
  2. mark_submitted() — solo dopo che una transazione e' stata davvero inviata
  3. mark_confirmed() o mark_failed() — dopo aver interrogato la chain

reserve() fallisce (ritorna False) se la chiave esiste gia': chi la chiama
non deve firmare niente in quel caso, il tentativo e' gia' in corso o concluso.
"""
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_DB_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "onchain_ledger.db"
_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                idempotency_key TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                chain TEXT NOT NULL,
                token TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                side TEXT NOT NULL,
                mode TEXT NOT NULL,
                size_usd REAL NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                tx_signature TEXT,
                price_impact_pct REAL,
                executed_qty REAL,
                executed_price_usd REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                owner_id TEXT NOT NULL,
                chain TEXT NOT NULL,
                token TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (owner_id, chain, token)
            );
            CREATE TABLE IF NOT EXISTS daily_spend (
                owner_id TEXT NOT NULL,
                chain TEXT NOT NULL,
                day_key TEXT NOT NULL,
                spent_usd REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (owner_id, chain, day_key)
            );
            CREATE TABLE IF NOT EXISTS circuit_breaker (
                owner_id TEXT NOT NULL,
                chain TEXT NOT NULL,
                consecutive_losses INTEGER NOT NULL DEFAULT 0,
                tripped_at REAL,
                reason TEXT,
                PRIMARY KEY (owner_id, chain)
            );
        """)


_init_db()


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def reserve(
    idempotency_key: str, owner_id: str, chain: str, token: str,
    strategy_name: str, side: str, mode: str, size_usd: float,
) -> bool:
    """True se la riga e' stata scritta ora (via libera a firmare). False se
    esisteva gia' — un retry sulla stessa chiave, mai una firma doppia."""
    now = time.time()
    with _lock, _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO orders (idempotency_key, owner_id, chain, token, strategy_name, "
                "side, mode, size_usd, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (idempotency_key, owner_id, chain, token, strategy_name, side, mode, size_usd, now, now),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_order(idempotency_key: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return dict(row) if row else None


def mark_submitted(idempotency_key: str, tx_signature: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'submitted', tx_signature = ?, updated_at = ? WHERE idempotency_key = ?",
            (tx_signature, time.time(), idempotency_key),
        )


def mark_confirmed(
    idempotency_key: str, executed_qty: float, executed_price_usd: float, price_impact_pct: float | None = None,
) -> None:
    """Chiusura riuscita: aggiorna l'ordine E la posizione E la spesa
    giornaliera nella stessa transazione — sono la stessa fonte di verita',
    non tre scritture indipendenti che possono disallinearsi."""
    executed_usd = executed_qty * executed_price_usd
    with _lock, _connect() as conn:
        order = conn.execute("SELECT * FROM orders WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if order is None:
            return
        conn.execute(
            "UPDATE orders SET status = 'confirmed', executed_qty = ?, executed_price_usd = ?, "
            "price_impact_pct = ?, updated_at = ? WHERE idempotency_key = ?",
            (executed_qty, executed_price_usd, price_impact_pct, time.time(), idempotency_key),
        )
        signed_qty = executed_qty if order["side"] == "buy" else -executed_qty
        signed_cost = executed_usd if order["side"] == "buy" else -executed_usd
        conn.execute(
            "INSERT INTO positions (owner_id, chain, token, quantity, cost_usd) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(owner_id, chain, token) DO UPDATE SET "
            "quantity = quantity + excluded.quantity, cost_usd = cost_usd + excluded.cost_usd",
            (order["owner_id"], order["chain"], order["token"], signed_qty, signed_cost),
        )
        day_key = _today_key()
        conn.execute(
            "INSERT INTO daily_spend (owner_id, chain, day_key, spent_usd) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner_id, chain, day_key) DO UPDATE SET spent_usd = spent_usd + excluded.spent_usd",
            (order["owner_id"], order["chain"], day_key, executed_usd),
        )


def mark_failed(idempotency_key: str, reason: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE orders SET status = 'failed', reason = ?, updated_at = ? WHERE idempotency_key = ?",
            (reason, time.time(), idempotency_key),
        )


def get_position(owner_id: str, chain: str, token: str) -> dict:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT quantity, cost_usd FROM positions WHERE owner_id = ? AND chain = ? AND token = ?",
            (owner_id, chain, token),
        ).fetchone()
        return {"quantity": row["quantity"], "cost_usd": row["cost_usd"]} if row else {"quantity": 0.0, "cost_usd": 0.0}


def get_all_positions(owner_id: str, chain: str) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT token, quantity, cost_usd FROM positions WHERE owner_id = ? AND chain = ? AND quantity > 0",
            (owner_id, chain),
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_spent(owner_id: str, chain: str, day_key: str | None = None) -> float:
    day_key = day_key or _today_key()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT spent_usd FROM daily_spend WHERE owner_id = ? AND chain = ? AND day_key = ?",
            (owner_id, chain, day_key),
        ).fetchone()
        return row["spent_usd"] if row else 0.0


def pending_unconfirmed(owner_id: str | None = None) -> list[dict]:
    """Ordini 'submitted' senza mai una conferma — quello che un riavvio a
    meta' lascia indietro. Chi chiama deve interrogare la chain con la loro
    tx_signature prima di considerare qualunque nuovo segnale."""
    with _lock, _connect() as conn:
        query = "SELECT * FROM orders WHERE status = 'submitted'"
        params: tuple = ()
        if owner_id is not None:
            query += " AND owner_id = ?"
            params = (owner_id,)
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def record_trade_outcome(owner_id: str, chain: str, pnl_usd: float, loss_streak_trip: int = 5) -> bool:
    """Aggiorna il contatore di perdite consecutive; ritorna True se il
    circuit breaker scatta ORA (chi chiama deve fermare nuovi ordini)."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT consecutive_losses FROM circuit_breaker WHERE owner_id = ? AND chain = ?",
            (owner_id, chain),
        ).fetchone()
        losses = row["consecutive_losses"] if row else 0
        losses = losses + 1 if pnl_usd < 0 else 0
        tripped = losses >= loss_streak_trip
        conn.execute(
            "INSERT INTO circuit_breaker (owner_id, chain, consecutive_losses, tripped_at, reason) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(owner_id, chain) DO UPDATE SET consecutive_losses = excluded.consecutive_losses, "
            "tripped_at = excluded.tripped_at, reason = excluded.reason",
            (owner_id, chain, losses, time.time() if tripped else None,
             f"{losses} operazioni consecutive in perdita" if tripped else None),
        )
        return tripped


def breaker_status(owner_id: str, chain: str) -> dict:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT consecutive_losses, tripped_at, reason FROM circuit_breaker WHERE owner_id = ? AND chain = ?",
            (owner_id, chain),
        ).fetchone()
        if row is None:
            return {"tripped": False, "consecutive_losses": 0, "reason": None}
        return {"tripped": bool(row["tripped_at"]), "consecutive_losses": row["consecutive_losses"], "reason": row["reason"]}


def reset_breaker(owner_id: str, chain: str) -> None:
    """Riattivazione MANUALE apposta — vedi il piano: un breaker che si
    riarma da solo non e' un freno, e' un ritardo."""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE circuit_breaker SET consecutive_losses = 0, tripped_at = NULL, reason = NULL "
            "WHERE owner_id = ? AND chain = ?",
            (owner_id, chain),
        )
