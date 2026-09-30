"""The Gem Finder's track record: what happened to what it chose.

The Meme Sniper has had a memory since VISE; the board had none, so nobody
could say whether its top picks went up. Here every project that enters the
board is written down once, with its price, score and rank at that moment,
and its return is recorded at 1, 3, 7, 30 and 90 days, whether it is still on
the board or not. `stats()` gives, per horizon, the median return and the share
that doubled, for the top ten and for the rest: if the top ten do not beat
the rest, the ranking is not ranking anything.

Lorenzo, 30/09 ("applica tutto"): a return without its reasons teaches
nothing, and a filter judged only on what it let in cannot be judged at all.
So each case also freezes a decision receipt (every part of the score, the
market, the rules version, `receipt = sha256(canonical json)`), and the
projects the board did not take are followed the same way: every "studied"
one and a fixed one-in-five sample of the "rejected" (by address hash, so the
sample cannot be steered). Each case also keeps its best and worst return,
which of +100% / -50% came first, and the chain's own coin over the same
window, so a falling market is not read as a bad ranking.
"""
from __future__ import annotations

import asyncio
import hashlib
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
CHECKPOINTS_D = (1, 3, 7, 30, 90)
POLL_S = 3600
TOP = 10
DOUBLED = 1.0
HALVED = -0.5
KEEP = 8000
DECISIONS = ("ranked", "studied", "rejected")
REJECTED_SAMPLE = 5              # one rejected project in five is followed
KRAKEN = "https://api.kraken.com/0/public/Ticker"
# The chain's own coin as the market it moves in (Kraken: public, no key).
BENCH_PAIR = {"solana": "SOLUSD", "bsc": "BNBUSD"}
BENCH_DEFAULT = "ETHUSD"         # ethereum, base, robinhood
BENCH_TTL_S = 2 * 3600

_track: dict[str, dict] = {}
_state = {"polled_at": 0.0}
_bench: dict[str, tuple[float, float]] = {}   # pair -> (price, at)


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
    _bench.clear()
    _state["polled_at"] = 0.0


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def base_key(k: str) -> str:
    return k.split("#", 1)[0]


def case_key(chain: str, token: str, decision: str) -> str:
    """The board's cases keep their old key; the others get a suffix, so a
    project studied first and ranked later is two cases, each with its own
    entry price."""
    k = f"{chain}:{token}"
    return k if decision == "ranked" else f"{k}#{decision}"


def sampled(chain: str, token: str) -> bool:
    return int(hashlib.sha256(f"{chain}:{token}".encode()).hexdigest()[:8], 16) % REJECTED_SAMPLE == 0


def bench_pair(chain: str) -> str:
    return BENCH_PAIR.get(chain, BENCH_DEFAULT)


def bench_price(chain: str, now: float) -> float | None:
    hit = _bench.get(bench_pair(chain))
    return hit[0] if hit and now - hit[1] < BENCH_TTL_S else None


def receipt_of(case: dict) -> str:
    frozen = {k: case.get(k) for k in ("chain", "token_address", "symbol", "at", "price", "score", "rank",
                                       "market_cap", "decision", "why", "parts", "rules_v", "bench0")}
    return hashlib.sha256(_canon(frozen).encode("utf-8")).hexdigest()


def _open(e: dict, decision: str, score, rank, why: str, parts: dict | None, rules_v: str | None,
          now: float | None) -> bool:
    k = case_key(e["chain"], e["token_address"], decision)
    price = _num(e.get("price_usd"))
    if k in _track or price is None:
        return False
    now = now or time.time()
    case = {"chain": e["chain"], "token_address": e["token_address"], "symbol": e.get("symbol"),
            "at": now, "price": price, "score": score, "rank": rank,
            "market_cap": e.get("market_cap"), "returns": {}, "last": None, "closed": False,
            "decision": decision, "why": why or "", "parts": parts, "rules_v": rules_v,
            "bench0": bench_price(e["chain"], now), "bench": {}, "hi": 0.0, "lo": 0.0, "first": None}
    case["receipt"] = receipt_of(case)
    _track[k] = case
    return True


def enter(e: dict, score: float, rank: int, now: float | None = None, parts: dict | None = None,
          rules_v: str | None = None) -> bool:
    """First time on the board with a price: written down, once."""
    return _open(e, "ranked", score, rank, "", parts, rules_v, now)


def decide(e: dict, decision: str, why: str = "", score=None, parts: dict | None = None,
           rules_v: str | None = None, now: float | None = None) -> bool:
    """A project the board studied or rejected, frozen the first time.
    Rejected ones only when sampled."""
    if decision not in ("studied", "rejected"):
        raise ValueError(decision)
    if decision == "rejected" and not sampled(e["chain"], e["token_address"]):
        return False
    return _open(e, decision, score, None, why, parts, rules_v, now)


def receipt_for(chain: str, token: str) -> str | None:
    """The receipt of the decision that put a token where it is: the board's
    first, else the studied one. What a trade carries as its reason."""
    for decision in ("ranked", "studied"):
        t = _track.get(case_key(chain, token, decision))
        if t and t.get("receipt"):
            return t["receipt"]
    return None


def _step(t: dict, price: float, now: float) -> None:
    ret = price / t["price"] - 1
    t["last"] = {"at": now, "ret": round(ret, 4)}
    t["hi"], t["lo"] = round(max(t.get("hi") or 0.0, ret), 4), round(min(t.get("lo") or 0.0, ret), 4)
    if t.get("first") is None:
        if ret >= DOUBLED:
            t["first"], t["first_at"] = "double", now
        elif ret <= HALVED:
            t["first"], t["first_at"] = "halve", now
    b0, b = t.get("bench0"), bench_price(t["chain"], now)
    for d in CHECKPOINTS_D:
        if str(d) not in t["returns"] and now - t["at"] >= d * 86400:
            t["returns"][str(d)] = round(ret, 4)
            if b0 and b:
                t.setdefault("bench", {})[str(d)] = round(b / b0 - 1, 4)
    if len(t["returns"]) == len(CHECKPOINTS_D):
        t["closed"] = True


def sample(chain: str, token: str, price, now: float | None = None) -> None:
    price = _num(price)
    if price is None:
        return
    now = now or time.time()
    for decision in DECISIONS:
        t = _track.get(case_key(chain, token, decision))
        if t and not t["closed"]:
            _step(t, price, now)


def open_keys(exclude: set[str] | None = None) -> list[str]:
    """Tokens (not cases) with an open case, outside `exclude`."""
    out = dict.fromkeys(base_key(k) for k, t in _track.items() if not t["closed"])
    return [k for k in out if k not in (exclude or set())]


async def _poll_bench(client: httpx.AsyncClient, now: float) -> None:
    pairs = sorted({bench_pair(t["chain"]) for t in _track.values() if not t["closed"]} | {"SOLUSD", BENCH_DEFAULT})
    try:
        r = await client.get(KRAKEN, params={"pair": ",".join(pairs)}, timeout=10.0)
        body = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return
    if body.get("error") or not isinstance(body.get("result"), dict):
        return
    # Kraken answers under its own names (ETHUSD -> XETHZUSD): match by the asset.
    for name, row in body["result"].items():
        for pair in pairs:
            asset = pair[:-3]
            if name == pair or (name.startswith(("X" + asset, asset)) and name.endswith("USD")):
                try:
                    price = float(row["c"][0])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if price > 0:
                    _bench[pair] = (price, now)


async def poll(client: httpx.AsyncClient, exclude: set[str], now: float | None = None) -> None:
    """Prices for tracked projects that left the board (the board's own
    market poll covers the others), once an hour."""
    now = now or time.time()
    if now - _state["polled_at"] < POLL_S:
        return
    _state["polled_at"] = now
    await _poll_bench(client, now)
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


def excess(t: dict, d) -> float | None:
    """Return over the chain's own coin in the same window."""
    r, b = (t.get("returns") or {}).get(str(d)), (t.get("bench") or {}).get(str(d))
    return round(r - b, 4) if r is not None and b is not None else None


def stats() -> dict:
    cases = list(_track.values())
    ranked = [t for t in cases if t.get("decision", "ranked") == "ranked"]
    out = {"tracked": len(ranked), "cases": {d: sum(t.get("decision", "ranked") == d for t in cases) for d in DECISIONS},
           "horizons": []}
    for d in CHECKPOINTS_D:
        done = [t for t in ranked if str(d) in t["returns"]]
        top = [t["returns"][str(d)] for t in done if (t.get("rank") or 99) <= TOP]
        rest = [t["returns"][str(d)] for t in done if (t.get("rank") or 99) > TOP]
        row = {"days": d, "all": _summary([t["returns"][str(d)] for t in done]),
               "top": _summary(top), "rest": _summary(rest)}
        # The filter's own test: what it took against what it left out.
        for dec in ("studied", "rejected"):
            row[dec] = _summary([t["returns"][str(d)] for t in cases
                                 if t.get("decision") == dec and str(d) in t["returns"]])
        ex = [x for x in (excess(t, d) for t in done) if x is not None]
        row["excess"] = {"n": len(ex), "median": round(_median(ex), 4) if ex else None}
        out["horizons"].append(row)
    firsts = [t["first"] for t in ranked if t.get("first")]
    out["first"] = {"double": firsts.count("double"), "halve": firsts.count("halve")}
    return out


_load()
