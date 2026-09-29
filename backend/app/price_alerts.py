"""
Price-level alerts: fire a Telegram message when a ticker's last close
crosses above or below a user-defined price.
Stored in data/price_alerts.json on the persistent volume.
"""

import json
import time
import uuid
from pathlib import Path

from app.models import AssetType, CryptoExchange, PriceAlert, PriceAlertCondition
from app.atomic_write import write_text_atomic

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "price_alerts.json"

_alerts: dict[str, PriceAlert] = {}
# last known close per symbol so we can detect crossings (not just current > threshold)
_last_prices: dict[str, float] = {}


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for item in raw:
        try:
            a = PriceAlert(**item)
            _alerts[a.id] = a
        except (TypeError, ValueError):
            continue


def _save() -> None:
    payload = [a.model_dump() for a in _alerts.values()]
    write_text_atomic(_STORE_FILE, json.dumps(payload), encoding="utf-8")


_load()


def list_alerts(owner_id: str) -> list[PriceAlert]:
    return [a for a in _alerts.values() if a.owner_id == owner_id]


def get_alert(alert_id: str) -> PriceAlert | None:
    return _alerts.get(alert_id)


def add_alert(
    owner_id: str,
    symbol: str,
    asset_type: AssetType,
    exchange: CryptoExchange,
    condition: PriceAlertCondition,
    price: float,
    note: str = "",
    once_only: bool = True,
) -> PriceAlert:
    alert = PriceAlert(
        id=uuid.uuid4().hex[:12],
        owner_id=owner_id,
        symbol=symbol.strip().upper(),
        asset_type=asset_type,
        exchange=exchange,
        condition=condition,
        price=price,
        note=note,
        once_only=once_only,
        created_at=int(time.time()),
    )
    _alerts[alert.id] = alert
    _save()
    return alert


def remove_alert(alert_id: str) -> None:
    if _alerts.pop(alert_id, None) is not None:
        _save()


def set_active(alert_id: str, active: bool) -> PriceAlert | None:
    a = _alerts.get(alert_id)
    if a is None:
        return None
    updated = a.model_copy(update={"active": active})
    _alerts[alert_id] = updated
    _save()
    return updated


def check_alerts(owner_id: str, symbol: str, current_price: float) -> list[PriceAlert]:
    """Check all active price alerts for this owner+symbol against current_price.
    Uses a crossing model: fires only when the price crosses the threshold
    (previous tick on one side, current on the other), not on every check.
    Returns the list of triggered alerts (already updated in storage).
    """
    prev = _last_prices.get(f"{owner_id}|{symbol}")
    _last_prices[f"{owner_id}|{symbol}"] = current_price

    triggered: list[PriceAlert] = []
    for a in list(_alerts.values()):
        if a.owner_id != owner_id or a.symbol != symbol or not a.active:
            continue
        hit = False
        if a.condition == PriceAlertCondition.crosses_above:
            # fires when prev < threshold <= current
            if prev is None:
                hit = current_price >= a.price
            else:
                hit = prev < a.price <= current_price
        else:  # crosses_below
            # fires when prev > threshold >= current
            if prev is None:
                hit = current_price <= a.price
            else:
                hit = prev > a.price >= current_price

        if not hit:
            continue
        now = int(time.time())
        updates: dict = {"last_triggered": now, "trigger_count": a.trigger_count + 1}
        if a.once_only:
            updates["active"] = False
        updated = a.model_copy(update=updates)
        _alerts[a.id] = updated
        triggered.append(updated)

    if triggered:
        _save()
    return triggered
