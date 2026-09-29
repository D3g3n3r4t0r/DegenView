"""The Gem Finder's track record: what happened to what it ranked.

The Meme Sniper has had a memory since VISE; the board had none, so nobody
could say whether its top picks went up. Here every project that enters the
board is written down once, with its price, score and rank at that moment,
and its return is recorded at 7, 30 and 90 days, whether it is still on the
board or not. `stats()` gives, per horizon, the median return and the share
that doubled, for the top ten and for the rest: if the top ten do not beat
the rest, the ranking is not ranking anything.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time

import httpx

from app.trading.onchain import storage
from app.atomic_write import write_text_atomic

logger = logging.getLogger(__name__)

_STORE_FILE = storage.data_file("onchain_gem_track.json")
DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/{chain}/{addresses}"
CHECKPOINTS_D = (7, 30, 90)
POLL_S = 3600
TOP = 10
DOUBLED = 1.0
KEEP = 2000

_track: dict[str, dict] = {}
_state = {"polled_at": 0.0}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _track.update({k: v for k, v in (raw.get("track") or {}).items() if isinstance(v, dict)})


def save() -> None:
    if len(_track) > KEEP:
        for k in sorted(_track, key=lambda k: _track[k]["at"])[:len(_track) - KEEP]:
            del _track[k]
    try:
        write_text_atomic(_STORE_FILE, json.dumps({"track": _track}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _track.clear()
    _state["polled_at"] = 0.0


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def enter(e: dict, score: float, rank: int, now: float | None = None) -> bool:
    """First time on the board with a price: written down, once."""
    k = f"{e['chain']}:{e['token_address']}"
    price = _num(e.get("price_usd"))
    if k in _track or price is None:
        return False
    _track[k] = {"chain": e["chain"], "token_address": e["token_address"], "symbol": e.get("symbol"),
                 "at": now or time.time(), "price": price, "score": score, "rank": rank,
                 "market_cap": e.get("market_cap"), "returns": {}, "last": None, "closed": False}
    return True


def sample(chain: str, token: str, price, now: float | None = None) -> None:
    t = _track.get(f"{chain}:{token}")
    price = _num(price)
    if not t or t["closed"] or price is None:
        return
    now = now or time.time()
    ret = price / t["price"] - 1
    t["last"] = {"at": now, "ret": round(ret, 4)}
    for d in CHECKPOINTS_D:
        if str(d) not in t["returns"] and now - t["at"] >= d * 86400:
            t["returns"][str(d)] = round(ret, 4)
    if len(t["returns"]) == len(CHECKPOINTS_D):
        t["closed"] = True


def open_keys(exclude: set[str] | None = None) -> list[str]:
    return [k for k, t in _track.items() if not t["closed"] and k not in (exclude or set())]


async def poll(client: httpx.AsyncClient, exclude: set[str], now: float | None = None) -> None:
    """Prices for tracked projects that left the board (the board's own
    market poll covers the others), once an hour."""
    now = now or time.time()
    if now - _state["polled_at"] < POLL_S:
        return
    _state["polled_at"] = now
    by_chain: dict[str, list[str]] = {}
    for k in open_keys(exclude):
        chain, token = k.split(":", 1)
        by_chain.setdefault(chain, []).append(token)
    for chain, tokens in by_chain.items():
        for i in range(0, len(tokens), 30):
            r = await client.get(DEX_TOKENS.format(chain=chain, addresses=",".join(tokens[i:i + 30])), timeout=10.0)
            if r.status_code != 200 or not isinstance(r.json(), list):
                continue
            best: dict[str, dict] = {}
            for p in r.json():
                token = (p.get("baseToken") or {}).get("address") or ""
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if token not in best or liq > float((best[token].get("liquidity") or {}).get("usd") or 0):
                    best[token] = p
            for token, p in best.items():
                sample(chain, token, p.get("priceUsd"), now)
            await asyncio.sleep(0.3)
    save()


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _summary(rets: list[float]) -> dict:
    n = len(rets)
    return {"n": n, "median": round(_median(rets), 4) if n else None,
            "positive": round(sum(r > 0 for r in rets) / n, 3) if n else None,
            "doubled": round(sum(r >= DOUBLED for r in rets) / n, 3) if n else None}


def stats() -> dict:
    out = {"tracked": len(_track), "horizons": []}
    for d in CHECKPOINTS_D:
        done = [t for t in _track.values() if str(d) in t["returns"]]
        top = [t["returns"][str(d)] for t in done if (t.get("rank") or 99) <= TOP]
        rest = [t["returns"][str(d)] for t in done if (t.get("rank") or 99) > TOP]
        out["horizons"].append({"days": d, "all": _summary([t["returns"][str(d)] for t in done]),
                                "top": _summary(top), "rest": _summary(rest)})
    return out


_load()
