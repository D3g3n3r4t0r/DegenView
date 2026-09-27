"""What each account's wallets were worth, over time: the profile's chart.

A reading every SNAPSHOT_S (main._wealth_loop) of everything the wallets
hold, in USD. Stored thinned as it ages, so a year of history stays small:
every reading for two days, one an hour for a month, one a day after that.
"""
from __future__ import annotations

import json
import threading
import time

from app.trading.onchain.storage import data_file

_STORE_FILE = data_file("onchain_wealth.json")
SNAPSHOT_S = 10 * 60
RANGES = {"24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400, "all": None}

_lock = threading.Lock()
_series: dict[str, list[list[float]]] = {}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _series.update({k: v for k, v in raw.items() if isinstance(v, list)})


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_series, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _series.clear()


def _thin(rows: list[list[float]], now: float) -> list[list[float]]:
    out, last_bucket = [], None
    for t, v in rows:
        age = now - t
        step = 0 if age < 2 * 86_400 else 3600 if age < 30 * 86_400 else 86_400
        bucket = (step, int(t // step)) if step else (0, t)
        if bucket == last_bucket:
            out[-1] = [t, v]          # the latest reading of the bucket stands for it
        else:
            out.append([t, v])
        last_bucket = bucket
    return out


def record(uid: str, value_usd: float, now: float | None = None) -> None:
    now = now or time.time()
    with _lock:
        rows = _series.setdefault(uid, [])
        if rows and now - rows[-1][0] < SNAPSHOT_S / 2:
            rows[-1] = [now, round(value_usd, 4)]
        else:
            rows.append([now, round(value_usd, 4)])
        _series[uid] = _thin(rows, now)
        _save()


def series(uid: str, rng: str = "all", now: float | None = None) -> list[list[float]]:
    now = now or time.time()
    span = RANGES.get(rng)
    rows = list(_series.get(uid) or [])
    return [r for r in rows if span is None or r[0] >= now - span]


def change(uid: str, rng: str, value_now: float | None, now: float | None = None) -> float | None:
    rows = series(uid, rng, now)
    if not rows or value_now is None:
        return None
    return round(value_now - rows[0][1], 4)


_load()
