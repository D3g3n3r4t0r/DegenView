"""Ricerca token per ticker nel wallet on-chain: un solo risultato per
ticker, quello col contratto giusto.

Lorenzo: "voglio solo un unico risultato per ticker, quello con il
contratto corretto e verificato con liquidita' migliore, non voglio dover
scegliere altri doppioni".

Perche' non la ricerca DexScreener del resto del sito: restituisce al
massimo 30 *pool* su tutte le chain, non token. Su ticker popolari il
contratto vero resta fuori (misurato il 23/09/2026: cercando USDC o WIF
il mint vero di Solana non compariva affatto), e i primi posti per
liquidita' sono spesso copie con un pool gonfiato e zero scambi (BONK:
$50M di "liquidita'", volume 0, 2 transazioni).

Fonti, una per chain, entrambe pubbliche e senza chiave:
- Solana: ricerca token di Jupiter, che dice se il mint e' verificato;
- Robinhood Chain: ricerca pool di GeckoTerminal filtrata sulla chain;
  "verificato" = il token ha una scheda CoinGecko (coingecko_coin_id).
"""
from __future__ import annotations

import time
from collections.abc import Iterable

import httpx

JUPITER_SEARCH_URL = "https://lite-api.jup.ag/tokens/v2/search"
GECKOTERMINAL_SEARCH_URL = "https://api.geckoterminal.com/api/v2/search/pools"

MAX_RESULTS = 10
# Un token non verificato compare solo sopra questa liquidita': sotto e'
# quasi sempre una copia appena lanciata, non il token che si cercava.
MIN_UNVERIFIED_LIQUIDITY_USD = 10_000
# ...a meno che non si scambi davvero: su Robinhood Chain il BONK piu'
# scambiato ha $1k di pool e $1.8M di volume giornaliero.
MIN_UNVERIFIED_VOLUME_USD = 50_000
# Anche un verificato senza liquidita' non si puo' comprare.
MIN_LIQUIDITY_USD = 1_000
_CACHE_TTL_S = 60
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def normalize_symbol(symbol: str | None) -> str:
    """"$WIF", "wif" e "WIF" sono lo stesso ticker."""
    return (symbol or "").strip().lstrip("$").upper()


def _pool_is_live(reserve_usd: float, volume_h24: float, txns_h24: int) -> bool:
    """Un pool con milioni di riserva e nessuno scambio non e' liquidita'
    vera: e' il trucco classico delle copie per salire in cima alla ricerca."""
    return txns_h24 >= 20 or volume_h24 >= reserve_usd * 0.001


def pick_one_per_symbol(candidates: Iterable[dict], query: str) -> list[dict]:
    """Da molti candidati (anche piu' contratti con lo stesso ticker) a un
    token per ticker: prima i verificati, poi la liquidita' maggiore. I
    ticker che coincidono con la ricerca vengono prima degli altri."""
    wanted = normalize_symbol(query)
    candidates = [c for c in candidates if normalize_symbol(c["symbol"]) and c.get("address")]
    # Solo ticker che contengono la ricerca: le fonti trovano anche per
    # nome ("BonkEarn" cercando BONK) o per l'altro lato del pool (WETH).
    by_ticker = [c for c in candidates if wanted in normalize_symbol(c["symbol"])]
    best: dict[str, dict] = {}
    for c in by_ticker or candidates:
        key = normalize_symbol(c["symbol"])
        if c["liquidity_usd"] < MIN_LIQUIDITY_USD and c.get("volume_usd", 0) < MIN_UNVERIFIED_VOLUME_USD:
            continue
        if not c["verified"] and c["liquidity_usd"] < MIN_UNVERIFIED_LIQUIDITY_USD \
                and c.get("volume_usd", 0) < MIN_UNVERIFIED_VOLUME_USD:
            continue
        rank = (c["verified"], c["liquidity_usd"])
        current = best.get(key)
        if current is None or rank > (current["verified"], current["liquidity_usd"]):
            best[key] = c
    ordered = sorted(
        best.values(),
        key=lambda c: (
            normalize_symbol(c["symbol"]) != wanted,
            not normalize_symbol(c["symbol"]).startswith(wanted),
            not c["verified"],
            -c["liquidity_usd"],
        ),
    )
    return ordered[:MAX_RESULTS]


def _jupiter_candidates(payload: object) -> list[dict]:
    out = []
    for t in payload if isinstance(payload, list) else []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        out.append({
            "address": t["id"],
            "symbol": normalize_symbol(t.get("symbol")),
            "name": t.get("name") or "",
            "decimals": t.get("decimals"),
            "verified": bool(t.get("isVerified")),
            "liquidity_usd": float(t.get("liquidity") or 0),
            "volume_usd": sum(float((t.get("stats24h") or {}).get(k) or 0) for k in ("buyVolume", "sellVolume")),
        })
    return out


def _gecko_candidates(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    tokens = {
        item["id"]: item.get("attributes") or {}
        for item in payload.get("included") or []
        if isinstance(item, dict) and item.get("type") == "token" and item.get("id")
    }
    by_address: dict[str, dict] = {}
    for pool in payload.get("data") or []:
        attrs = pool.get("attributes") or {}
        reserve = float(attrs.get("reserve_in_usd") or 0)
        volume = float((attrs.get("volume_usd") or {}).get("h24") or 0)
        tx = (attrs.get("transactions") or {}).get("h24") or {}
        live_liquidity = reserve if _pool_is_live(reserve, volume, int(tx.get("buys", 0)) + int(tx.get("sells", 0))) else 0.0
        rel = pool.get("relationships") or {}
        # Entrambi i lati: cercando "USDG" il token cercato e' spesso la
        # quote di un pool, non la base.
        for side in ("base_token", "quote_token"):
            token_id = ((rel.get(side) or {}).get("data") or {}).get("id")
            token = tokens.get(token_id)
            if not token or not token.get("address"):
                continue
            entry = by_address.setdefault(token["address"].lower(), {
                "address": token["address"],
                "symbol": normalize_symbol(token.get("symbol")),
                "name": token.get("name") or "",
                "decimals": token.get("decimals"),
                "verified": bool(token.get("coingecko_coin_id")),
                "liquidity_usd": 0.0,
                "volume_usd": 0.0,
            })
            entry["liquidity_usd"] += live_liquidity
            if live_liquidity or reserve == 0:
                entry["volume_usd"] += volume
    return list(by_address.values())


async def _fetch_json(url: str, params: dict) -> object:
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url, params=params, headers={"accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


async def search(chain: str, query: str) -> list[dict]:
    """Solleva httpx.HTTPError se la fonte non risponde: chi chiama decide
    se ripiegare su un'altra ricerca."""
    query = query.strip()
    key = (chain, query.lower())
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL_S:
        return cached[1]

    if chain == "solana":
        candidates = _jupiter_candidates(await _fetch_json(JUPITER_SEARCH_URL, {"query": query}))
    elif chain == "robinhood":
        candidates = _gecko_candidates(await _fetch_json(
            GECKOTERMINAL_SEARCH_URL,
            {"query": query, "network": "robinhood", "include": "base_token,quote_token"},
        ))
    else:
        return []

    results = [
        {k: c[k] for k in ("address", "symbol", "name", "decimals", "verified", "liquidity_usd")}
        for c in pick_one_per_symbol(candidates, query)
    ]
    _cache[key] = (time.time(), results)
    return results

