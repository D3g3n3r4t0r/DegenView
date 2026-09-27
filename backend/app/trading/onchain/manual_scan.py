"""Scan one token on request, through everything the system does.

Lorenzo, 27/09: "aggiungiamo anche l'opzione di aggiungere un indirizzo di
un token o il suo ticker che poi va a cercare nel database di DexScreener
con le logiche che abbiamo adesso, cosi' da avere un riepilogo [...]
compresa anche la scansione di DeepSeek e tutto il processo fatto
manualmente su un ticker a scelta".

resolve() finds the most liquid pair on a chain we cover; scan() runs the
listing checks (legit.assess, plus the security check even when the
pipeline would stop earlier on a meme name), the rug memory (similar past
cases, this token's own history) and DeepSeek's judgement, and returns
one summary. Nothing is recorded as an alert.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from app.notify import deepseek_desk
from app.trading.onchain import ai_scan, alert_track, legit, outcomes, rug_memory

SEARCH = "https://api.dexscreener.com/latest/dex/search?q={q}"


def looks_like_address(q: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,48}", q))


def pick(pairs: list[dict], query: str) -> dict | None:
    q = query.strip().lstrip("$")
    ok = [p for p in pairs if p.get("chainId") in legit.CHAIN_LABEL]
    if looks_like_address(q):
        ok = [p for p in ok if (p.get("baseToken") or {}).get("address", "").lower() == q.lower()] or ok
    else:
        ok = [p for p in ok if (p.get("baseToken") or {}).get("symbol", "").upper() == q.upper()] or ok
    return max(ok, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), default=None)


def item_of(pair: dict) -> dict:
    base = pair.get("baseToken") or {}
    cap = pair.get("marketCap") or pair.get("fdv")
    return {"chain": pair.get("chainId"), "symbol": base.get("symbol") or "?", "name": base.get("name") or "",
            "token_address": base.get("address") or "", "pair_address": pair.get("pairAddress") or "",
            "pair_url": pair.get("url") or "", "dex": pair.get("dexId") or "",
            "liquidity_usd": float((pair.get("liquidity") or {}).get("usd") or 0),
            "market_cap": float(cap) if cap else None, "price_usd": pair.get("priceUsd"),
            "image": (pair.get("info") or {}).get("imageUrl"),
            "created_at": (pair.get("pairCreatedAt") or 0) / 1000 or None,
            "change_24h": (pair.get("priceChange") or {}).get("h24"),
            "volume_24h": (pair.get("volume") or {}).get("h24")}


async def _security(item: dict, client: httpx.AsyncClient) -> dict:
    addr = item.get("token_address") or ""
    if item["chain"] == "solana":
        return legit.judge_rugcheck(await legit.rugcheck(addr, client))
    if item["chain"] in legit.GOPLUS_CHAIN:
        return legit.judge_goplus(await legit.goplus(item["chain"], addr, client))
    return legit._check("security", "Security", None, "chain not covered")


async def scan(query: str) -> dict:
    query = (query or "").strip()
    if not query:
        return {"error": "Write a ticker or an address."}
    deepseek_desk.note("manual", f"Manual scan requested: {query[:40]}")
    async with httpx.AsyncClient(timeout=15.0, headers={"accept": "application/json"}) as client:
        try:
            r = await client.get(SEARCH.format(q=quote(query)))
            pairs = (r.json() or {}).get("pairs") or [] if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return {"error": "DexScreener is not answering, try again."}
        pair = pick(pairs, query)
        if not pair:
            return {"error": f"No pool for \"{query}\" on Solana, Robinhood, BSC, Base or Ethereum."}
        item = item_of(pair)
        verdict = await legit.assess(item, legit.links_from_dexscreener(pair), client)
        checks = list(verdict.get("checks") or [])
        if not any(c.get("key") == "security" for c in checks):
            checks.append(await _security(item, client))
    item.update(checks=checks, socials=verdict.get("socials"), website=verdict.get("website"),
                report=verdict.get("report"))
    feats = outcomes.features(item)
    pool = rug_memory.cases()
    ai = await ai_scan.judge_one(item, feats, pool)
    deepseek_desk.note("manual", f"Scanned {item['symbol']}: pipeline {verdict['status']}"
                       + (f", rug risk {ai['risk']}" if ai else ""), symbol=item["symbol"], chain=item["chain"])
    tracked = alert_track._alerts.get(f"meme:{item['chain']}:{item['token_address']}")
    return {"token": {k: item.get(k) for k in ("chain", "symbol", "name", "token_address", "pair_address", "pair_url",
                                               "dex", "liquidity_usd", "market_cap", "price_usd", "image",
                                               "created_at", "change_24h", "volume_24h", "website")},
            "pipeline": {"status": verdict["status"], "reason": verdict.get("reason") or ""},
            "checks": [{k: c.get(k) for k in ("key", "label", "ok", "detail")} for c in checks],
            "report": verdict.get("report"),
            "memory": {"summary": rug_memory.summary(feats, item["chain"], pool=pool),
                       "similar": rug_memory.similar(feats, item["chain"], k=5, pool=pool),
                       "history": rug_memory.lookup(item["token_address"])},
            "ai": ai,
            "alert": {"at": tracked["at"], "now": (tracked.get("last") or {}).get("ret")} if tracked else None}
