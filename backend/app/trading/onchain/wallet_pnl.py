"""How profitable a Solana wallet's trades were: last 24 hours, 7 and 30 days.

Asked on 23/10, for the copy trading section: "un tool che permetta di
controllare la profittabilita' dei trade fatti dal wallet che noi prendiamo
in considerazione [...] ultime 24 ore, ultimi 7 giorni, ultimi 30 giorni".

- history: the wallet's signatures back to 30 days (at most MAX_SIGS), every
  transaction read and passed through copytrade.parse_swap, so the analysis
  sees exactly the trades the copier would have seen;
- dollars at the time: SOL legs priced with the SOLUSDT hourly close of the
  trade's hour (MEXC), not today's price;
- closed trades only (asked on 23/10: "soltanto i trade aperti e chiusi
  [...] non prendere in considerazione le transazioni ancora in corso"): a
  trade starts with a buy on an empty position and ends when the wallet has
  sold it all (a dust rest under DUST_SHARE of the most it held counts as
  sold). Its result is everything it got back minus everything it put in.
  A period counts the trades opened and closed inside it; positions still
  open, and trades opened before the period, are only shown as excluded;
- tokens sold without a known buy (bought before the history, or received
  by transfer) are counted apart, never given a made-up cost.
"""
from __future__ import annotations

import asyncio
import bisect
import logging
import time
from typing import Callable

from app.trading.onchain import copytrade as ct

logger = logging.getLogger(__name__)

DAY = 86_400
WINDOWS = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY}
MAX_SIGS = 5_000           # a wallet busier than this in 30 days is a bot: say how far back we got
BATCH = 20                 # getTransaction calls per JSON-RPC batch
DUST_SHARE = 0.01          # under 1% of the most it held left: the trade is closed
BOT_SWAPS_PER_DAY = 150
CACHE_S = 15 * 60
_cache: dict[str, tuple[float, dict]] = {}


def cached(address: str) -> dict | None:
    hit = _cache.get(address)
    return hit[1] if hit and time.time() - hit[0] < CACHE_S else None


# ── pure part ─────────────────────────────────────────────────────────────

def price_at(hours: list[int], closes: list[float], t: float, fallback: float) -> float:
    """SOL close of the hour holding t (the last known hour before it)."""
    if not hours:
        return fallback
    i = bisect.bisect_right(hours, int(t)) - 1
    return closes[max(0, i)]


def round_trips(swaps: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Closed trades, positions still open, sells with no known buy; swaps
    sorted by time, each with "usd"."""
    pos: dict[str, dict] = {}
    trades: list[dict] = []
    orphan: list[dict] = []
    for s in swaps:
        p = pos.setdefault(s["mint"], {"qty": 0.0, "peak": 0.0, "trip": None})
        if s["side"] == "buy":
            if p["trip"] is None:
                p["trip"] = {"mint": s["mint"], "opened_at": s["t"], "invested": 0.0, "returned": 0.0,
                             "buys": 0, "sells": 0}
                p["qty"] = p["peak"] = 0.0
            p["qty"] += s["units"]
            p["peak"] = max(p["peak"], p["qty"])
            p["trip"]["invested"] += s["usd"]
            p["trip"]["buys"] += 1
            continue
        known = min(s["units"], p["qty"]) if p["trip"] else 0.0
        if known <= 0:
            orphan.append(s)
            continue
        share = known / s["units"]
        trip = p["trip"]
        trip["returned"] += s["usd"] * share
        trip["sells"] += 1
        if share < 1:
            orphan.append({**s, "units": s["units"] - known, "usd": s["usd"] * (1 - share)})
        p["qty"] -= known
        if p["qty"] <= DUST_SHARE * p["peak"]:
            trades.append({**trip, "closed_at": s["t"], "pnl": trip["returned"] - trip["invested"],
                           "hold_s": s["t"] - trip["opened_at"]})
            p["qty"], p["peak"], p["trip"] = 0.0, 0.0, None
    still = [{**p["trip"], "share_left": p["qty"] / p["peak"] if p["peak"] else 1.0}
             for p in pos.values() if p["trip"] is not None]
    return trades, still, orphan


def window(trades: list[dict], still: list[dict], orphan: list[dict], since: float) -> dict:
    ts = [t for t in trades if t["opened_at"] >= since]
    wins = [t for t in ts if t["pnl"] > 0]
    losses = [t for t in ts if t["pnl"] <= 0]
    pnl = sum(t["pnl"] for t in ts)
    invested = sum(t["invested"] for t in ts)
    holds = sorted(t["hold_s"] for t in ts)
    best = max(ts, key=lambda t: t["pnl"], default=None)
    worst = min(ts, key=lambda t: t["pnl"], default=None)
    return {
        "trades": len(ts), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(ts) * 100) if ts else None,
        "pnl_usd": round(pnl, 2),
        "roi_pct": round(pnl / invested * 100, 1) if invested > 0 else None,
        "invested_usd": round(invested, 2),
        "returned_usd": round(sum(t["returned"] for t in ts), 2),
        "avg_win_usd": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss_usd": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
        "median_hold_s": holds[len(holds) // 2] if holds else None,
        "tokens": len({t["mint"] for t in ts}),
        "best": {"mint": best["mint"], "pnl_usd": round(best["pnl"], 2)} if best and best["pnl"] > 0 else None,
        "worst": {"mint": worst["mint"], "pnl_usd": round(worst["pnl"], 2)} if worst and worst["pnl"] < 0 else None,
        "excluded_open": sum(1 for o in still if o["opened_at"] >= since),
        "excluded_opened_before": sum(1 for t in trades if t["closed_at"] >= since > t["opened_at"]),
        "sells_without_cost": sum(1 for o in orphan if o["t"] >= since),
    }


def tokens(trades: list[dict], limit: int = 25) -> list[dict]:
    rows: dict[str, dict] = {}
    for t in trades:
        r = rows.setdefault(t["mint"], {"mint": t["mint"], "trades": 0, "wins": 0, "pnl_usd": 0.0, "invested_usd": 0.0})
        r["trades"] += 1
        r["wins"] += t["pnl"] > 0
        r["pnl_usd"] += t["pnl"]
        r["invested_usd"] += t["invested"]
    for r in rows.values():
        r["pnl_usd"], r["invested_usd"] = round(r["pnl_usd"], 2), round(r["invested_usd"], 2)
    return sorted(rows.values(), key=lambda r: abs(r["pnl_usd"]), reverse=True)[:limit]


# ── network ───────────────────────────────────────────────────────────────

async def _signatures(address: str, since: float, say: Callable[[str], None]) -> tuple[list[dict], bool]:
    out: list[dict] = []
    before = None
    while len(out) < MAX_SIGS:
        opts = {"limit": 1000}
        if before:
            opts["before"] = before
        rows = await ct.rpc("getSignaturesForAddress", [address, opts]) or []
        if not rows:
            return out, False
        for r in rows:
            if (r.get("blockTime") or 0) < since:
                return out, False
            if r.get("err") is None:
                out.append(r)
        before = rows[-1]["signature"]
        say(f"{len(out)} transactions found")
    return out[:MAX_SIGS], True


async def _batch_once(sigs: list[str]) -> list[dict | None]:
    import httpx
    body = [{"jsonrpc": "2.0", "id": i, "method": "getTransaction",
             "params": [s, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]}
            for i, s in enumerate(sigs)]
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(timeout=40.0) as c:
                r = await c.post(ct._rpc_url(), json=body)
            if r.status_code == 200 and isinstance(r.json(), list):
                got = {x.get("id"): x.get("result") for x in r.json()}
                return [got.get(i) for i in range(len(sigs))]
            err = f"RPC {r.status_code}"
        except httpx.HTTPError as exc:
            err = f"RPC unreachable ({type(exc).__name__})"     # never the URL: it holds the key
        if attempt == 3:
            raise RuntimeError(err)
        await asyncio.sleep((4.0 if "429" in err else 1.5) * (attempt + 1))
    return []


async def _batch(sigs: list[str]) -> list[dict | None]:
    """A batch answers some calls with an error under rate limits (seen on
    the public node, 23/10): those are asked again, twice, before giving up.
    A batch refused outright (429 after every retry) ends as unread, never
    as the end of the whole analysis (956 transactions lost to one 429, 23/10)."""
    try:
        out = await _batch_once(sigs)
    except RuntimeError:
        out = [None] * len(sigs)          # still refused: counted as unread, the analysis goes on
    for wait in (1.0, 2.5):
        missing = [i for i, tx in enumerate(out) if tx is None]
        if not missing:
            break
        await asyncio.sleep(wait)
        try:
            again = await _batch_once([sigs[i] for i in missing])
        except RuntimeError:
            continue
        for i, tx in zip(missing, again):
            out[i] = tx
    return out


async def _sol_history(since: float) -> tuple[list[int], list[float]]:
    from app.providers.mexc import MexcProvider
    try:
        df = await MexcProvider().fetch_ohlcv("SOLUSDT", "1h", int((time.time() - since) / 3600) + 48)
    except Exception as exc:  # noqa: BLE001
        logger.warning("wallet_pnl: no SOL history (%s), today's price used", exc)
        return [], []
    return [int(ts.timestamp()) for ts in df.index], [float(x) for x in df["close"]]


async def analyze(address: str, say: Callable[[str], None] = lambda m: None) -> dict:
    if not ct.valid_address(address):
        raise ValueError("Not a Solana wallet address.")
    now = time.time()
    since = now - WINDOWS["30d"]
    say("Reading the wallet's history (30 days)")
    sigs, partial = await _signatures(address, since, say)
    hours, closes_px = await _sol_history(since)
    sol_now = await ct.sol_price() or (closes_px[-1] if closes_px else 0.0)
    if not sol_now:
        raise RuntimeError("No SOL price right now, try again.")
    helius = bool(ct._helius())
    swaps: list[dict] = []
    unread = 0
    names = [r["signature"] for r in sigs]
    for i in range(0, len(names), BATCH):
        part = names[i:i + BATCH]
        txs = await _batch(part)
        unread += sum(1 for tx in txs if tx is None)
        for sig, tx in zip(part, txs):
            s = ct.parse_swap(tx, address) if tx else None
            if s is None:
                continue
            t = s["block_time"] or now
            usd = s["sol"] * price_at(hours, closes_px, t, sol_now) + s["stable_usd"]
            swaps.append({"t": t, "sig": sig, "side": s["side"], "mint": s["mint"], "units": s["units"],
                          "decimals": s["decimals"], "usd": usd})
        if (i // BATCH) % 5 == 4 or i + BATCH >= len(names):
            say(f"Read {min(i + BATCH, len(names))} of {len(names)} transactions, {len(swaps)} swaps")
        if not helius:
            await asyncio.sleep(1.0)          # the public node limits bursts
    swaps.sort(key=lambda s: s["t"])
    trades, still, orphan = round_trips(swaps)
    span_days = max(1.0, (now - (swaps[0]["t"] if swaps else now)) / DAY)
    result = {
        "address": address, "generated_at": now, "sol_price": sol_now,
        "coverage": {"from": sigs[-1].get("blockTime") if sigs else None, "transactions": len(sigs),
                     "swaps": len(swaps), "partial": partial, "unread": unread, "sol_history": bool(hours)},
        "windows": {k: window(trades, still, orphan, now - v) for k, v in WINDOWS.items()},
        "still_open": sorted(({"mint": o["mint"], "opened_at": o["opened_at"], "invested_usd": round(o["invested"], 2),
                               "returned_usd": round(o["returned"], 2)} for o in still),
                             key=lambda o: -o["opened_at"])[:20],
        "still_open_count": len(still),
        "tokens": tokens(trades),
        "swaps_per_day": round(len(swaps) / span_days, 1),
        "bot_like": len(swaps) / span_days > BOT_SWAPS_PER_DAY or partial,
    }
    _cache[address] = (time.time(), result)
    return result
