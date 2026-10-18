"""The listing date of a gem the sources gave no creation date (Lorenzo,
17/10: "utilizzare come data di creazione delle gemme che attualmente non
hanno data la data di listing sull'exchange in cui viene analizzata").

A DEX gem: the oldest pool DexScreener lists for the token. A layer (its
pair is "exchange:PAIR", layers.py): the first monthly candle of the pair on
Binance or MEXC. Read a few at a time by leaderboard.live_market_loop, kept
on file; only whitekobra's gem view reads them (main._with_listing_dates).
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.atomic_write import write_text_atomic
from app.trading.onchain import storage

logger = logging.getLogger(__name__)

_FILE = storage.data_file("onchain_listing_dates.json")
PER_TURN = 5                     # reads per minute, on top of the live market
RETRY_S = 24 * 3600              # a read that found nothing waits a day
DEX_PAIRS = "https://api.dexscreener.com/token-pairs/v1/{chain}/{token}"
KLINES = {
    "binance": "https://api.binance.com/api/v3/klines",
    "mexc": "https://api.mexc.com/api/v3/klines",
}

# 2: a layer's date read from the whole monthly history. Version 1 asked MEXC
# for startTime=0, which MEXC ignores: every MEXC layer came back "listed"
# this month (Lorenzo, 18/10: "I layer [...] hanno tutti la stessa data").
VERSION = 2
_dates: dict[str, dict] = {}     # "chain:token" -> {"at": listing ts or None, "checked": ts, "v": VERSION}
_loaded = False
_source = None                   # () -> rows of the gem view, set by main.py


def _key(chain: str, token: str) -> str:
    return f"{chain}:{token}"


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    # Layer dates of an older version are wrong (see VERSION): read again.
    _dates.update({k: v for k, v in raw.items() if not k.startswith("layer:") or v.get("v") == VERSION})


def _save() -> None:
    try:
        write_text_atomic(_FILE, json.dumps(_dates), encoding="utf-8")
    except OSError:
        logger.exception("listing dates not saved")


def reset_for_tests() -> None:
    global _loaded
    _dates.clear()
    _loaded = True


def set_source(fn) -> None:
    global _source
    _source = fn


def get(chain: str, token: str) -> float | None:
    _load()
    return (_dates.get(_key(chain, token)) or {}).get("at")


async def _dex_listing(client: httpx.AsyncClient, chain: str, token: str) -> float | None:
    r = await client.get(DEX_PAIRS.format(chain=chain, token=token), timeout=10.0)
    if r.status_code != 200 or not isinstance(r.json(), list):
        return None
    born = [p["pairCreatedAt"] / 1000 for p in r.json() if isinstance(p, dict) and p.get("pairCreatedAt")]
    return min(born) if born else None


async def _cex_listing(client: httpx.AsyncClient, pair_address: str) -> float | None:
    exchange, _, pair = (pair_address or "").partition(":")
    url = KLINES.get(exchange.lower())
    if not url or not pair:
        return None
    # The last 1000 months, oldest first: the first candle is the listing.
    # No startTime, which MEXC ignores.
    r = await client.get(url, params={"symbol": pair, "interval": "1M", "limit": 1000}, timeout=10.0)
    rows = r.json() if r.status_code == 200 else None
    return min(row[0] for row in rows) / 1000 if isinstance(rows, list) and rows and all(rows) else None


async def fill(client: httpx.AsyncClient, now: float | None = None) -> int:
    """Reads the listing date of up to PER_TURN gems of the view that have
    no creation date. Returns how many were read."""
    _load()
    if _source is None:
        return 0
    now = now or time.time()
    todo = []
    for e in _source():
        if e.get("launched_at") or not e.get("token_address"):
            continue
        k = _key(e.get("chain") or "", e["token_address"])
        seen = _dates.get(k)
        if seen and (seen.get("at") or now - (seen.get("checked") or 0) < RETRY_S):
            continue
        todo.append((k, e))
        if len(todo) >= PER_TURN:
            break
    for k, e in todo:
        try:
            if e.get("chain") == "layer":
                at = await _cex_listing(client, e.get("pair_address") or "")
            else:
                at = await _dex_listing(client, e["chain"], e["token_address"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            at = None
        _dates[k] = {"at": at, "checked": now, "v": VERSION}
    if todo:
        _save()
    return len(todo)
