"""Copy trading of EVM wallets: one 0x address, six networks (23/10).

Lorenzo, 23/10, with a screenshot of FOMO's address list: "oltre al wallet
Solana, anche un aggregatore di wallet EVM [...] un indirizzo che mette
insieme piu' wallet EVM permette di fare copy trading su tutte le reti EVM".
Choices made when asked: Base, BNB Chain, Ethereum, Robinhood Chain, Arc and
Monad; the account's Robinhood wallet is the EVM wallet (an EVM key is the
same address on every EVM network); KyberSwap for quotes; every account.

Phase 2 of the plan (HANDOVER.md): simulated only. Following an EVM wallet
in "real" is refused in copytrade.set_follow until phase 3.

Same rules, store and limits as the Solana engine (copytrade.py): follows,
positions and trades live in the same account, so the daily cap and the
open-position cap count Solana and EVM together. What differs per chain:
- detection: no logsSubscribe-by-address on EVM, so every few seconds one
  eth_getLogs for ERC-20 Transfers from the followed wallets and one for
  Transfers to them, over the blocks since the last look;
- reading: parse_evm_swap() nets the wallet's token transfers in the
  receipt plus its native balance change across the block (gas added back):
  one token up = buy, one token down = sell, anything else is ignored;
- quotes: KyberSwap's aggregator where it trades (Base, BNB, Ethereum,
  Monad), the Uniswap v3 quoter the server already uses on Robinhood Chain;
  Arc has no trusted source yet, so its trades are seen and logged, not copied.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

import httpx

from app.trading.onchain import copytrade, rpc_client

logger = logging.getLogger(__name__)

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"     # KyberSwap's name for the chain's own coin
KYBER = "https://aggregator-api.kyberswap.com/{slug}/api/v1/routes"
KYBER_CLIENT = "liquidityengine"

# quote: "kyber" | "uniswap" | None (seen and logged, never copied).
# stables: address -> decimals (USDC on BNB Chain has 18, on Base/Ethereum 6).
CHAINS: dict[str, dict] = {
    "base": {"label": "Base", "native": "ETH", "block_s": 2.0, "quote": "kyber", "slug": "base",
             "wrapped": "0x4200000000000000000000000000000000000006",
             "stables": {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,
                         "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": 6},
             "dex": "base", "tx": "https://basescan.org/tx/"},
    "bsc": {"label": "BNB Chain", "native": "BNB", "block_s": 0.75, "quote": "kyber", "slug": "bsc",
            "wrapped": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
            "stables": {"0x55d398326f99059ff775485246999027b3197955": 18,
                        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": 18},
            "dex": "bsc", "tx": "https://bscscan.com/tx/"},
    "ethereum": {"label": "Ethereum", "native": "ETH", "block_s": 12.0, "quote": "kyber", "slug": "ethereum",
                 "wrapped": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                 "stables": {"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,
                             "0xdac17f958d2ee523a2206206994597c13d831ec7": 6},
                 "dex": "ethereum", "tx": "https://etherscan.io/tx/"},
    "robinhood": {"label": "Robinhood Chain", "native": "ETH", "block_s": 1.0, "quote": "uniswap", "slug": None,
                  "wrapped": "0x0bd7d308f8e1639fab988df18a8011f41eacad73", "stables": {},
                  "dex": "robinhood", "tx": None},
    "monad": {"label": "Monad", "native": "MON", "block_s": 0.5, "quote": "kyber", "slug": "monad",
              "wrapped": None, "stables": {}, "dex": "monad", "tx": None},
    "arc": {"label": "Arc", "native": "USDC", "block_s": 1.0, "quote": None, "slug": None,
            "wrapped": None, "stables": {}, "dex": "arc", "tx": None},
}
POLL_S = {"ethereum": 6.0}          # the rest: every 3 s
DEFAULT_POLL_S = 3.0
LOOKBACK_S = 30                     # first look after start: this far back
MAX_RANGE = 2000                    # blocks per eth_getLogs, under the public nodes' caps
MIN_LEADER_USD = 1.0                # less paid than this is a transfer or dust, not a trade

_handled: set[str] = set()
_last_block: dict[str, int] = {}
_decimals: dict[tuple[str, str], int] = {}
_balance_cache: dict[str, tuple[float, dict]] = {}
status: dict[str, dict] = {c: {"state": "idle", "last_block": None, "error": ""} for c in CHAINS}


class NoRoute(RuntimeError):
    """No quote source can trade this pair on this chain."""


# ── addresses ────────────────────────────────────────────────────────────

def is_evm(address: str) -> bool:
    a = (address or "").strip()
    return len(a) == 42 and a[:2].lower() == "0x" and all(c in "0123456789abcdefABCDEF" for c in a[2:])


def norm(address: str) -> str:
    return address.strip().lower()


def _topic(address: str) -> str:
    return "0x" + "0" * 24 + norm(address)[2:]


def _addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def copyable(chain: str) -> bool:
    return CHAINS[chain]["quote"] is not None


# ── reading a transaction (pure, tested) ─────────────────────────────────

def parse_evm_swap(chain: str, wallet: str, logs: list[dict], native_delta_wei: int,
                   decimals: dict[str, int]) -> dict | None:
    """The wallet's swap in a receipt, or None when it is not one.

    native_delta_wei: the wallet's native balance change across the block with
    the gas it paid added back. The wrapped native counts as native, the
    chain's stablecoins as dollars; exactly one other token must move.
    {side, token, decimals, units, raw, native, stable_usd}."""
    cfg = CHAINS[chain]
    w = norm(wallet)
    raw: dict[str, int] = {}
    for log in logs or []:
        topics = log.get("topics") or []
        if len(topics) != 3 or (topics[0] or "").lower() != TRANSFER:     # 4 topics = an NFT
            continue
        src, dst = _addr(topics[1]), _addr(topics[2])
        if w not in (src, dst) or src == dst:
            continue
        try:
            amount = int(log.get("data") or "0x0", 16)
        except ValueError:
            continue
        token = (log.get("address") or "").lower()
        raw[token] = raw.get(token, 0) + (amount if dst == w else -amount)
    native = native_delta_wei / 1e18
    stable = 0.0
    tokens = {}
    for token, delta in raw.items():
        if not delta:
            continue
        if token == cfg["wrapped"]:
            native += delta / 1e18
        elif token in cfg["stables"]:
            stable += delta / 10 ** cfg["stables"][token]
        else:
            tokens[token] = delta
    if len(tokens) != 1:
        return None
    token, delta = next(iter(tokens.items()))
    side = "buy" if delta > 0 else "sell"
    if side == "buy" and not (native < 0 or stable < 0):
        return None                    # tokens arrived, nothing paid: a transfer or an airdrop
    if side == "sell" and not (native > 0 or stable > 0):
        return None                    # tokens left, nothing received: a transfer
    dec = decimals.get(token, 18)
    return {"side": side, "token": token, "decimals": dec, "raw": abs(delta),
            "units": abs(delta) / 10 ** dec, "native": abs(native), "stable_usd": abs(stable)}


def sell_fraction(sold_raw: int, left_raw: int) -> float:
    """Share of his position a sell took, from what he still holds after it."""
    if left_raw <= 0:
        return 1.0
    return min(1.0, sold_raw / (sold_raw + left_raw))


def position_key(chain: str, token: str) -> str:
    return f"{chain}:{token}"


# ── network ──────────────────────────────────────────────────────────────

async def rpc(chain: str, method: str, params: list):
    return await rpc_client.call_rpc(chain, method, params, timeout=12.0)


async def token_decimals(chain: str, token: str) -> int:
    key = (chain, token)
    if key not in _decimals:
        try:
            res = await rpc(chain, "eth_call", [{"to": token, "data": "0x313ce567"}, "latest"])
            _decimals[key] = int(res, 16) if res and res != "0x" else 18
        except (RuntimeError, ValueError):
            return 18
    return _decimals[key]


async def token_balance(chain: str, token: str, owner: str, block: str = "latest") -> int:
    res = await rpc(chain, "eth_call", [{"to": token, "data": "0x70a08231" + _topic(owner)[2:]}, block])
    return int(res, 16) if res and res != "0x" else 0


async def native_balance(chain: str, owner: str, block: str = "latest") -> int:
    return int(await rpc(chain, "eth_getBalance", [owner, block]), 16)


_balance_jobs: dict[str, asyncio.Task] = {}


async def _read_balances(address: str) -> dict[str, float | None]:
    async def one(chain):
        try:
            return chain, await native_balance(chain, address) / 1e18
        except (RuntimeError, ValueError):
            return chain, None
    out = dict(await asyncio.gather(*(one(c) for c in CHAINS)))
    _balance_cache[norm(address)] = (time.time(), out)
    return out


async def native_balances(address: str, wait_s: float = 2.5) -> dict[str, float | None]:
    """The EVM wallet's own coin on each network, cached 30 s. The page asks
    every 5 s: a slow node must not hold the whole copy-trading state, so the
    read runs on its own and an answer later than wait_s lands next time."""
    key = norm(address)
    hit = _balance_cache.get(key)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    job = _balance_jobs.get(key)
    if job is None or job.done():
        job = _balance_jobs[key] = asyncio.create_task(_read_balances(address))
    try:
        return await asyncio.wait_for(asyncio.shield(job), timeout=wait_s)
    except asyncio.TimeoutError:
        return hit[1] if hit else {}


async def kyber_route(chain: str, token_in: str, token_out: str, amount_in: int) -> dict:
    """{amount_out, in_usd, out_usd} from KyberSwap's aggregator; NoRoute when
    it has no path. Free, no key: x-client-id only names the caller."""
    slug = CHAINS[chain]["slug"]
    if not slug:
        raise NoRoute(f"KyberSwap does not trade on {CHAINS[chain]['label']}")
    params = {"tokenIn": token_in, "tokenOut": token_out, "amountIn": str(int(amount_in))}
    for wait in (0.6, 1.2, None):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(KYBER.format(slug=slug), params=params, headers={"x-client-id": KYBER_CLIENT})
        except httpx.HTTPError as exc:
            if wait is None:
                raise RuntimeError(f"KyberSwap unreachable ({type(exc).__name__})") from exc
            await asyncio.sleep(wait)
            continue
        if r.status_code == 429 and wait is not None:
            await asyncio.sleep(wait)
            continue
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        summary = ((body.get("data") or {}).get("routeSummary")) or {}
        if r.status_code != 200 or body.get("code") not in (0, None) or not summary.get("amountOut"):
            raise NoRoute(f"KyberSwap: {str(body.get('message') or r.status_code)[:80]}")
        return {"amount_out": int(summary["amountOut"]),
                "in_usd": float(summary.get("amountInUsd") or 0) or None,
                "out_usd": float(summary.get("amountOutUsd") or 0) or None}
    raise RuntimeError("KyberSwap busy (429)")


async def quote(chain: str, token_in: str, token_out: str, amount_in: int) -> dict:
    """Same shape on every chain: {amount_out, in_usd, out_usd}."""
    how = CHAINS[chain]["quote"]
    if how == "kyber":
        return await kyber_route(chain, token_in, token_out, amount_in)
    if how == "uniswap":
        from app.trading.onchain import quotes
        weth = CHAINS[chain]["wrapped"]
        a, b = (weth if token_in == NATIVE else token_in), (weth if token_out == NATIVE else token_out)
        found = await quotes.find_pool_and_fee(a, b)
        if not found:
            raise NoRoute("no Uniswap pool for this pair on Robinhood Chain")
        q = await quotes.uniswap_v3_quote(a, b, found[1], amount_in)
        return {"amount_out": int(q["amount_out"]), "in_usd": None, "out_usd": None}
    raise NoRoute(f"no trusted quote source on {CHAINS[chain]['label']} yet")


async def native_usd(chain: str, probe_token: str | None = None) -> float | None:
    """The chain's own coin in dollars. Arc pays gas in USDC; ETH chains share
    the server's ETH price; anything else (BNB, MON) is read off a KyberSwap
    probe of 0.1 coin into the token being traded, which carries amountInUsd."""
    if chain == "arc":
        return 1.0
    from app.trading.onchain import prices
    if CHAINS[chain]["native"] == "ETH":
        p = await prices.native_price_usd("robinhood")
        if p:
            return p
    if chain == "bsc":
        from app.trading.onchain import live_prices
        key = live_prices._key("bsc", CHAINS["bsc"]["wrapped"])
        try:
            hit = (await live_prices.prices([key])).get(f"{key[0]}:{key[1]}")
            if hit and hit.get("p"):
                return float(hit["p"])
        except Exception:  # noqa: BLE001
            pass
    if probe_token and CHAINS[chain]["quote"] == "kyber":
        try:
            r = await kyber_route(chain, NATIVE, probe_token, 10 ** 17)
            return r["in_usd"] * 10 if r["in_usd"] else None
        except RuntimeError:
            return None
    return None


# ── copying ──────────────────────────────────────────────────────────────

def watched(chain: str) -> dict[str, list[str]]:
    """EVM leader -> owners following it on this chain, mode other than off."""
    out: dict[str, list[str]] = {}
    for leader, owners in copytrade.watched("evm").items():
        for owner in owners:
            f = copytrade.account(owner)["follows"].get(leader) or {}
            if chain in (f.get("chains") or list(CHAINS)):
                out.setdefault(leader, []).append(owner)
    return out


async def _native_delta(chain: str, leader: str, block: int, tx: dict, receipt: dict) -> int:
    after = await native_balance(chain, leader, hex(block))
    before = await native_balance(chain, leader, hex(block - 1))
    delta = after - before
    if (tx.get("from") or "").lower() == leader:
        gas = int(receipt.get("gasUsed") or "0x0", 16) * int(receipt.get("effectiveGasPrice") or tx.get("gasPrice") or "0x0", 16)
        delta += gas + int(receipt.get("l1Fee") or "0x0", 16)      # Base posts an L1 data fee too
    return delta


async def handle_tx(chain: str, leader: str, tx_hash: str, block: int) -> None:
    """One transaction touching a followed wallet's tokens."""
    key = f"{chain}:{tx_hash}:{leader}"
    if key in _handled:
        return
    _handled.add(key)
    if len(_handled) > 20_000:
        _handled.clear()
        _handled.add(key)
    owners = watched(chain).get(leader, [])
    if not owners:
        return
    try:
        receipt, tx, blk = await asyncio.gather(
            rpc(chain, "eth_getTransactionReceipt", [tx_hash]),
            rpc(chain, "eth_getTransactionByHash", [tx_hash]),
            rpc(chain, "eth_getBlockByNumber", [hex(block), False]))
        if not receipt or receipt.get("status") != "0x1":
            return
        tokens = {(lg.get("address") or "").lower() for lg in receipt.get("logs") or []}
        decs = dict(zip(tokens, await asyncio.gather(*(token_decimals(chain, t) for t in tokens))))
        swap = parse_evm_swap(chain, leader, receipt.get("logs") or [],
                              await _native_delta(chain, leader, block, tx or {}, receipt), decs)
    except RuntimeError as exc:
        logger.warning("copytrade_evm: %s %s unreadable: %s", chain, tx_hash, exc)
        return
    if swap is None:
        return
    block_time = int((blk or {}).get("timestamp") or "0x0", 16) or time.time()
    age = time.time() - block_time
    price = await native_usd(chain, swap["token"])
    leader_usd = swap["native"] * price + swap["stable_usd"] if price else None
    if leader_usd is not None and leader_usd < MIN_LEADER_USD:
        return
    if swap["side"] == "sell":
        try:
            left = await token_balance(chain, swap["token"], leader, hex(block))
        except RuntimeError:
            left = 0
        swap["frac"] = sell_fraction(swap["raw"], left)
    status[chain]["last_event"] = time.time()
    for owner in owners:
        acc = copytrade.account(owner)
        f = acc["follows"].get(leader)
        if not f or f["mode"] == "off" or any(t.get("leader_sig") == tx_hash for t in acc["trades"]):
            continue
        base = {"leader": leader, "label": f.get("label", ""), "leader_sig": tx_hash, "chain": chain,
                "side": swap["side"], "mint": swap["token"],
                "leader_usd": round(leader_usd, 2) if leader_usd is not None else None,
                "latency_s": round(age, 1), "mode": f["mode"]}
        if age > copytrade.FRESH_S:
            row = {**base, "status": "skipped", "reason": f"seen {age:.0f}s late"}
        elif not copyable(chain):
            row = {**base, "status": "skipped", "reason": f"seen only: no trusted quote source on {CHAINS[chain]['label']} yet"}
        elif price is None:
            row = {**base, "status": "skipped", "reason": f"no {CHAINS[chain]['native']} price right now"}
        else:
            try:
                async with copytrade._lock(owner, position_key(chain, swap["token"])):
                    row = await (_copy_buy if swap["side"] == "buy" else _copy_sell)(owner, acc, f, swap, price, base)
            except NoRoute as exc:
                row = {**base, "status": "skipped", "reason": str(exc)[:200]}
            except Exception as exc:  # noqa: BLE001
                logger.exception("copytrade_evm: %s %s for %s failed", chain, tx_hash, owner)
                row = {**base, "status": "failed", "reason": str(exc)[:200]}
        if row:
            row["latency_s"] = round(time.time() - block_time, 1)
            copytrade._log(acc, row)
            copytrade._save()


async def _copy_buy(owner: str, acc: dict, f: dict, swap: dict, price: float, base: dict) -> dict:
    chain, token = base["chain"], swap["token"]
    pkey = position_key(chain, token)
    held = acc["positions"].get(f["address"], {}).get(pkey)
    usd, why = copytrade.size_buy(f, acc["limits"], base["leader_usd"] or 0.0, copytrade.spent_today(acc),
                                  copytrade.open_count(acc), held is not None)
    if usd is None:
        return {**base, "status": "skipped", "reason": why}
    wei = int(usd / price * 1e18)
    probe = max(wei // 100, 10 ** 12)
    q, small = await asyncio.gather(quote(chain, NATIVE, token, wei), quote(chain, NATIVE, token, probe))
    impact = copytrade.buy_impact_pct(wei, q["amount_out"], probe, small["amount_out"])
    units = q["amount_out"] / 10 ** swap["decimals"]
    if units <= 0:
        return {**base, "status": "skipped", "reason": "the quote returns nothing", "usd": round(usd, 2)}
    our_price, his_price = usd / units, (base["leader_usd"] or 0.0) / swap["units"]
    chase = (our_price / his_price - 1) * 100 if his_price else 0.0
    row = {**base, "usd": round(usd, 2), "qty": units, "price": our_price, "leader_price": his_price,
           "chase_pct": round(chase, 1), "impact_pct": round(impact, 2)}
    if chase > f["max_chase_pct"]:
        return {**row, "status": "skipped", "reason": f"price already {chase:.0f}% above his"}
    if impact > copytrade.MAX_IMPACT_PCT:
        return {**row, "status": "skipped", "reason": f"price impact {impact:.1f}%"}
    try:
        back = await quote(chain, token, NATIVE, q["amount_out"])
    except RuntimeError:
        back = None
    if not back or (1 - back["amount_out"] / wei) * 100 > copytrade.MAX_ROUNDTRIP_LOSS_PCT:
        return {**row, "status": "skipped", "reason": "no way to sell it back (possible honeypot or tax)"}
    if f["mode"] == "real":
        return {**row, "status": "skipped", "reason": "real money on EVM networks is not switched on yet"}
    row["status"] = "sim"
    pos = acc["positions"].setdefault(f["address"], {}).setdefault(
        pkey, {"mint": pkey, "token": token, "chain": chain, "decimals": swap["decimals"], "qty": 0.0,
               "cost_usd": 0.0, "opened_at": time.time(), "real": False})
    pos["qty"] += units
    pos["cost_usd"] += usd
    copytrade._add_spent(acc, usd)
    return row


async def _copy_sell(owner: str, acc: dict, f: dict, swap: dict, price: float, base: dict,
                     frac: float | None = None) -> dict | None:
    chain, token = base["chain"], swap["token"]
    pkey = position_key(chain, token)
    pos = acc["positions"].get(f["address"], {}).get(pkey)
    if pos is None:
        return None
    if f["copy"] != "both" and frac is None:
        return {**base, "status": "skipped", "reason": "exits are not copied (entry only)"}
    frac = swap.get("frac", 1.0) if frac is None else frac
    if frac >= 0.98:
        frac = 1.0
    qty = pos["qty"] * frac
    raw = int(qty * 10 ** pos["decimals"])
    if raw <= 0:
        copytrade._close(acc, f["address"], pkey)
        return {**base, "status": "skipped", "reason": "nothing left to sell"}
    q = await quote(chain, token, NATIVE, raw)
    usd = q["amount_out"] / 1e18 * price
    cost = pos["cost_usd"] * frac
    row = {**base, "usd": round(usd, 2), "qty": qty, "price": usd / qty if qty else None,
           "frac": round(frac, 3), "pnl_usd": round(usd - cost, 2), "status": "sim"}
    pos["qty"] -= qty
    pos["cost_usd"] -= cost
    if frac >= 1.0 or pos["qty"] <= 0:
        copytrade._close(acc, f["address"], pkey)
    return row


async def close_position(owner_id: str, leader: str, pkey: str) -> dict:
    """Sell a copied EVM position by hand (simulated, like every EVM copy)."""
    acc = copytrade.account(owner_id)
    pos = acc["positions"].get(leader, {}).get(pkey)
    if pos is None:
        raise ValueError("No such position.")
    chain, token = pos["chain"], pos["token"]
    price = await native_usd(chain, token)
    if not price:
        raise ValueError(f"No {CHAINS[chain]['native']} price right now, try again.")
    f = acc["follows"].get(leader) or {**copytrade.DEFAULT_FOLLOW, "address": leader, "copy": "both", "label": ""}
    base = {"leader": leader, "label": f.get("label", ""), "leader_sig": f"manual-{uuid.uuid4().hex[:16]}",
            "chain": chain, "side": "sell", "mint": token, "leader_usd": None, "latency_s": None,
            "mode": "sim", "manual": True}
    async with copytrade._lock(owner_id, pkey):
        try:
            row = await _copy_sell(owner_id, acc, f, {"token": token}, price, base, frac=1.0)
        except NoRoute as exc:
            raise ValueError(str(exc)) from exc
    row = copytrade._log(acc, row or {**base, "status": "skipped", "reason": "nothing to sell"})
    copytrade._save()
    return row


# ── watcher ──────────────────────────────────────────────────────────────

async def poll_chain(chain: str) -> None:
    """One look at the blocks since the last one, for every followed wallet."""
    leaders = sorted(watched(chain))
    st = status[chain]
    if not leaders:
        _last_block.pop(chain, None)
        st.update(state="idle", error="")
        return
    latest = int(await rpc(chain, "eth_blockNumber", []), 16)
    start = _last_block.get(chain)
    if start is None:
        start = latest - int(LOOKBACK_S / CHAINS[chain]["block_s"])
    start = max(start + 1, latest - MAX_RANGE)
    if start > latest:
        return
    padded = [_topic(a) for a in leaders]
    span = {"fromBlock": hex(start), "toBlock": hex(latest)}
    sent, received = await asyncio.gather(
        rpc(chain, "eth_getLogs", [{**span, "topics": [TRANSFER, padded]}]),
        rpc(chain, "eth_getLogs", [{**span, "topics": [TRANSFER, None, padded]}]))
    seen: dict[tuple[str, str], int] = {}
    wanted = set(leaders)
    for log in (sent or []) + (received or []):
        topics = log.get("topics") or []
        if len(topics) != 3:
            continue
        for who in (_addr(topics[1]), _addr(topics[2])):
            if who in wanted:
                seen[(who, log["transactionHash"])] = int(log["blockNumber"], 16)
    _last_block[chain] = latest
    st.update(state="watching", last_block=latest, error="", addresses=len(leaders))
    for (leader, tx_hash), block in sorted(seen.items(), key=lambda kv: kv[1]):
        asyncio.create_task(handle_tx(chain, leader, tx_hash, block))


async def _chain_loop(chain: str) -> None:
    while True:
        try:
            await poll_chain(chain)
        except Exception as exc:  # noqa: BLE001
            status[chain].update(state="error", error=str(exc)[:160])
        await asyncio.sleep(POLL_S.get(chain, DEFAULT_POLL_S))


async def loop() -> None:
    """Started by main's lifespan next to the Solana watcher."""
    await asyncio.gather(*(_chain_loop(c) for c in CHAINS))
