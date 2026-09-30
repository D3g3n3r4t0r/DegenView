"""Linked wallets checked on-chain, for the Top 50 only.

RugCheck's insider graph links wallets by transfers and its `currentHolding`
lags. On DREGG (30/09) it said "807 wallets linked, 39% of supply": 761 of
them were only receivers of one 744-token airdrop (among them 7 top holders
with their own bags), and the two small groups held 0 on-chain, one having
moved its 3% into Streamflow locks. Lorenzo: "fai che questa analisi venga
fatta su tutte le cripto [...] della classifica [...] soltanto se vanno in
top 50".

So: drop the links of an airdrop (one sender, many receivers, most of them
with the same amount), drop pools and lockers, rebuild the groups from what
is left, and read each wallet's balance now over RPC. A read that fails too
often returns None: the unverified RugCheck figure stays.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter

import httpx

from app.trading.onchain import rpc_client

logger = logging.getLogger(__name__)

GRAPH_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/insiders/graph"
AIRDROP_MIN_TARGETS = 20     # a sender with fewer receivers is a group, not a drop
AIRDROP_SAME_SHARE = 0.5     # share of receivers holding the very same amount
MAX_WALLETS = 80             # RPC reads per token, biggest graph holdings first
MAX_FAILED_SHARE = 0.2
CACHE_S = 6 * 3600           # tokenomics refreshes every 20 minutes
RPC_CONCURRENCY = 4

_cache: dict[str, tuple[float, dict | None]] = {}


def airdrop_senders(links: list[dict], holdings: dict[str, float]) -> set[str]:
    out: dict[str, list[str]] = {}
    for link in links:
        out.setdefault(link.get("source"), []).append(link.get("target"))
    senders = set()
    for src, targets in out.items():
        if src is None or len(targets) < AIRDROP_MIN_TARGETS:
            continue
        same = Counter(holdings.get(t) for t in targets).most_common(1)[0][1]
        if same >= AIRDROP_SAME_SHARE * len(targets):
            senders.add(src)
    return senders


def groups(graph: list[dict], skip: set[str]) -> tuple[list[set[str]], int, dict[str, float]]:
    """(linked groups of 2+ wallets without airdrop links, airdrop receivers
    left out, graph holdings by wallet)."""
    holdings = {n["id"]: float(n.get("holdings") or 0) for net in graph for n in net.get("nodes") or []}
    links = [lk for net in graph for lk in net.get("links") or []]
    drops = airdrop_senders(links, holdings)
    dropped = {lk.get("target") for lk in links if lk.get("source") in drops}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for lk in links:
        a, b = lk.get("source"), lk.get("target")
        if not a or not b or a in drops or a in skip or b in skip:
            continue
        parent[find(a)] = find(b)
    comps: dict[str, set[str]] = {}
    for x in parent:
        comps.setdefault(find(x), set()).add(x)
    kept = [c for c in comps.values() if len(c) >= 2]
    linked = set().union(*kept) if kept else set()
    return kept, len(dropped - linked), holdings


async def _balance(owner: str, mint: str, sem: asyncio.Semaphore) -> float | None:
    async with sem:
        try:
            r = await rpc_client.call_rpc("solana", "getTokenAccountsByOwner",
                                          [owner, {"mint": mint}, {"encoding": "jsonParsed"}], timeout=10.0)
        except Exception:
            return None
    return sum(float(a["account"]["data"]["parsed"]["info"]["tokenAmount"].get("uiAmount") or 0)
               for a in (r or {}).get("value") or [])


async def verify(mint: str, report: dict, client: httpx.AsyncClient, now: float | None = None) -> dict | None:
    """{"pct", "wallets", "groups", "airdrop_wallets", "at"} from balances
    read now, or None when the graph or too many balances can't be read."""
    now = now or time.time()
    hit = _cache.get(mint)
    if hit and now - hit[0] < CACHE_S:
        return hit[1]
    out = await _verify(mint, report, client, now)
    _cache[mint] = (now, out)
    return out


async def _verify(mint: str, report: dict, client: httpx.AsyncClient, now: float) -> dict | None:
    tok = report.get("token") or {}
    supply = float(tok.get("supply") or 0) / 10 ** int(tok.get("decimals") or 0)
    if supply <= 0:
        return None
    try:
        r = await client.get(GRAPH_URL.format(mint=mint), timeout=15.0)
        graph = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        graph = None
    if not isinstance(graph, list):
        return None
    skip = set((report.get("knownAccounts") or {}).keys())
    for m in report.get("markets") or []:
        skip |= {v for v in (m.get("pubkey"), m.get("liquidityA"), m.get("liquidityB")) if isinstance(v, str)}
    kept, airdrop, holdings = groups(graph, skip)
    wallets = sorted(set().union(*kept) if kept else set(), key=lambda w: -holdings.get(w, 0))[:MAX_WALLETS]
    sem = asyncio.Semaphore(RPC_CONCURRENCY)
    got = await asyncio.gather(*(_balance(w, mint, sem) for w in wallets))
    failed = sum(1 for b in got if b is None)
    if wallets and failed > MAX_FAILED_SHARE * len(wallets):
        logger.info("linked wallets of %s not verified: %d/%d balance reads failed", mint, failed, len(wallets))
        return None
    held = sum(b for b in got if b)
    return {"pct": held / supply * 100, "wallets": len(wallets), "groups": len(kept),
            "airdrop_wallets": airdrop, "at": now}
