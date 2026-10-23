"""The coins a strategy's bot bought on a spot exchange, so its exit sells
exactly those.

Until 23/10 an exit re-used the entry's sizing: with "fixed 50 USDT" it sold
50 USDT worth at the exit price (part of the position left behind after a
rise, a sell larger than the holding after a fall), with "10% of balance" it
sold 10% of every coin of that kind on the account. Now a buy records its
quantity per (account, exchange, pair, strategy), and the exit sells that
quantity, never more than is free; other coins on the account are left alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.atomic_write import write_text_atomic

_STORE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "spot_positions.json"
_store: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _store
    if _store is None:
        try:
            _store = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _store = {}
    return _store


def _save() -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(_STORE_FILE, json.dumps(_load(), separators=(",", ":")))


def _key(owner_id: str, exchange: str, symbol: str, strategy: str) -> str:
    return f"{owner_id}|{exchange}|{symbol.upper()}|{strategy}"


def held(owner_id: str, exchange: str, symbol: str, strategy: str) -> float:
    return float((_load().get(_key(owner_id, exchange, symbol, strategy)) or {}).get("qty") or 0.0)


def bought(owner_id: str, exchange: str, symbol: str, strategy: str, qty: float, at: float) -> None:
    if qty <= 0:
        return
    row = _load().setdefault(_key(owner_id, exchange, symbol, strategy), {"qty": 0.0, "since": at})
    row["qty"] += qty
    _save()


def sold(owner_id: str, exchange: str, symbol: str, strategy: str) -> None:
    """The exit sold the whole recorded quantity (or all that was free)."""
    if _load().pop(_key(owner_id, exchange, symbol, strategy), None) is not None:
        _save()


def closed_by_hand(owner_id: str, exchange: str, symbol: str) -> None:
    """"Sell all" from the Trading tab: every strategy's record on the pair goes."""
    prefix = f"{owner_id}|{exchange}|{symbol.upper()}|"
    gone = [k for k in _load() if k.startswith(prefix)]
    for k in gone:
        del _load()[k]
    if gone:
        _save()


def qty_of(result: dict) -> float:
    """Coins an order bought: netQty (MEXC: the quantity sent less the fee it
    keeps from the coins), else executedQty (Binance), else the quantity sent."""
    for k in ("netQty", "executedQty", "origQty", "requestedQty"):
        try:
            v = float(result.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return 0.0
