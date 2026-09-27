"""What the Telegram alerts would have paid: enter when the message arrives.

Request: "il meme sniper deve avere una leaderboard anch'esso, con anche i
risultati se avessimo seguito l'alert di telegram (non le strategie),
semplicemente se fossimo entrati quando arrivava il messaggio di telegram
quanto guadagno ci sarebbe stato [...] le performance del segnale dopo
1,2,3,4,5,6,8,12,24,48h, e infine aggiornato in tempo reale, oltre a questo
anche il rendimento della miglior strategia backtestata".

Every alert sent (a meme listing, a gem entering the board) is written
down once. Its entry is the first pool price read after the message went
out, so the result is what someone tapping the notification could have
had, not the price the scanner saw before vetting. From then on the pool is
read on DexScreener: every SAMPLE_FAST_S for the first two days (the
checkpoints are the first reading past each hour mark), then every
SAMPLE_SLOW_S until KEEP_WATCHING_S, so the "now" column stays live. A pool
that disappears counts as -100%. For memes the best backtested strategy on
the same token (the listing's own backtest) sits next to it.

Plain price change, no fees: the simulated trades with costs are the Meme
Sniper's track record (meme_engine); this is the raw signal.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time

import httpx

from app.trading.onchain import storage

logger = logging.getLogger(__name__)

_STORE_FILE = storage.data_file("onchain_alert_track.json")
DEX_PAIRS = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pairs}"
CHECKPOINTS_H = (1, 2, 3, 4, 5, 6, 8, 12, 24, 48)
SAMPLE_FAST_S = 60
SAMPLE_SLOW_S = 15 * 60
FAST_FOR_S = 49 * 3600
KEEP_WATCHING_S = 14 * 86400
GONE_AFTER = 5                    # readings in a row without the pool
KEEP = 3000
KINDS = ("meme", "gem")

_alerts: dict[str, dict] = {}
_state = {"sampled_at": 0.0, "slow_at": 0.0}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _alerts.update({k: v for k, v in (raw.get("alerts") or {}).items() if isinstance(v, dict)})


def save() -> None:
    if len(_alerts) > KEEP:
        for k in sorted(_alerts, key=lambda k: _alerts[k]["at"])[:len(_alerts) - KEEP]:
            del _alerts[k]
    try:
        _STORE_FILE.write_text(json.dumps({"alerts": _alerts}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _alerts.clear()
    _state.update(sampled_at=0.0, slow_at=0.0)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def record(item: dict, kind: str, now: float | None = None) -> dict | None:
    """An alert just went out. Once per token and kind."""
    if kind not in KINDS or not item.get("chain") or not item.get("pair_address"):
        return None
    now = now or time.time()
    k = f"{kind}:{item['chain']}:{item.get('token_address') or item['pair_address']}"
    if k in _alerts:
        return None
    _alerts[k] = {
        "kind": kind, "chain": item["chain"], "symbol": item.get("symbol") or "?", "name": item.get("name") or "",
        "token_address": item.get("token_address") or "", "pair_address": item["pair_address"],
        "pair_url": item.get("pair_url") or "", "at": now, "cap0": _num(item.get("market_cap")),
        "liq0": _num(item.get("liquidity_usd")), "quoted": _num(item.get("price_usd")),
        "entry": None, "entry_at": None, "returns": {}, "last": None, "max_ret": None, "min_ret": None,
        "misses": 0, "gone": False, "closed": False, "strategy": None, "score": item.get("score"),
    }
    save()
    return _alerts[k]


def apply_price(a: dict, price, now: float) -> None:
    """One reading of the pool. None = the pool did not answer."""
    if a["closed"]:
        return
    price = _num(price)
    if price is None:
        if a["entry"] is not None:
            a["misses"] += 1
            if a["misses"] >= GONE_AFTER:
                a.update(gone=True, closed=True, last={"ret": -1.0, "at": now})
                for h in CHECKPOINTS_H:
                    a["returns"].setdefault(str(h), -1.0)
        return
    a["misses"] = 0
    if a["entry"] is None:
        a["entry"], a["entry_at"] = price, now
        return
    ret = round(price / a["entry"] - 1, 4)
    a["last"] = {"ret": ret, "at": now, "price": price}
    a["max_ret"] = ret if a["max_ret"] is None else max(a["max_ret"], ret)
    a["min_ret"] = ret if a["min_ret"] is None else min(a["min_ret"], ret)
    age = now - a["entry_at"]
    for h in CHECKPOINTS_H:
        if str(h) not in a["returns"] and age >= h * 3600:
            a["returns"][str(h)] = ret
    if age >= KEEP_WATCHING_S:
        a["closed"] = True


def set_strategy(kind: str, chain: str, token: str, backtest: dict | None) -> None:
    """The best backtested strategy on the same token (the listing's)."""
    a = _alerts.get(f"{kind}:{chain}:{token}")
    if a is None or not backtest or backtest.get("return_pct") is None:
        return
    a["strategy"] = {"label": backtest.get("label"), "name": backtest.get("strategy_name"),
                     "return_pct": backtest.get("return_pct"), "trades": backtest.get("trades"),
                     "interval": backtest.get("interval"), "at": backtest.get("at")}


def _due(now: float) -> dict[str, list[dict]]:
    slow = now - _state["slow_at"] >= SAMPLE_SLOW_S
    out: dict[str, list[dict]] = {}
    for a in _alerts.values():
        if a["closed"]:
            continue
        young = now - a["at"] < FAST_FOR_S
        if young or slow:
            out.setdefault(a["chain"], []).append(a)
    if slow:
        _state["slow_at"] = now
    return out


async def sample(client: httpx.AsyncClient, now: float | None = None) -> int:
    now = now or time.time()
    if now - _state["sampled_at"] < SAMPLE_FAST_S:
        return 0
    _state["sampled_at"] = now
    n = 0
    for chain, alerts in _due(now).items():
        for i in range(0, len(alerts), 30):
            batch = alerts[i:i + 30]
            try:
                r = await client.get(DEX_PAIRS.format(chain=chain, pairs=",".join(a["pair_address"] for a in batch)),
                                     timeout=10.0)
                pairs = (r.json() or {}).get("pairs") or [] if r.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                pairs = None
            if pairs is None:
                continue            # the API did not answer: not a vanished pool
            by = {(p.get("pairAddress") or "").lower(): p for p in pairs}
            for a in batch:
                p = by.get(a["pair_address"].lower())
                apply_price(a, p.get("priceUsd") if p else None, now)
                n += 1
            await asyncio.sleep(0.3)
    save()
    return n


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def board(kind: str, limit: int = 30, now: float | None = None) -> dict:
    """The alerts ranked by what they are worth now, with every checkpoint,
    and per checkpoint the median and the share in profit."""
    now = now or time.time()
    rows = [a for a in _alerts.values() if a["kind"] == kind and a["entry"] is not None]
    rows.sort(key=lambda a: -((a.get("last") or {}).get("ret") if a.get("last") else -9))
    items = [{"symbol": a["symbol"], "name": a["name"], "chain": a["chain"], "token_address": a["token_address"],
              "pair_url": a["pair_url"], "at": a["at"], "cap0": a["cap0"], "returns": a["returns"],
              "now": (a.get("last") or {}).get("ret"), "max": a["max_ret"], "gone": a["gone"],
              "age_h": round((now - a["at"]) / 3600, 1), "strategy": a.get("strategy")} for a in rows[:limit]]
    summary = []
    for h in CHECKPOINTS_H:
        vals = [a["returns"][str(h)] for a in rows if str(h) in a["returns"]]
        summary.append({"h": h, "n": len(vals), "median": round(_median(vals), 4) if vals else None,
                        "positive": round(sum(v > 0 for v in vals) / len(vals), 3) if vals else None,
                        "mean": round(sum(vals) / len(vals), 4) if vals else None})
    live = [a["last"]["ret"] for a in rows if a.get("last")]
    strat = [a["strategy"]["return_pct"] for a in rows if a.get("strategy")]
    return {"items": items, "total": len(rows), "checkpoints": list(CHECKPOINTS_H), "summary": summary,
            "now": {"n": len(live), "median": round(_median(live), 4) if live else None,
                    "positive": round(sum(v > 0 for v in live) / len(live), 3) if live else None},
            "strategy": {"n": len(strat), "median_pct": round(_median(strat), 2) if strat else None}}


def recent(kind: str, since_s: float, now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [a for a in _alerts.values() if a["kind"] == kind and now - a["at"] <= since_s]


_load()
