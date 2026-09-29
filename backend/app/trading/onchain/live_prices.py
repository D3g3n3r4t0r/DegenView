"""Live USD prices of the tokens a wallet holds, for the ticking balance.

Lorenzo, 29/09, on pump.fun's app: "il saldo delle crypto nel wallet si
aggiorna in modo frenetico costantemente [...] nel simulato vedo che
praticamente non si aggiorna mai il valore del token".

One shared cache for every screen and every user: the browser asks every
couple of seconds, the server asks DexScreener at most once per token per
TTL, in batches of 30 per chain (its /tokens/v1 endpoint, 300 calls a
minute, free, no key, every trade moves priceUsd). GeckoTerminal is the
fallback when DexScreener does not answer (30 calls a minute, so only
then). A token neither source answers keeps its last price with its age,
up to STALE_S; after that it is left out, never invented.
"""
import asyncio
import time
from collections import deque

import httpx

DEXSCREENER_TOKENS = "https://api.dexscreener.com/tokens/v1/{chain}/{addrs}"
GECKO_TOKENS = "https://api.geckoterminal.com/api/v2/simple/networks/{network}/token_price/{addrs}"
TTL_S = 1.5
STALE_S = 180.0
BATCH = 30
MAX_IDS = 60
# Our own budget under DexScreener's 300/min, shared by every user.
DS_PER_MIN = 240
GT_PER_MIN = 25

CHAINS = {"solana": "solana", "robinhood": "robinhood", "base": "base", "ethereum": "eth", "bsc": "bsc"}

_cache: dict[tuple[str, str], tuple[float, float, str]] = {}   # (chain, addr) -> (price, fetched_at, source)
_calls: dict[str, deque] = {"ds": deque(), "gt": deque()}
_lock = asyncio.Lock()
_clock = time.time


def reset_for_tests() -> None:
    _cache.clear()
    for q in _calls.values():
        q.clear()


def _key(chain: str, addr: str) -> tuple[str, str]:
    # EVM addresses are case-insensitive, Solana mints are not.
    return chain, addr.lower() if addr.startswith("0x") else addr


def _budget(name: str, per_min: int) -> bool:
    now = _clock()
    q = _calls[name]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_min:
        return False
    q.append(now)
    return True


def parse_ids(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in (raw or "").split(","):
        chain, _, addr = part.strip().partition(":")
        if chain in CHAINS and addr.isalnum() and 32 <= len(addr) <= 44:
            k = _key(chain, addr)
            if k not in out:
                out.append(k)
    return out[:MAX_IDS]


def _best_prices(pairs: list[dict], chain: str) -> dict[tuple[str, str], float]:
    """Per base token, the price of its deepest pool."""
    best: dict[tuple[str, str], tuple[float, float]] = {}
    for p in pairs or []:
        try:
            if p.get("chainId") != chain:
                continue
            k = _key(chain, p["baseToken"]["address"])
            price = float(p["priceUsd"])
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and (k not in best or liq > best[k][1]):
            best[k] = (price, liq)
    return {k: v[0] for k, v in best.items()}


async def _dexscreener(client: httpx.AsyncClient, chain: str, addrs: list[str]) -> dict[tuple[str, str], float]:
    if not _budget("ds", DS_PER_MIN):
        return {}
    try:
        r = await client.get(DEXSCREENER_TOKENS.format(chain=chain, addrs=",".join(addrs)))
        if r.status_code != 200:
            return {}
        return _best_prices(r.json(), chain)
    except (httpx.HTTPError, ValueError):
        return {}


async def _gecko(client: httpx.AsyncClient, chain: str, addrs: list[str]) -> dict[tuple[str, str], float]:
    if not _budget("gt", GT_PER_MIN):
        return {}
    try:
        r = await client.get(GECKO_TOKENS.format(network=CHAINS[chain], addrs=",".join(addrs)))
        if r.status_code != 200:
            return {}
        prices = r.json()["data"]["attributes"]["token_prices"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return {}
    out = {}
    for addr, v in (prices or {}).items():
        try:
            if v is not None and float(v) > 0:
                out[_key(chain, addr)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


async def _refresh(keys: list[tuple[str, str]]) -> None:
    by_chain: dict[str, list[str]] = {}
    for chain, addr in keys:
        by_chain.setdefault(chain, []).append(addr)
    async with httpx.AsyncClient(timeout=4.0) as client:
        jobs = []
        for chain, addrs in by_chain.items():
            for i in range(0, len(addrs), BATCH):
                jobs.append((chain, addrs[i:i + BATCH]))
        found = await asyncio.gather(*(_dexscreener(client, c, a) for c, a in jobs))
        now = _clock()
        seen = set()
        for got in found:
            for k, price in got.items():
                _cache[k] = (price, now, "dexscreener")
                seen.add(k)
        missing = [(c, [a for a in batch if (c, a) not in seen]) for c, batch in jobs]
        missing = [(c, a) for c, a in missing if a]
        if missing:
            for got in await asyncio.gather(*(_gecko(client, c, a) for c, a in missing)):
                for k, price in got.items():
                    _cache[k] = (price, _clock(), "geckoterminal")


async def prices(keys: list[tuple[str, str]]) -> dict[str, dict]:
    """{"chain:addr": {"p": price, "age": seconds, "src": source}} for every
    key with a price no older than STALE_S."""
    stale = [k for k in keys if k not in _cache or _clock() - _cache[k][1] >= TTL_S]
    if stale:
        async with _lock:   # one fetch at a time: the next caller finds it cached
            stale = [k for k in stale if k not in _cache or _clock() - _cache[k][1] >= TTL_S]
            if stale:
                await _refresh(stale)
    now = _clock()
    out = {}
    for k in keys:
        hit = _cache.get(k)
        if hit and now - hit[1] < STALE_S:
            out[f"{k[0]}:{k[1]}"] = {"p": hit[0], "age": round(now - hit[1], 1), "src": hit[2]}
    return out
