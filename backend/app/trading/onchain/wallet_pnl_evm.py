"""How profitable an EVM wallet's trades were, one network at a time:
last 24 hours, 7 and 30 days (Trading → Copy trading → Wallet profitability).

Asked on 23/10: "aggiungi la possibilita' di fare check anche su wallet che
fanno parte degli EVM, ovvero tutte le reti che sono state integrate nel
wallet EVM" — the six networks of copytrade_evm.CHAINS.

Same rules as the Solana analysis (wallet_pnl.py), whose pure part is
reused as is: closed trades only, from the first buy on an empty position to
the last sell; open positions and sells with no known buy are shown apart.

What differs is reading the history:
- no node lists an address's transactions, so the wallet's ERC-20 Transfers
  (from it and to it) are searched with eth_getLogs over the blocks of the
  last 30 days, in ranges that shrink when a node refuses one and grow back;
- the public nodes keep no month-old state, so the coin paid or received is
  not a balance difference (copytrade_evm's trick for live trades): it is the
  transaction's value when the wallet sent it, plus the wrapped coin a router
  unwrapped (WETH Withdrawal) in the same transaction, which is how a sell
  for ETH/BNB pays out. Wrapped coin and stablecoins moved directly count too;
- a log's time comes from its block, interpolated between two blocks whose
  time is read (block times are steady enough for 24 h / 7 / 30 day windows);
- the coin's dollar price is MEXC's hourly close of the trade's hour.

A busy wallet means many ranges and receipts: the reading has a time budget
per network, and the result says how far back it got.
"""
from __future__ import annotations

import asyncio
import bisect
import logging
import time
from typing import Callable

from app.trading.onchain import copytrade_evm as evm
from app.trading.onchain import wallet_pnl as base

logger = logging.getLogger(__name__)

WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"   # WETH.Withdrawal(src, wad)
FIRST_RANGE = {"monad": 100}         # blocks per eth_getLogs to start with; the rest start at DEFAULT_RANGE
DEFAULT_RANGE = 5_000
MIN_RANGE, MAX_RANGE = 50, 50_000
PARALLEL = 4                         # ranges in flight at once
MAX_TXS = 3_000                      # more trading transactions than this in 30 days: a bot, say how far back
READ_BUDGET_S = 6 * 60               # per network
PRICE_PAIR = {"ETH": "ETHUSDT", "BNB": "BNBUSDT", "MON": "MONUSDT"}
_cache: dict[str, tuple[float, dict]] = {}


def cache_key(chain: str, address: str) -> str:
    return f"{chain}:{evm.norm(address)}"


def cached(chain: str, address: str) -> dict | None:
    hit = _cache.get(cache_key(chain, address))
    return hit[1] if hit and time.time() - hit[0] < base.CACHE_S else None


# ── pure part (tested) ───────────────────────────────────────────────────

def native_delta_from_tx(chain: str, wallet: str, tx: dict, receipt: dict) -> int:
    """The coin the wallet paid (negative) or received (positive) in one
    transaction, without reading any balance: what it sent as value, plus
    what the wrapped-coin contract unwrapped in the same transaction."""
    w = evm.norm(wallet)
    delta = 0
    if (tx.get("from") or "").lower() == w:
        delta -= int(tx.get("value") or "0x0", 16)
    wrapped = evm.CHAINS[chain]["wrapped"]
    if wrapped:
        for log in receipt.get("logs") or []:
            topics = log.get("topics") or []
            if (log.get("address") or "").lower() == wrapped and topics and topics[0].lower() == WITHDRAWAL:
                delta += int(log.get("data") or "0x0", 16)
    return delta


def block_time(block: int, known: list[tuple[int, int]]) -> float:
    """A block's time from the nearest known (block, time) pairs: linear
    inside them, the edge rate outside."""
    blocks = [b for b, _ in known]
    i = bisect.bisect_left(blocks, block)
    if i < len(known) and known[i][0] == block:
        return float(known[i][1])
    lo = known[max(0, min(i - 1, len(known) - 2))]
    hi = known[max(1, min(i, len(known) - 1))]
    if hi[0] == lo[0]:
        return float(lo[1])
    return lo[1] + (block - lo[0]) * (hi[1] - lo[1]) / (hi[0] - lo[0])


def too_wide(error: str) -> bool:
    """A node saying the range is too big (each words it its own way)."""
    e = error.lower()
    return any(k in e for k in ("range", "limit", "exceed", "too many", "too large", "10000", "query returned more"))


# ── network ──────────────────────────────────────────────────────────────

async def _block(chain: str, number: int) -> dict:
    return await evm.rpc(chain, "eth_getBlockByNumber", [hex(number), False]) or {}


async def block_at(chain: str, ts: float, latest: int, latest_ts: int) -> tuple[int, int]:
    """First block at or after ts (binary search, ~25 reads): returns (block, its time)."""
    guess = max(0, latest - int((latest_ts - ts) / evm.CHAINS[chain]["block_s"]))
    lo, hi = max(0, guess - guess // 4 - 1000), latest
    lo_ts = int((await _block(chain, lo)).get("timestamp") or "0x0", 16)
    if lo_ts > ts:
        lo = 0
    while hi - lo > 1:
        mid = (lo + hi) // 2
        mid_ts = int((await _block(chain, mid)).get("timestamp") or "0x0", 16)
        if mid_ts < ts:
            lo = mid
        else:
            hi = mid
    hi_ts = int((await _block(chain, hi)).get("timestamp") or "0x0", 16)
    return hi, hi_ts


async def wallet_logs(chain: str, wallet: str, start: int, end: int, deadline: float,
                      say: Callable[[str], None]) -> tuple[list[dict], int]:
    """Every ERC-20 Transfer from or to the wallet in [start, end], newest
    ranges first; returns (logs, first block actually covered)."""
    topic = evm._topic(wallet)
    step = FIRST_RANGE.get(chain, DEFAULT_RANGE)
    logs: list[dict] = []
    covered = end + 1
    hi = end
    sem = asyncio.Semaphore(PARALLEL)

    async def one(a: int, b: int) -> list[dict]:
        async with sem:
            span = {"fromBlock": hex(a), "toBlock": hex(b)}
            sent, got = await asyncio.gather(
                evm.rpc(chain, "eth_getLogs", [{**span, "topics": [evm.TRANSFER, topic]}]),
                evm.rpc(chain, "eth_getLogs", [{**span, "topics": [evm.TRANSFER, None, topic]}]))
            return (sent or []) + (got or [])

    while hi >= start:
        if time.time() > deadline:
            break
        ranges = []
        b = hi
        for _ in range(PARALLEL):
            if b < start:
                break
            a = max(start, b - step + 1)
            ranges.append((a, b))
            b = a - 1
        results = await asyncio.gather(*(one(a, b) for a, b in ranges), return_exceptions=True)
        failed = next((r for r in results if isinstance(r, Exception)), None)
        if failed is not None:
            if too_wide(str(failed)) and step > MIN_RANGE:
                step = max(MIN_RANGE, step // 4)
                continue
            raise RuntimeError(str(failed)[:200])
        for r in results:
            logs.extend(r)
        hi = ranges[-1][0] - 1
        covered = ranges[-1][0]
        step = min(MAX_RANGE, step * 2)
        say(f"{evm.CHAINS[chain]['label']}: {end - covered + 1:,} of {end - start + 1:,} blocks searched, "
            f"{len({lg['transactionHash'] for lg in logs})} transactions")
    return logs, covered


async def _price_history(native: str, since: float) -> tuple[list[int], list[float]]:
    pair = PRICE_PAIR.get(native)
    if not pair:
        return [], []
    from app.providers.mexc import MexcProvider
    try:
        df = await MexcProvider().fetch_ohlcv(pair, "1h", int((time.time() - since) / 3600) + 48)
    except Exception as exc:  # noqa: BLE001
        logger.warning("wallet_pnl_evm: no %s history (%s), today's price used", pair, exc)
        return [], []
    return [int(ts.timestamp()) for ts in df.index], [float(x) for x in df["close"]]


async def analyze(address: str, chain: str, say: Callable[[str], None] = lambda m: None) -> dict:
    if not evm.is_evm(address):
        raise ValueError("Not an EVM wallet address.")
    if chain not in evm.CHAINS:
        raise ValueError("Unknown network.")
    cfg = evm.CHAINS[chain]
    wallet = evm.norm(address)
    now = time.time()
    since = now - base.WINDOWS["30d"]
    deadline = now + READ_BUDGET_S
    say(f"{cfg['label']}: finding the block of 30 days ago")
    try:
        latest = int(await evm.rpc(chain, "eth_blockNumber", []), 16)
        latest_ts = int((await _block(chain, latest)).get("timestamp") or "0x0", 16) or int(now)
        start, start_ts = await block_at(chain, since, latest, latest_ts)
        logs, covered = await wallet_logs(chain, wallet, start, latest, deadline, say)
    except RuntimeError as exc:
        # The node's own words go to the log; the page gets a sentence.
        logger.warning("wallet_pnl_evm: %s unreadable: %s", chain, exc)
        raise RuntimeError(f"{cfg['label']} is not answering right now: try again in a minute.") from exc
    partial = covered > start

    by_tx: dict[str, int] = {}
    for lg in logs:
        by_tx[lg["transactionHash"]] = int(lg["blockNumber"], 16)
    hashes = sorted(by_tx, key=lambda h: -by_tx[h])
    if len(hashes) > MAX_TXS:
        hashes, partial = hashes[:MAX_TXS], True
        covered = by_tx[hashes[-1]]

    known = sorted({(start, start_ts), (latest, latest_ts)})
    if covered > start:
        mid_ts = int((await _block(chain, covered)).get("timestamp") or "0x0", 16)
        if mid_ts:
            known = sorted(set(known) | {(covered, mid_ts)})

    hours, closes = await _price_history(cfg["native"], since)
    now_price = await evm.native_usd(chain) or (closes[-1] if closes else None)
    sem = asyncio.Semaphore(6)
    unread = 0

    async def read(h: str):
        async with sem:
            try:
                return h, *await asyncio.gather(evm.rpc(chain, "eth_getTransactionByHash", [h]),
                                                evm.rpc(chain, "eth_getTransactionReceipt", [h]))
            except RuntimeError:
                return h, None, None

    swaps: list[dict] = []
    for i in range(0, len(hashes), 60):
        if time.time() > deadline + 120:
            partial = True
            break
        part = await asyncio.gather(*(read(h) for h in hashes[i:i + 60]))
        for h, tx, receipt in part:
            if not tx or not receipt:
                unread += 1
                continue
            if receipt.get("status") != "0x1":
                continue
            tokens = {(lg.get("address") or "").lower() for lg in receipt.get("logs") or []}
            decs = {t: await evm.token_decimals(chain, t) for t in tokens}
            s = evm.parse_evm_swap(chain, wallet, receipt.get("logs") or [],
                                   native_delta_from_tx(chain, wallet, tx, receipt), decs)
            if s is None:
                continue
            t = block_time(by_tx[h], known)
            px = 1.0 if chain == "arc" else base.price_at(hours, closes, t, now_price or 0.0)
            swaps.append({"t": t, "sig": h, "side": s["side"], "mint": s["token"], "units": s["units"],
                          "decimals": s["decimals"], "usd": s["native"] * px + s["stable_usd"]})
        say(f"{cfg['label']}: read {min(i + 60, len(hashes))} of {len(hashes)} transactions, {len(swaps)} swaps")
    if not now_price and chain != "arc" and not hours:
        raise RuntimeError(f"No {cfg['native']} price right now, try again.")

    swaps.sort(key=lambda s: s["t"])
    trades, still, orphan = base.round_trips(swaps)
    span_days = max(1.0, (now - (swaps[0]["t"] if swaps else now)) / base.DAY)
    result = {
        "address": wallet, "chain": chain, "chain_label": cfg["label"], "generated_at": now,
        "coverage": {"from": block_time(covered, known), "transactions": len(hashes), "swaps": len(swaps),
                     "partial": partial, "unread": unread, "price_history": bool(hours) or chain == "arc",
                     "native": cfg["native"]},
        "windows": {k: base.window(trades, still, orphan, now - v) for k, v in base.WINDOWS.items()},
        "still_open": sorted(({"mint": o["mint"], "opened_at": o["opened_at"], "invested_usd": round(o["invested"], 2),
                               "returned_usd": round(o["returned"], 2)} for o in still),
                             key=lambda o: -o["opened_at"])[:20],
        "still_open_count": len(still),
        "tokens": base.tokens(trades),
        "swaps_per_day": round(len(swaps) / span_days, 1),
        "bot_like": len(swaps) / span_days > base.BOT_SWAPS_PER_DAY or len(hashes) >= MAX_TXS,
    }
    _cache[cache_key(chain, wallet)] = (time.time(), result)
    return result
