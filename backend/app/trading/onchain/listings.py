"""
Listing appena nati con liquidita', quasi in tempo reale.

Lorenzo: "voglio che io sia informato sui listing di roba interessante dal
punto di vista di liquidita' con tempi rapidissimi rispetto all'uscita [...]
deve essere proprio quasi istantaneo".

GeckoTerminal da solo non basta: misurato il 23/09, il pool piu' nuovo della
sua lista `new_pools` aveva gia' 7-8 minuti, e la risposta resta in cache 60 s.
Quindi tre fonti, dalla piu' rapida:

- Robinhood Chain: i log `PoolCreated` (Uniswap v3) e `PairCreated` (v2) letti
  dal nodo ogni `CHAIN_POLL_S` secondi, qualunque factory li emetta;
- Solana: i token pump.fun appena "laureati" (pool PumpSwap con liquidita'
  vera), dal feed pubblico di pump.fun, secondi dopo la laurea;
- entrambe: `new_pools` di GeckoTerminal ogni minuto, per tutto il resto
  (Raydium, Meteora, altri DEX).

Un pool appena creato ha liquidita' zero: la liquidita' arriva dopo. Ogni
pool trovato resta "in attesa" per `PENDING_TTL_S` e viene riletto su
DexScreener (30 pool per richiesta) finche' non supera le soglie o scade.
Solo allora parte l'avviso, una volta per ticker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "onchain_listings.json"

ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"
DEXSCREENER_PAIRS = "https://api.dexscreener.com/latest/dex/pairs"
PUMPFUN_COINS = "https://frontend-api-v3.pump.fun/coins"
GECKO_BASE = "https://api.geckoterminal.com/api/v2"

# Soglie dell'avviso: regolabili qui.
LIQ_MIN_USD = 20_000
MCAP_MAX_USD = 20_000_000
LIQ_TO_MCAP_MIN = 0.05
MAX_AGE_S = 6 * 3600          # oltre, non e' piu' un listing
PENDING_TTL_S = 2 * 3600      # quanto si aspetta che arrivi la liquidita'
MAX_PENDING = 300
KEEP_LISTINGS = 40
NOTIFY_MAX_AGE_S = 15 * 60    # fuori dall'app si avvisa solo di cio' che e' davvero appena uscito

TICK_S = 3
CHAIN_POLL_S = 3
PUMPFUN_POLL_S = 8
ENRICH_FRESH_S = 3            # pool trovati negli ultimi FRESH_WINDOW_S
ENRICH_ALL_S = 20             # tutti gli altri in attesa
FRESH_WINDOW_S = 180
GECKO_POLL_S = 60
_MAX_LOG_BLOCKS = 5_000

POOL_CREATED_V3 = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"
PAIR_CREATED_V2 = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

_NOT_A_TOKEN = {
    "SOL", "WSOL", "USDC", "USDT", "USDG", "WETH", "ETH", "DAI", "USDS", "PYUSD",
    "USD1", "USDE", "BTC", "WBTC", "CBBTC", "JITOSOL", "MSOL",
}

SOURCE_LABELS = {"chain": "catena", "pumpfun": "pump.fun", "gecko": "GeckoTerminal"}


@dataclass
class _Pending:
    chain: str
    pair: str
    source: str
    detected_at: float = field(default_factory=time.time)


_pending: dict[str, _Pending] = {}   # chain:pair
_done: dict[str, float] = {}          # chain:pair -> quando e' stato chiuso (avvisato o scaduto)
_alerted_tickers: dict[str, float] = {}  # chain:TICKER -> quando
_listings: list[dict] = []
_subscribers: list[asyncio.Queue] = []
_callbacks: list[Callable[[dict], Awaitable[None]]] = []
_state = {"last_block": 0, "last_tick": 0.0, "sources": {}}


def _key(chain: str, pair: str) -> str:
    return f"{chain}:{pair}"


# ------------------------------------------------------------------ memoria

def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _listings.extend(x for x in raw.get("listings", []) if isinstance(x, dict))
        _alerted_tickers.update(raw.get("tickers") or {})


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps({"listings": _listings, "tickers": _alerted_tickers},
                                          ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


_load()


def recent() -> list[dict]:
    return list(_listings)


def status() -> dict:
    return {
        "pending": len(_pending),
        "last_tick": _state["last_tick"],
        "sources": dict(_state["sources"]),
        "thresholds": {"liq_min_usd": LIQ_MIN_USD, "mcap_max_usd": MCAP_MAX_USD,
                       "liq_to_mcap_min": LIQ_TO_MCAP_MIN, "max_age_h": MAX_AGE_S / 3600},
    }


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def on_listing(fn: Callable[[dict], Awaitable[None]]) -> None:
    _callbacks.append(fn)


def reset_for_tests() -> None:
    _pending.clear()
    _done.clear()
    _alerted_tickers.clear()
    _listings.clear()
    _subscribers.clear()
    _state.update(last_block=0, last_tick=0.0, sources={})


# ------------------------------------------------------------------- scoperta

def add_pending(chain: str, pair: str, source: str) -> bool:
    k = _key(chain, pair)
    if not pair or k in _pending or k in _done:
        return False
    if len(_pending) >= MAX_PENDING:  # si sacrifica il piu' vecchio, mai il nuovo
        oldest = min(_pending, key=lambda x: _pending[x].detected_at)
        del _pending[oldest]
        _done[oldest] = time.time()
    _pending[k] = _Pending(chain, pair, source)
    return True


def pools_from_logs(logs: list[dict]) -> list[str]:
    """Indirizzo del pool da un log PoolCreated (ultima parola dei dati) o
    PairCreated (prima parola)."""
    pools = []
    for log in logs:
        data = (log.get("data") or "")[2:]
        topic = (log.get("topics") or [""])[0]
        if topic == POOL_CREATED_V3 and len(data) >= 128:
            pools.append("0x" + data[-40:])
        elif topic == PAIR_CREATED_V2 and len(data) >= 64:
            pools.append("0x" + data[24:64])
    return pools


def pools_from_pumpfun(coins: list[dict], now: float | None = None) -> list[str]:
    now = now or time.time()
    out = []
    for c in coins:
        if not c.get("complete"):
            continue
        created = (c.get("created_timestamp") or 0) / 1000
        pool = c.get("pump_swap_pool") or c.get("pool_address") or c.get("raydium_pool")
        if pool and now - created <= MAX_AGE_S:
            out.append(pool)
    return out


def evaluate_pair(pair: dict, now: float | None = None) -> dict | None:
    """Un pair DexScreener che supera le soglie, come voce di listing."""
    now = now or time.time()
    base = pair.get("baseToken") or {}
    symbol = (base.get("symbol") or "").strip()
    if not symbol or symbol.upper() in _NOT_A_TOKEN:
        return None
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    cap = pair.get("marketCap") or pair.get("fdv")
    created = (pair.get("pairCreatedAt") or 0) / 1000
    if liq < LIQ_MIN_USD or not cap or float(cap) > MCAP_MAX_USD or liq / float(cap) < LIQ_TO_MCAP_MIN:
        return None
    if created and now - created > MAX_AGE_S:
        return None
    return {
        "chain": pair.get("chainId"),
        "symbol": symbol,
        "name": base.get("name") or symbol,
        "token_address": base.get("address") or "",
        "pair_address": pair.get("pairAddress") or "",
        "pair_url": pair.get("url") or "",
        "dex": pair.get("dexId") or "",
        "liquidity_usd": liq,
        "market_cap": float(cap),
        "created_at": created or None,
    }


def _is_expired(p: _Pending, now: float) -> bool:
    return now - p.detected_at > PENDING_TTL_S


async def _publish(item: dict) -> None:
    _listings.insert(0, item)
    del _listings[KEEP_LISTINGS:]
    _save()
    for q in list(_subscribers):
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            pass
    fresh = item.get("created_at") and item["found_at"] - item["created_at"] <= NOTIFY_MAX_AGE_S
    for fn in list(_callbacks) if fresh else []:
        try:
            await fn(item)
        except Exception:
            logger.exception("listings: callback fallita")


async def accept_pairs(pairs: list[dict], now: float | None = None) -> list[dict]:
    """Chiude i pending che ora superano le soglie. Uno per ticker per chain."""
    now = now or time.time()
    published = []
    for pair in pairs:
        chain = pair.get("chainId")
        k = _key(chain, pair.get("pairAddress") or "")
        pending = _pending.get(k)
        if pending is None:
            continue
        item = evaluate_pair(pair, now)
        if item is None:
            continue
        del _pending[k]
        _done[k] = now
        ticker = f"{chain}:{item['symbol'].upper()}"
        if ticker in _alerted_tickers:
            continue  # una copia con lo stesso nome: il primo con liquidita' vince
        _alerted_tickers[ticker] = now
        item.update(found_at=now, source=pending.source,
                    latency_s=round(now - item["created_at"]) if item["created_at"] else None)
        await _publish(item)
        published.append(item)
    for k, p in list(_pending.items()):
        if _is_expired(p, now):
            del _pending[k]
            _done[k] = now
    for k, ts in list(_done.items()):
        if now - ts > 2 * PENDING_TTL_S:
            del _done[k]
    for k, ts in list(_alerted_tickers.items()):
        if now - ts > 7 * 86400:
            del _alerted_tickers[k]
    return published


# --------------------------------------------------------------------- fonti

async def _poll_chain(client: httpx.AsyncClient) -> None:
    async def rpc(method: str, params: list):
        r = await client.post(ROBINHOOD_RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        return body["result"]

    head = int(await rpc("eth_blockNumber", []), 16)
    start = _state["last_block"] + 1 if _state["last_block"] else head
    start = max(start, head - _MAX_LOG_BLOCKS)
    if start > head:
        return
    logs = await rpc("eth_getLogs", [{"fromBlock": hex(start), "toBlock": hex(head),
                                      "topics": [[POOL_CREATED_V3, PAIR_CREATED_V2]]}])
    _state["last_block"] = head
    for pool in pools_from_logs(logs):
        add_pending("robinhood", pool, "chain")


async def _poll_pumpfun(client: httpx.AsyncClient) -> None:
    r = await client.get(PUMPFUN_COINS, params={"offset": 0, "limit": 50, "sort": "last_trade_timestamp",
                                                "order": "DESC", "complete": "true"})
    if r.status_code == 200 and isinstance(r.json(), list):
        for pool in pools_from_pumpfun(r.json()):
            add_pending("solana", pool, "pumpfun")


async def _poll_gecko(client: httpx.AsyncClient) -> None:
    for chain in ("solana", "robinhood"):
        r = await client.get(f"{GECKO_BASE}/networks/{chain}/new_pools", params={"page": 1},
                             headers={"Accept": "application/json"})
        if r.status_code == 200:
            for pool in r.json().get("data") or []:
                add_pending(chain, (pool.get("attributes") or {}).get("address") or "", "gecko")
        await asyncio.sleep(2.1)


async def _enrich(client: httpx.AsyncClient, *, fresh_only: bool) -> None:
    now = time.time()
    by_chain: dict[str, list[str]] = {}
    for p in _pending.values():
        if fresh_only and now - p.detected_at > FRESH_WINDOW_S:
            continue
        by_chain.setdefault(p.chain, []).append(p.pair)
    pairs: list[dict] = []
    for chain, pools in by_chain.items():
        for i in range(0, len(pools), 30):
            r = await client.get(f"{DEXSCREENER_PAIRS}/{chain}/{','.join(pools[i:i + 30])}")
            if r.status_code == 200:
                pairs += (r.json() or {}).get("pairs") or []
    await accept_pairs(pairs)


async def _run(name: str, every: float, fn, client: httpx.AsyncClient, now: float) -> None:
    src = _state["sources"].setdefault(name, {"last_ok": 0.0, "last_try": 0.0, "error": ""})
    if now - src["last_try"] < every:
        return
    src["last_try"] = now
    try:
        await fn(client)
        src.update(last_ok=time.time(), error="")
    except Exception as exc:  # una fonte giu' non ferma le altre
        src["error"] = str(exc)[:120]
        logger.info("listings: %s: %s", name, exc)


START_DELAY_S = 10


async def listings_loop() -> None:
    await asyncio.sleep(START_DELAY_S)
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            now = time.time()
            _state["last_tick"] = now
            await asyncio.gather(
                _run("chain", CHAIN_POLL_S, _poll_chain, client, now),
                _run("pumpfun", PUMPFUN_POLL_S, _poll_pumpfun, client, now),
                _run("gecko", GECKO_POLL_S, _poll_gecko, client, now),
            )
            await _run("dexscreener", ENRICH_FRESH_S, lambda c: _enrich(c, fresh_only=True), client, now)
            await _run("dexscreener_all", ENRICH_ALL_S, lambda c: _enrich(c, fresh_only=False), client, now)
            await asyncio.sleep(TICK_S)
