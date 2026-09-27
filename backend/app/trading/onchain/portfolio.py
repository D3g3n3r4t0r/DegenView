"""Everything a wallet holds, on every chain, priced.

Lorenzo: "il wallet deve essere multi-chain e devo visualizzare il saldo a
prescindere da quale token e in quale chain ho".

One reader per chain, each reporting every token it can see, then one
pricing pass on DexScreener (30 tokens a call):

- Solana: SOL plus every SPL and Token-2022 account (pump.fun tokens are
  Token-2022: the old reader missed them);
- Base, Ethereum: Blockscout's public API lists every ERC-20 an address
  holds, with the native balance;
- Robinhood Chain: its Blockscout sits behind a bot challenge, so ETH plus
  balanceOf, in JSON-RPC batches, on every token this site has ever
  touched there (alerts, the system's trades, orders, quote tokens);
- BSC: BNB (no free token indexer to lean on).

An EVM address is the same on every EVM chain, so one EVM wallet is read on
all four. Tokens with no price, or worth less than a cent, are kept but
marked hidden: airdropped spam should not inflate the total, nor vanish.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

EVM_CHAINS = ("robinhood", "base", "ethereum", "bsc")
CHAIN_OF_KIND = {"evm": EVM_CHAINS, "solana": ("solana",)}
NATIVE = {"solana": "SOL", "robinhood": "ETH", "base": "ETH", "ethereum": "ETH", "bsc": "BNB"}
# The wrapped native per chain, priced on GeckoTerminal like prices.py does.
WRAPPED = {
    "solana": ("solana", "So11111111111111111111111111111111111111112"),
    "robinhood": ("robinhood", "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"),
    "base": ("base", "0x4200000000000000000000000000000000000006"),
    "ethereum": ("eth", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    "bsc": ("bsc", "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
}
# The native coins' own logos: DexScreener's picture of the wrapped token
# (ETH for every ETH chain). Without it SOL/ETH/BNB got a generated emblem,
# which reads as the wrong icon (Lorenzo: "le icone non corrispondono a
# quelle corrette del token").
NATIVE_IMAGE = {
    "solana": "https://dd.dexscreener.com/ds-data/tokens/solana/So11111111111111111111111111111111111111112.png",
    "robinhood": "https://dd.dexscreener.com/ds-data/tokens/ethereum/0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2.png",
    "base": "https://dd.dexscreener.com/ds-data/tokens/ethereum/0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2.png",
    "ethereum": "https://dd.dexscreener.com/ds-data/tokens/ethereum/0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2.png",
    "bsc": "https://dd.dexscreener.com/ds-data/tokens/bsc/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c.png",
}
BLOCKSCOUT = {"base": "https://base.blockscout.com", "ethereum": "https://eth.blockscout.com"}
RPC = {"robinhood": "https://rpc.mainnet.chain.robinhood.com", "bsc": "https://bsc-dataseed.binance.org"}
SOL_RPC = "https://api.mainnet-beta.solana.com"
TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
STABLES = {"USDG", "USDC", "USDT", "PYUSD", "USD1", "DAI", "USDS", "USDE", "FDUSD"}
DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/{chain}/{addrs}"
DUST_USD = 0.01
TTL_S = 60
MAX_RH_CANDIDATES = 200

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_native_px: dict[str, tuple[float, float]] = {}


def reset_for_tests() -> None:
    _cache.clear()
    _native_px.clear()


# ------------------------------------------------------------------ prices

async def native_price(chain: str, client: httpx.AsyncClient) -> float | None:
    hit = _native_px.get(chain)
    if hit and time.time() - hit[1] < 60:
        return hit[0]
    net, addr = WRAPPED[chain]
    try:
        r = await client.get(f"https://api.geckoterminal.com/api/v2/simple/networks/{net}/token_price/{addr}")
        price = float(next(iter(r.json()["data"]["attributes"]["token_prices"].values())))
    except Exception:
        return hit[0] if hit else None
    _native_px[chain] = (price, time.time())
    return price


async def dex_prices(chain: str, tokens: list[str], client: httpx.AsyncClient) -> dict[str, dict]:
    """{token (lowercased for EVM): {price, symbol, name, image}} from each
    token's most liquid pair on DexScreener."""
    out: dict[str, dict] = {}
    norm = (lambda a: a.lower()) if chain != "solana" else (lambda a: a)
    for i in range(0, len(tokens), 30):
        batch = tokens[i:i + 30]
        try:
            r = await client.get(DEX_TOKENS.format(chain=chain, addrs=",".join(batch)))
            pairs = r.json() if r.status_code == 200 else []
        except Exception:
            continue
        best: dict[str, tuple[float, dict]] = {}
        for p in pairs if isinstance(pairs, list) else []:
            base = p.get("baseToken") or {}
            k = norm(base.get("address") or "")
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            if k and (k not in best or liq > best[k][0]):
                best[k] = (liq, p)
        for k, (_liq, p) in best.items():
            base = p.get("baseToken") or {}
            try:
                price = float(p.get("priceUsd"))
            except (TypeError, ValueError):
                price = None
            out[k] = {"price": price, "symbol": base.get("symbol"), "name": base.get("name"),
                      "image": (p.get("info") or {}).get("imageUrl")}
    return out


# ----------------------------------------------------------------- readers

async def _solana(address: str, client: httpx.AsyncClient) -> tuple[float, list[dict]]:
    async def rpc(method, params):
        r = await client.post(SOL_RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"])
        return body["result"]
    lamports = (await rpc("getBalance", [address]))["value"]
    rows = []
    for program in TOKEN_PROGRAMS:
        res = await rpc("getTokenAccountsByOwner", [address, {"programId": program}, {"encoding": "jsonParsed"}])
        for item in res.get("value", []):
            info = item["account"]["data"]["parsed"]["info"]
            amt = info["tokenAmount"]
            ui = float(amt.get("uiAmountString") or 0)
            if ui > 0:
                rows.append({"token": info["mint"], "amount": ui, "decimals": amt["decimals"]})
    return lamports / 1e9, rows


async def _blockscout(chain: str, address: str, client: httpx.AsyncClient) -> tuple[float, list[dict]]:
    base = BLOCKSCOUT[chain]
    r = await client.get(f"{base}/api/v2/addresses/{address}")
    native = int((r.json() or {}).get("coin_balance") or 0) / 1e18 if r.status_code == 200 else 0.0
    r = await client.get(f"{base}/api/v2/addresses/{address}/token-balances")
    rows = []
    for item in r.json() if r.status_code == 200 and isinstance(r.json(), list) else []:
        t = item.get("token") or {}
        if (t.get("type") or "ERC-20") != "ERC-20":
            continue
        try:
            dec = int(t.get("decimals") or 0)
            amount = int(item.get("value") or 0) / 10 ** dec
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        rate = t.get("exchange_rate")
        rows.append({"token": t.get("address_hash") or t.get("address") or "", "amount": amount, "decimals": dec,
                     "symbol": t.get("symbol"), "name": t.get("name"), "image": t.get("icon_url"),
                     "price": float(rate) if rate not in (None, "") else None})
    return native, rows


async def _evm_rpc_batch(url: str, calls: list[tuple[str, list]], client: httpx.AsyncClient) -> list:
    out = []
    for i in range(0, len(calls), 50):
        chunk = calls[i:i + 50]
        body = [{"jsonrpc": "2.0", "id": j, "method": m, "params": p} for j, (m, p) in enumerate(chunk)]
        r = await client.post(url, json=body)
        res = r.json()
        by_id = {x.get("id"): x.get("result") for x in res} if isinstance(res, list) else {}
        out += [by_id.get(j) for j in range(len(chunk))]
    return out


def robinhood_candidates() -> list[str]:
    """Every Robinhood token this site has touched."""
    from app.trading.onchain import alert_track, autotrader
    seen = {autotrader.USDG.lower(): autotrader.USDG, WRAPPED["robinhood"][1].lower(): WRAPPED["robinhood"][1]}
    if autotrader._meta.get("usdc"):
        seen[autotrader._meta["usdc"].lower()] = autotrader._meta["usdc"]
    for a in sorted(alert_track._alerts.values(), key=lambda x: -x.get("at", 0)):
        if a.get("chain") == "robinhood" and a.get("token_address", "").startswith("0x"):
            seen.setdefault(a["token_address"].lower(), a["token_address"])
    for u in autotrader._state.values():
        for t in u.get("trades") or []:
            if (t.get("token") or "").startswith("0x"):
                seen.setdefault(t["token"].lower(), t["token"])
    return list(seen.values())[:MAX_RH_CANDIDATES]


async def _robinhood(address: str, client: httpx.AsyncClient) -> tuple[float, list[dict]]:
    from app.trading.onchain import token_metadata
    url = RPC["robinhood"]
    owner = address[2:].lower().zfill(64)
    tokens = robinhood_candidates()
    calls = [("eth_getBalance", [address, "latest"])] + [
        ("eth_call", [{"to": t, "data": "0x70a08231" + owner}, "latest"]) for t in tokens]
    res = await _evm_rpc_batch(url, calls, client)
    native = int(res[0] or "0x0", 16) / 1e18
    rows = []
    for t, raw in zip(tokens, res[1:]):
        try:
            v = int(raw or "0x0", 16)
        except ValueError:
            continue
        if v <= 0:
            continue
        dec = await token_metadata.get_token_decimals("robinhood", t)
        if dec is None:
            continue
        rows.append({"token": t, "amount": v / 10 ** dec, "decimals": dec})
    return native, rows


async def _bsc(address: str, client: httpx.AsyncClient) -> tuple[float, list[dict]]:
    r = await client.post(RPC["bsc"], json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]})
    return int(r.json().get("result") or "0x0", 16) / 1e18, []


READERS = {"solana": _solana, "base": lambda a, c: _blockscout("base", a, c),
           "ethereum": lambda a, c: _blockscout("ethereum", a, c), "robinhood": _robinhood, "bsc": _bsc}


# ------------------------------------------------------------------- wallet

async def wallet(chain: str, address: str, client: httpx.AsyncClient | None = None, *, fresh: bool = False) -> list[dict]:
    """Every holding of one address on one chain, priced. Raises if the
    chain's source does not answer: a wallet we could not read is not empty."""
    key = (chain, address.lower() if chain != "solana" else address)
    hit = _cache.get(key)
    if hit and not fresh and time.time() - hit[0] < TTL_S:
        return hit[1]
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, headers={"accept": "application/json"})
    try:
        native, rows = await READERS[chain](address, client)
        need = [r["token"] for r in rows if r.get("price") is None or not r.get("symbol")]
        info = await dex_prices(chain, need, client) if need else {}
        px = await native_price(chain, client) if native > 0 else None
    finally:
        if own:
            await client.aclose()
    norm = (lambda a: a.lower()) if chain != "solana" else (lambda a: a)
    out = []
    if native > 0:
        out.append({"chain": chain, "token": None, "symbol": NATIVE[chain], "name": NATIVE[chain], "amount": native,
                    "price_usd": px, "value_usd": native * px if px is not None else None, "image": NATIVE_IMAGE.get(chain),
                    "native": True, "hidden": False})
    for r in rows:
        meta = info.get(norm(r["token"]), {})
        symbol = r.get("symbol") or meta.get("symbol") or r["token"][:6]
        price = r.get("price") if r.get("price") is not None else meta.get("price")
        if price is None and (symbol or "").upper() in STABLES:
            price = 1.0
        value = r["amount"] * price if price is not None else None
        out.append({"chain": chain, "token": r["token"], "symbol": symbol, "name": r.get("name") or meta.get("name") or symbol,
                    "amount": r["amount"], "price_usd": price, "value_usd": value,
                    "image": r.get("image") or meta.get("image"), "native": False,
                    "hidden": value is None or value < DUST_USD})
    out.sort(key=lambda h: -(h["value_usd"] or 0))
    _cache[key] = (time.time(), out)
    return out


async def everything(addresses: list[tuple[str, str, str]]) -> dict:
    """addresses: (kind "evm"|"solana", address, source). Every chain of
    each, in parallel. Returns holdings, totals by chain, and what could
    not be read."""
    jobs = [(chain, addr, source) for kind, addr, source in addresses for chain in CHAIN_OF_KIND[kind]]
    async with httpx.AsyncClient(timeout=15.0, headers={"accept": "application/json"}) as client:
        results = await asyncio.gather(*(wallet(c, a, client) for c, a, _s in jobs), return_exceptions=True)
    holdings, missing, by_chain, read = [], [], {}, set()
    for (chain, addr, source), res in zip(jobs, results):
        if not isinstance(res, Exception):
            read.add(chain)
        if isinstance(res, Exception):
            logger.info("portfolio: %s %s unreadable: %s", chain, addr[:8], res)
            missing.append({"chain": chain, "address": addr})
            continue
        for h in res:
            holdings.append({**h, "wallet": addr, "source": source})
            if not h["hidden"] and h["value_usd"]:
                by_chain[chain] = by_chain.get(chain, 0.0) + h["value_usd"]
    holdings.sort(key=lambda h: -(h["value_usd"] or 0))
    cash = sum(h["value_usd"] or 0 for h in holdings if not h["hidden"] and (h["symbol"] or "").upper() in STABLES)
    total = sum(by_chain.values())
    return {"total": round(total, 4), "cash": round(cash, 4), "by_chain": {k: round(v, 4) for k, v in by_chain.items()},
            "holdings": holdings, "missing": missing,
            "read": {c: round(by_chain.get(c, 0.0), 4) for c in read},
            "missing_chains": sorted({m["chain"] for m in missing} - read)}
