"""Prices read from the pool itself on the EVM chains, block by block.

Lorenzo, 30/09: "il saldo delle posizioni si aggiorni piu' velocemente
possibile [...] vedere in tempo reale i cambiamenti di prezzo". DexScreener
answers from a CDN cache that is up to 30 s old (cache-control max-age=30,
measured), so the ticking balance could not move faster than that.

Here the deepest pool DexScreener names for a token is read with one
eth_call per pool (getReserves for v2-style pools, slot0 for Uniswap v3),
batched per chain on free public RPCs: the price of the last block, ~1-3 s
on BSC/Base/Robinhood, 12 s on Ethereum. The quote token's USD value
(WETH, WBNB, USDC...) comes from DexScreener's priceUsd / priceNative and is
refreshed with the pool every META_S: it moves far less than the token.

A pool is used only if its first on-chain price agrees with DexScreener's
within MAX_GAP; anything else (v4 pool ids, stable curves, Algebra pools,
an answer that does not decode) goes back to DexScreener for BAD_S.
"""
import time

import httpx

RPC = {
    "base": "https://base-rpc.publicnode.com",
    "bsc": "https://bsc-rpc.publicnode.com",
    "ethereum": "https://ethereum-rpc.publicnode.com",
    "robinhood": "https://rpc.mainnet.chain.robinhood.com",
    "arc": "https://rpc.mainnet.arc.io",
}
GET_RESERVES = "0x0902f1ac"
SLOT0 = "0x3850c7bd"
DECIMALS = "0x313ce567"
META_S = 60.0
USABLE_S = 300.0
BAD_S = 600.0
MAX_GAP = 0.05

_pools: dict[tuple[str, str], dict] = {}
_clock = time.time


def reset_for_tests() -> None:
    _pools.clear()


def _is_addr(a: str) -> bool:
    return isinstance(a, str) and a.startswith("0x") and len(a) == 42


def note_pair(key: tuple[str, str], pair: dict) -> None:
    """Remember the pool DexScreener priced `key` from (its deepest)."""
    chain = key[0]
    if chain not in RPC:
        return
    now = _clock()
    old = _pools.get(key)
    if old and old.get("bad") and now - old["at"] < BAD_S:
        return
    try:
        pool = pair["pairAddress"]
        base = pair["baseToken"]["address"].lower()
        quote = pair["quoteToken"]["address"].lower()
        native = float(pair["priceNative"])
        usd = float(pair["priceUsd"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return
    labels = [str(x).lower() for x in pair.get("labels") or []]
    if not (_is_addr(pool) and _is_addr(base) and _is_addr(quote)) or native <= 0 or usd <= 0 \
            or "v4" in labels or "stable" in labels:
        _pools[key] = {"bad": True, "at": now}
        return
    pool = pool.lower()
    same = old if old and not old.get("bad") and old.get("pool") == pool else None
    _pools[key] = {
        "pool": pool, "kind": "v3" if "v3" in labels else "v2",
        "base": base, "quote": quote, "base_is_0": int(base, 16) < int(quote, 16),
        "ds_native": native, "quote_usd": usd / native, "at": now,
        "dec": same.get("dec") if same else None, "ok": bool(same and same.get("ok")),
    }


def usable(key: tuple[str, str]) -> bool:
    """A pool to read on-chain (its quote price at most USABLE_S old)."""
    p = _pools.get(key)
    return bool(p and not p.get("bad") and _clock() - p["at"] < USABLE_S)


def needs_meta(key: tuple[str, str]) -> bool:
    """Time to ask DexScreener again for the pool and the quote's price."""
    p = _pools.get(key)
    return bool(p and not p.get("bad") and _clock() - p["at"] >= META_S)


def _bad(key: tuple[str, str]) -> None:
    _pools[key] = {"bad": True, "at": _clock()}


def _word(hexdata: str, i: int) -> int:
    body = hexdata[2:] if hexdata.startswith("0x") else hexdata
    return int(body[64 * i:64 * (i + 1)], 16)


def native_price(p: dict, state: str) -> float | None:
    """Quote per base from the pool's raw state and the two decimals."""
    try:
        d0, d1 = p["dec"] if p["base_is_0"] else p["dec"][::-1]
        if p["kind"] == "v3":
            sqrt = _word(state, 0)
            one_per_zero = (sqrt / 2 ** 96) ** 2
        else:
            r0, r1 = _word(state, 0), _word(state, 1)
            one_per_zero = r1 / r0
        one_per_zero *= 10 ** (d0 - d1)
    except (ValueError, TypeError, ZeroDivisionError, IndexError, OverflowError):
        return None
    if one_per_zero <= 0:
        return None
    return one_per_zero if p["base_is_0"] else 1 / one_per_zero


def _call(i: int, to: str, data: str) -> dict:
    return {"jsonrpc": "2.0", "id": i, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]}


async def read(client: httpx.AsyncClient, chain: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """USD price of each key from its pool's latest block; keys whose pool
    fails are left out (and sent back to DexScreener)."""
    jobs, batch = [], []
    for k in keys:
        p = _pools.get(k)
        if not p or p.get("bad"):
            continue
        n = len(batch)
        batch.append(_call(n, p["pool"], SLOT0 if p["kind"] == "v3" else GET_RESERVES))
        dec_at = None
        if p["dec"] is None:
            dec_at = len(batch)
            batch.append(_call(dec_at, p["base"], DECIMALS))
            batch.append(_call(dec_at + 1, p["quote"], DECIMALS))
        jobs.append((k, n, dec_at))
    if not batch:
        return {}
    try:
        r = await client.post(RPC[chain], json=batch)
        if r.status_code != 200:
            return {}
        answers = {a.get("id"): a.get("result") for a in r.json() if isinstance(a, dict)}
    except (httpx.HTTPError, ValueError, TypeError):
        return {}
    out = {}
    for k, n, dec_at in jobs:
        p = _pools[k]
        state = answers.get(n)
        if dec_at is not None:
            try:
                p["dec"] = (_word(answers[dec_at], 0), _word(answers[dec_at + 1], 0))
                if max(p["dec"]) > 36:
                    raise ValueError
            except (KeyError, TypeError, ValueError, IndexError):
                _bad(k)
                continue
        if not isinstance(state, str) or len(state) < 2 + 64 * 2:
            _bad(k)
            continue
        native = native_price(p, state)
        if native is None:
            _bad(k)
            continue
        if not p["ok"]:
            if abs(native / p["ds_native"] - 1) > MAX_GAP:
                _bad(k)
                continue
            p["ok"] = True
        out[k] = native * p["quote_usd"]
    return out
