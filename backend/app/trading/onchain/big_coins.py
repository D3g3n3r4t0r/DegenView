"""The largest coins by global market cap, to recognise their copies.

A bridged copy (Wormhole, Portal, ...) lives at its own contract, and
CoinGecko often lists it as a coin of its own with a tiny cap: asking for
that contract's cap says "$500k" for AAVE (Lorenzo, 28/09). So the check is
by identity instead: a token whose symbol, or name plus symbol, matches one
of the top coins is that coin, whatever its pool says.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from app.trading.onchain import storage

logger = logging.getLogger(__name__)

MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
PAGES = 2                     # 250 each: the top 500
REFRESH_S = 24 * 3600
RETRY_S = 15 * 60
MIN_CAP_USD = 10_000_000

_STORE = storage.data_file("onchain_big_coins.json")
_SEED = Path(__file__).with_name("big_coins_seed.json")   # shipped snapshot: works from the first second
BRIDGE_WORDS = re.compile(r"wormhole|\(portal\)|bridged|allbridge|sollet|axelar|celer|multichain|layerzero"
                          r"|\((?:wh|pos|pow|eth|bsc|base|sol)\)|\bwrapped\b", re.I)
_state: dict = {"at": 0.0, "next_at": 0.0, "coins": []}   # coins: [{"symbol", "name", "cap"}]
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for f in (_STORE, _SEED):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and isinstance(raw.get("coins"), list) and raw["coins"]:
            # The seed's date is not trusted: the live list is fetched on the first tick anyway.
            _state.update(at=float(raw.get("at") or 0) if f is _STORE else 0.0, coins=raw["coins"])
            return


def _save() -> None:
    try:
        _STORE.write_text(json.dumps({"at": _state["at"], "coins": _state["coins"]}), encoding="utf-8")
    except OSError:
        pass


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_idx: dict = {"of": None, "by_symbol": {}, "named": []}


def _index() -> tuple[dict[str, dict], list[dict]]:
    _load()
    if _idx["of"] is _state["coins"]:
        return _idx["by_symbol"], _idx["named"]
    by_symbol: dict[str, dict] = {}
    for c in _state["coins"]:
        k = _norm(c.get("symbol"))
        if k and float(c.get("cap") or 0) > float((by_symbol.get(k) or {}).get("cap") or 0):
            by_symbol[k] = c
    named = [{"s": _norm(c.get("symbol")), "n": _norm(c.get("name")), **c} for c in _state["coins"]
             if float(c.get("cap") or 0) > MIN_CAP_USD and len(_norm(c.get("symbol"))) >= 3
             and len(_norm(c.get("name"))) >= 3]
    _idx.update({"of": _state["coins"], "by_symbol": by_symbol, "named": named})
    return by_symbol, named


def match(symbol: str | None, name: str | None) -> dict | None:
    """The big coin this token is a copy of, or None.

    Same ticker as a top coin, or a ticker that contains it (WAAVE, AAVE.E)
    with a name that starts like the coin's ("Aave (Wormhole)")."""
    by_symbol, coins = _index()
    sym, nm = _norm(symbol), _norm(name)
    if not sym:
        return None
    c = by_symbol.get(sym)
    if c and float(c.get("cap") or 0) > MIN_CAP_USD:
        return c
    return next((c for c in coins if c["s"] in sym and nm.startswith(c["n"])), None)


def bridged(e: dict) -> bool:
    """A name that says the token is a port from another chain ("Aave (Wormhole)",
    "Wrapped ETH (Portal)"): not a native project, whatever its cap."""
    return bool(BRIDGE_WORDS.search(f"{e.get('name') or ''} {e.get('symbol') or ''}"))


def cap_of(e: dict) -> float:
    c = match(e.get("symbol"), e.get("name"))
    return float(c["cap"]) if c else 0.0


async def refresh(client: httpx.AsyncClient, now: float | None = None) -> bool:
    """Once a day, the top coins by market cap (two CoinGecko requests).
    True when the list changed."""
    _load()
    now = now or time.time()
    if now < _state["next_at"] or now - _state["at"] < REFRESH_S:
        return False
    _state["next_at"] = now + RETRY_S
    coins = []
    for page in range(1, PAGES + 1):
        r = await client.get(MARKETS, params={"vs_currency": "usd", "order": "market_cap_desc",
                                              "per_page": 250, "page": page},
                             timeout=20.0, headers={"Accept": "application/json"})
        if r.status_code != 200:
            logger.info("big_coins: CoinGecko %s on page %s", r.status_code, page)
            return False
        coins += [{"symbol": c.get("symbol"), "name": c.get("name"), "cap": float(c.get("market_cap") or 0)}
                  for c in r.json() if isinstance(c, dict)]
    if coins:
        _state.update(at=now, coins=coins)
        _save()
        logger.info("big_coins: %d top coins loaded", len(coins))
        return True
    return False


def set_for_tests(coins: list[dict]) -> None:
    global _loaded
    _loaded = True
    _state.update(at=time.time(), next_at=0.0, coins=coins)


def reset_for_tests() -> None:
    global _loaded
    _loaded = True
    _state.update(at=0.0, next_at=0.0, coins=[])
