"""
Il "pilota": quello che il wallet on-chain fa da solo, reso visibile.

Lorenzo: "voglio sapere cosa sta monitorando, voglio vedere cosa sta
scansionando [...] una volta che attivo una strategia". Il ponte sniper ->
watchlist (main._sniper_onchain_bridge_tick) e il giro dei segnali
(main._watchlist_alert_loop) lavoravano gia', ma in silenzio: nessuno dei due
lasciava traccia di quando era passato, di cosa aveva guardato e di cosa
aveva scartato. Qui finiscono quelle tracce.

Due tipi di memoria, apposta:
- le SCOPERTE (token aggiunti dal ponte, con liquidita' ed eta' al momento
  dell'aggiunta) si salvano su file: sono la risposta a "perche' questo token
  e' qui?", e non devono sparire a ogni deploy;
- tutto il resto (ultimo giro, token esaminati oggi, scartati di recente,
  ultima valutazione di ogni token) sta in memoria: descrive il processo
  vivo, e dopo un riavvio "non ancora passato" e' la risposta vera.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque

from app.trading.onchain.storage import data_file

_STORE_FILE = data_file("onchain_pilot_discoveries.json")

_MAX_DISCOVERIES = 500
_MAX_REJECTED = 20

_lock = threading.Lock()

# owner_id -> symbol -> {added_at, liquidity_usd, age_hours, name, token_address, score}
_discoveries: dict[str, dict[str, dict]] = {}

# chain -> stato del ponte, in memoria
_scan: dict[str, dict] = {}
# chain -> deque di scartati recenti
_rejected: dict[str, deque] = {}
# watchlist entry id -> {ts, price}
_last_eval: dict[str, dict] = {}


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(raw, dict):
        _discoveries.update({k: v for k, v in raw.items() if isinstance(v, dict)})


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_discoveries, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


_load()


def _day_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else time.time()))


# ------------------------------------------------------------------ scritture


def record_scan(chain: str, *, seen: list[str], accepted: int, interval_s: int, now: float | None = None) -> None:
    """Un giro del ponte su una chain: quali token ha esaminato (indirizzi,
    per contarli una volta sola al giorno) e quanti ne ha fatti passare."""
    now = now if now is not None else time.time()
    with _lock:
        state = _scan.setdefault(chain, {})
        today = _day_key(now)
        if state.get("day") != today:
            state.update(day=today, seen_today=set(), accepted_today=0)
        state["seen_today"].update(seen)
        state["accepted_today"] += accepted
        state["last_at"] = now
        state["interval_s"] = interval_s
        state["last_seen"] = len(seen)


def record_rejection(chain: str, *, symbol: str, reason: str, liquidity_usd: float, age_hours: float,
                     now: float | None = None) -> None:
    with _lock:
        bucket = _rejected.setdefault(chain, deque(maxlen=_MAX_REJECTED))
        # Lo stesso token torna a ogni giro con lo stesso motivo: una riga sola.
        for item in bucket:
            if item["symbol"] == symbol:
                item.update(reason=reason, at=now or time.time(), liquidity_usd=liquidity_usd, age_hours=age_hours)
                return
        bucket.appendleft({
            "symbol": symbol, "reason": reason, "at": now or time.time(),
            "liquidity_usd": liquidity_usd, "age_hours": age_hours,
        })


def record_discovery(owner_id: str, symbol: str, *, name: str, token_address: str, liquidity_usd: float,
                     age_hours: float, score: str | None = None, now: float | None = None) -> None:
    with _lock:
        mine = _discoveries.setdefault(owner_id, {})
        mine[symbol] = {
            "added_at": now or time.time(), "name": name, "token_address": token_address,
            "liquidity_usd": liquidity_usd, "age_hours": age_hours, "score": score,
        }
        if len(mine) > _MAX_DISCOVERIES:
            for old in sorted(mine, key=lambda s: mine[s]["added_at"])[: len(mine) - _MAX_DISCOVERIES]:
                del mine[old]
        _save()


def record_evaluation(entry_id: str, *, price: float | None, now: float | None = None) -> None:
    """Il giro dei segnali e' passato su questo token (candele lette e
    strategia valutata), con o senza segnale."""
    with _lock:
        _last_eval[entry_id] = {"ts": now or time.time(), "price": price}


# -------------------------------------------------------------------- letture


def scan_state(chain: str) -> dict:
    with _lock:
        state = _scan.get(chain) or {}
        today = _day_key()
        fresh = state.get("day") == today
        return {
            "last_at": state.get("last_at"),
            "interval_s": state.get("interval_s"),
            "next_at": (state["last_at"] + state["interval_s"]) if state.get("last_at") and state.get("interval_s") else None,
            "seen_last": state.get("last_seen", 0),
            "seen_today": len(state["seen_today"]) if fresh else 0,
            "accepted_today": state.get("accepted_today", 0) if fresh else 0,
        }


def rejected(chain: str) -> list[dict]:
    with _lock:
        return [dict(item) for item in _rejected.get(chain, ())]


def discovery(owner_id: str, symbol: str) -> dict | None:
    with _lock:
        found = _discoveries.get(owner_id, {}).get(symbol)
        return dict(found) if found else None


def last_evaluation(entry_id: str) -> dict | None:
    with _lock:
        found = _last_eval.get(entry_id)
        return dict(found) if found else None


def reset_for_tests() -> None:
    with _lock:
        _discoveries.clear()
        _scan.clear()
        _rejected.clear()
        _last_eval.clear()
