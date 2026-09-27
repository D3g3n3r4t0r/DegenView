"""What each account's wallets were worth, over time: the profile's chart.

A reading every SNAPSHOT_S (main._wealth_loop) of everything the wallets
hold, in USD. Stored thinned as it ages, so a year of history stays small:
every reading (at most one a minute) for two days, one an hour for a month,
one a day after that.
"""
from __future__ import annotations

import json
import threading
import time

from app.trading.onchain.storage import data_file

_STORE_FILE = data_file("onchain_wealth.json")
SNAPSHOT_S = 5 * 60      # the background reading; the header adds one a minute while the app is open
MIN_GAP_S = 60           # two readings closer than this: the later replaces the earlier
# Lorenzo, 27/09: "il wallet deve avere anche l'andamento 1h 2h 3h 4h 8h; e
# il grafico deve essere realizzato seguendo il valore del portafoglio,
# strettamente legato".
RANGES = {"1h": 3600, "2h": 2 * 3600, "3h": 3 * 3600, "4h": 4 * 3600, "8h": 8 * 3600,
          "24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400, "all": None}
# v2 (27/09): every chain, every token (portfolio.py). Readings from before
# were the site's two wallets only: a different quantity, dropped rather than
# drawn on the same line (Lorenzo: "il grafico non rispetta l'andamento
# reale del portafoglio").
# v3: v2's first readings could be a $0 recorded while Solana did not answer.
VERSION = 3
CARRY_S = 6 * 3600     # a chain that did not answer counts at its last value this long

_lock = threading.Lock()
_series: dict[str, list[list[float]]] = {}
_chains: dict[str, dict[str, list[float]]] = {}     # uid -> chain -> [t, value]


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return                     # older readings measured something else
    _series.update({k: v for k, v in (raw.get("series") or {}).items() if isinstance(v, list)})
    _chains.update({k: v for k, v in (raw.get("chains") or {}).items() if isinstance(v, dict)})


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps({"version": VERSION, "series": _series, "chains": _chains},
                                          separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _series.clear()
    _chains.clear()


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


def combine(uid: str, read: dict[str, float], missing: list[str], now: float | None = None) -> float | None:
    """The total to record: the chains read now, plus each chain that did
    not answer at its last value if that is recent. None when a missing
    chain has no recent value: better no point than a false dip."""
    now = now or time.time()
    last = _chains.setdefault(uid, {})
    for chain, v in read.items():
        last[chain] = [now, round(v, 4)]
    total = sum(read.values())
    for chain in missing:
        prev = last.get(chain)
        if prev is None or now - prev[0] > CARRY_S:
            return None
        total += prev[1]
    return total


def record(uid: str, value_usd: float, now: float | None = None) -> None:
    now = now or time.time()
    with _lock:
        rows = _series.setdefault(uid, [])
        if rows and now - rows[-1][0] < MIN_GAP_S:
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
