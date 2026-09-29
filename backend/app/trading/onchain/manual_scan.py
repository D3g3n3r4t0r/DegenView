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

Lorenzo, 29/09: "lo scanner manuale e' insufficiente e non si e' evoluto
seguendo tutti gli aggiornamenti". A project (not a meme name) is judged by
the Gem Finder, not by the meme listing filter: its board entry or database
row (score, pillars, DeepSeek's verdict and code reading), or a place in the
study queue when it was never met, if the user adds it (`add`). The trend follower's backtest comes from
the strategy lab, or is run now and kept there.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import quote

import httpx

from app.notify import deepseek_desk
from app.trading.onchain import (ai_scan, alert_track, code_review, judge, leaderboard, legit, outcomes,
                                 projects_db, research, rug_memory, strategy_lab)

logger = logging.getLogger(__name__)

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


# outcomes.py labels its verdicts in Italian; the site is in English.
OUTCOME_EN = {"buono": "fine", "crollo": "crashed", "piatto": "flat", "finto": "fake volume"}
BACKTEST_TIMEOUT_S = 25
RECENT_KEEP = 200
# What each scan found, so "add" enters what the server read, never what a client sends.
_recent: dict[str, dict] = {}


def english(text: str) -> str:
    return re.sub(r"\b(" + "|".join(OUTCOME_EN) + r")\b", lambda m: OUTCOME_EN[m.group(1)], text or "")


def clean_flags(ai: dict | None) -> dict | None:
    """DeepSeek sometimes restates the rug memory with its own numbers
    (HYDX: "4/5 similar rugged" next to a memory of 1 rug in 5). The memory
    is shown with the real counts, so its flags about it are dropped."""
    if not ai:
        return ai
    return {**ai, "flags": [f for f in ai.get("flags") or [] if "similar" not in str(f).lower()]}


def about(info: dict | None, socials: list[dict] | None) -> dict:
    """What the project says it is, and who holds it (GeckoTerminal)."""
    info = info or {}
    split = info.get("holders_split") or {}
    try:
        top10 = float(split.get("top_10")) if split.get("top_10") is not None else None
    except (TypeError, ValueError):
        top10 = None
    return {"summary": research.summary_line(info.get("description") or "") or None,
            "holders": info.get("holders"), "top10_pct": top10,
            "socials": [{"type": x.get("type"), "url": x.get("url")} for x in (socials or [])
                        if str(x.get("url") or "").startswith("https://")][:4]}


def _pillars(raw: dict | None) -> dict:
    return {k: (v or {}).get("score") for k, v in (raw or {}).items() if isinstance(v, dict)}


def _judge_view(j: dict | None) -> dict | None:
    if not j or j.get("verdict") is None:
        return None
    return {"verdict": j.get("verdict"), "score": j.get("score"),
            "problems": (j.get("problems") or [])[:2], "strengths": (j.get("strengths") or [])[:2]}


def _code_view(c: dict | None) -> dict | None:
    if not c or c.get("complexity") is None:
        return None
    return {"complexity": c.get("complexity"), "innovation": c.get("innovation"), "summary": c.get("summary")}


def gem_view(item: dict, now: float | None = None) -> dict:
    """What the Gem Finder knows about this project: on the board, in the
    database, or queued now for its first study."""
    chain, token = item["chain"], item["token_address"]
    e = leaderboard._entries.get(projects_db.key(chain, token))
    if e is not None:
        why = leaderboard.qualifies(e, now)
        return {"status": "ranked" if e.get("rank") else "studied", "rank": e.get("rank"),
                "score": round(leaderboard.final_score(e)), "why": why, "pillars": _pillars(e.get("pillars")),
                "judge": _judge_view(e.get("judge")), "code": _code_view(e.get("code"))}
    p = projects_db.get(chain, token)
    if p is not None:
        return {"status": p.get("status") or "new", "rank": p.get("rank"),
                "score": round(p["score"]) if p.get("score") is not None else None, "why": p.get("why") or "",
                "pillars": _pillars(p.get("pillars")), "judge": _judge_view(judge.get(chain, token)),
                "code": _code_view(code_review.get(code_review.repo_of({"pillars": p.get("pillars")})))}
    return {"status": "unknown", "rank": None, "score": None, "why": "", "pillars": {}, "judge": None, "code": None}


def add(chain: str, token: str, now: float | None = None) -> dict:
    """Lorenzo, 29/09: "voglio poter aggiungere manualmente un progetto che
    poi entra eventualmente nel circolo di tutte le nostre logiche". The
    scanned project joins the Gem Finder's working set: pillars, research,
    DeepSeek's judge and code reading, then the board and the strategy lab
    if it earns it. A manual add also lifts an earlier rejection: it gets a
    fresh look, and the same rules decide."""
    item = _recent.get(projects_db.key(chain, token))
    if item is None:
        return {"error": "Scan the token first."}
    if legit._looks_like_meme(item.get("symbol") or "", item.get("name") or ""):
        return {"error": "Meme names are followed by the Meme Sniper, not the Gem Finder."}
    k = projects_db.key(chain, token)
    leaderboard._gone.pop(k, None)
    fresh = leaderboard.add(dict(item), "manual", now)
    projects_db.recheck(chain, token)
    deepseek_desk.note("manual", f"Added {item.get('symbol')} to the Gem Finder by hand",
                       symbol=item.get("symbol"), chain=chain)
    return {"added": True, "new": fresh, "gem": gem_view(item, now)}


def backtest_view(r: dict | None) -> dict | None:
    """The strategy lab's result in two lines: the best 5-minute strategy
    and the trend follower on the daily chart, each against holding."""
    if not r:
        return None
    bt = r.get("backtests") or {}
    rows = [x for x in bt.get("rows") or [] if x.get("trades") and x.get("return_pct") is not None]
    best = max(rows, key=lambda x: x["return_pct"]) if rows else None
    daily = r.get("daily") or {}
    drow = (daily.get("rows") or [None])[0]
    out = {"at": r.get("at"), "error": r.get("error"),
           "fast": {**{k: best.get(k) for k in ("label", "return_pct", "trades", "win_rate", "max_dd")},
                    "hold_pct": bt.get("hold_pct")} if best else None,
           "daily": {**{k: drow.get(k) for k in ("label", "return_pct", "trades", "win_rate", "max_dd")},
                     "interval": daily.get("interval"), "hold_pct": daily.get("hold_pct")}
           if drow and drow.get("trades") else None}
    return out if out["fast"] or out["daily"] or out["error"] else None


async def backtest(item: dict, now: float | None = None) -> dict | None:
    """The lab's backtest of this token, run now when it has none."""
    k = strategy_lab.key_of(item["chain"], item["token_address"])
    r = strategy_lab._results.get(k)
    if r is None and strategy_lab.GECKO_NETWORKS.get(item["chain"]):
        e = {k2: item.get(k2) for k2 in ("chain", "token_address", "symbol", "pair_address")}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await asyncio.wait_for(strategy_lab.run_one(client, e, now or time.time()), BACKTEST_TIMEOUT_S)
            if r is not None:
                strategy_lab._save()
        except Exception as exc:
            logger.info("manual scan: backtest of %s failed: %s", item.get("symbol"), exc)
            r = None
    return backtest_view(r)


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
        links = legit.links_from_dexscreener(pair)
        verdict, info = await asyncio.gather(legit.assess(item, links, client),
                                             research.gecko_info(item["chain"], item["token_address"], client))
        checks = list(verdict.get("checks") or [])
        if not any(c.get("key") == "security" for c in checks):
            checks.append(await _security(item, client))
    item.update(checks=checks, socials=verdict.get("socials"), website=verdict.get("website"),
                report=verdict.get("report"))
    socials = verdict.get("socials") or links["socials"]
    _recent[projects_db.key(item["chain"], item["token_address"])] = {
        **item, "websites": links["websites"], "socials": socials,
        "website": verdict.get("website") or (links["websites"] or [None])[0],
        "description": (info or {}).get("description") or ""}
    while len(_recent) > RECENT_KEEP:
        _recent.pop(next(iter(_recent)))
    meme = legit._looks_like_meme(item.get("symbol") or "", item.get("name") or "")
    gem = None if meme else gem_view(item)
    feats = outcomes.features(item)
    pool = rug_memory.cases()
    ai, bt = await asyncio.gather(ai_scan.judge_one(item, feats, pool, project=not meme), backtest(item))
    ai = clean_flags(ai)
    deepseek_desk.note("manual", f"Scanned {item['symbol']}: pipeline {verdict['status']}"
                       + (f", rug risk {ai['risk']}" if ai else ""), symbol=item["symbol"], chain=item["chain"])
    tracked = alert_track._alerts.get(f"meme:{item['chain']}:{item['token_address']}")
    return {"token": {k: item.get(k) for k in ("chain", "symbol", "name", "token_address", "pair_address", "pair_url",
                                               "dex", "liquidity_usd", "market_cap", "price_usd", "image",
                                               "created_at", "change_24h", "volume_24h", "website")},
            "pipeline": {"status": verdict["status"], "reason": verdict.get("reason") or ""},
            "checks": [{k: c.get(k) for k in ("key", "label", "ok", "detail")} for c in checks],
            "report": verdict.get("report"),
            "about": about(info, socials),
            "kind": "meme" if meme else "project", "gem": gem, "backtest": bt,
            "memory": {"summary": english(rug_memory.summary(feats, item["chain"], pool=pool)),
                       "similar": rug_memory.similar(feats, item["chain"], k=5, pool=pool),
                       "history": rug_memory.lookup(item["token_address"])},
            "ai": ai,
            "alert": {"at": tracked["at"], "now": (tracked.get("last") or {}).get("ret")} if tracked else None}
