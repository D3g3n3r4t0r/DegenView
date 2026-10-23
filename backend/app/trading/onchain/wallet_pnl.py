"""How profitable a Solana wallet's trades were: last 24 hours, 7 and 30 days.

Asked on 23/10, for the copy trading section: "un tool che permetta di
controllare la profittabilita' dei trade fatti dal wallet che noi prendiamo
in considerazione [...] ultime 24 ore, ultimi 7 giorni, ultimi 30 giorni".

- history: the wallet's signatures back to 30 days (at most MAX_SIGS), every
  transaction read and passed through copytrade.parse_swap, so the analysis
  sees exactly the trades the copier would have seen;
- dollars at the time: SOL legs priced with the SOLUSDT hourly close of the
  trade's hour (MEXC), not today's price;
- positions per token at average cost: a sell realizes proceeds minus the
  average cost of what it sold. Tokens sold without a known buy (bought
  before the history, or received by transfer) are counted apart, never
  given a made-up cost;
- per window: realized P&L and ROI of the sells inside it, win rate per
  token, volumes, best and worst token, and the stricter "opened and
  closed inside the window" figure; plus the open positions valued now.
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
MAX_OPEN_VALUED = 15       # open positions priced with a live quote
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


def realize(swaps: list[dict]) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """Average-cost positions from swaps sorted by time, each with "usd".

    Returns (closes, open positions by mint, sells with no known cost)."""
    pos: dict[str, dict] = {}
    closes: list[dict] = []
    orphan: list[dict] = []
    for s in swaps:
        p = pos.setdefault(s["mint"], {"qty": 0.0, "cost": 0.0, "opened_at": None, "buys": 0})
        if s["side"] == "buy":
            if p["qty"] <= 1e-12:
                p["opened_at"] = s["t"]
            p["qty"] += s["units"]
            p["cost"] += s["usd"]
            p["buys"] += 1
            continue
        known = min(s["units"], p["qty"])
        if known <= 1e-12:
            orphan.append(s)
            continue
        share = known / s["units"]
        cost = p["cost"] * known / p["qty"]
        proceeds = s["usd"] * share
        closes.append({"t": s["t"], "mint": s["mint"], "cost": cost, "proceeds": proceeds,
                       "pnl": proceeds - cost, "opened_at": p["opened_at"], "sig": s.get("sig")})
        if share < 1:
            orphan.append({**s, "units": s["units"] - known, "usd": s["usd"] - proceeds})
        p["qty"] -= known
        p["cost"] -= cost
        if p["qty"] <= 1e-9 * max(1.0, known):
            p["qty"], p["cost"] = 0.0, 0.0
    open_ = {m: p for m, p in pos.items() if p["qty"] > 0 and p["cost"] > 0}
    return closes, open_, orphan


def window(swaps: list[dict], closes: list[dict], orphan: list[dict], since: float) -> dict:
    cs = [c for c in closes if c["t"] >= since]
    by_mint: dict[str, float] = {}
    for c in cs:
        by_mint[c["mint"]] = by_mint.get(c["mint"], 0.0) + c["pnl"]
    wins = sum(1 for v in by_mint.values() if v > 0)
    pnl = sum(c["pnl"] for c in cs)
    cost = sum(c["cost"] for c in cs)
    inside = [c for c in cs if c["opened_at"] is not None and c["opened_at"] >= since]
    in_cost = sum(c["cost"] for c in inside)
    ws = [s for s in swaps if s["t"] >= since]
    best = max(by_mint.items(), key=lambda kv: kv[1], default=None)
    worst = min(by_mint.items(), key=lambda kv: kv[1], default=None)
    return {
        "realized_usd": round(pnl, 2),
        "roi_pct": round(pnl / cost * 100, 1) if cost > 0 else None,
        "sold_cost_usd": round(cost, 2),
        "tokens_closed": len(by_mint), "wins": wins, "losses": len(by_mint) - wins,
        "win_rate_pct": round(wins / len(by_mint) * 100) if by_mint else None,
        "buys": sum(1 for s in ws if s["side"] == "buy"),
        "sells": sum(1 for s in ws if s["side"] == "sell"),
        "bought_usd": round(sum(s["usd"] for s in ws if s["side"] == "buy"), 2),
        "sold_usd": round(sum(s["usd"] for s in ws if s["side"] == "sell"), 2),
        "tokens_traded": len({s["mint"] for s in ws}),
        "opened_and_closed_usd": round(sum(c["pnl"] for c in inside), 2),
        "opened_and_closed_roi_pct": round(sum(c["pnl"] for c in inside) / in_cost * 100, 1) if in_cost > 0 else None,
        "best": {"mint": best[0], "pnl_usd": round(best[1], 2)} if best and best[1] > 0 else None,
        "worst": {"mint": worst[0], "pnl_usd": round(worst[1], 2)} if worst and worst[1] < 0 else None,
        "sells_without_cost": sum(1 for o in orphan if o["t"] >= since),
    }


def tokens(swaps: list[dict], closes: list[dict], open_: dict, limit: int = 25) -> list[dict]:
    rows: dict[str, dict] = {}
    for s in swaps:
        r = rows.setdefault(s["mint"], {"mint": s["mint"], "buys": 0, "sells": 0, "bought_usd": 0.0,
                                        "sold_usd": 0.0, "realized_usd": 0.0, "last_t": 0})
        r["buys" if s["side"] == "buy" else "sells"] += 1
        r["bought_usd" if s["side"] == "buy" else "sold_usd"] += s["usd"]
        r["last_t"] = max(r["last_t"], s["t"])
    for c in closes:
        rows[c["mint"]]["realized_usd"] += c["pnl"]
    for m, r in rows.items():
        r["holding"] = m in open_
        for k in ("bought_usd", "sold_usd", "realized_usd"):
            r[k] = round(r[k], 2)
    return sorted(rows.values(), key=lambda r: abs(r["realized_usd"]), reverse=True)[:limit]


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
    closes, open_, orphan = realize(swaps)

    say("Valuing open positions")
    dec = {s["mint"]: s["decimals"] for s in swaps}
    opened = []
    for mint, p in sorted(open_.items(), key=lambda kv: -kv[1]["cost"])[:MAX_OPEN_VALUED]:
        value = None
        try:
            q = await ct.quote(mint, ct.WSOL, int(p["qty"] * 10 ** dec[mint]), 1000)
            value = q["out_amount"] / 1e9 * sol_now
        except RuntimeError:
            pass                              # no route: worth nothing we could sell
        opened.append({"mint": mint, "cost_usd": round(p["cost"], 2), "opened_at": p["opened_at"],
                       "value_usd": round(value, 2) if value is not None else None,
                       "unrealized_usd": round(value - p["cost"], 2) if value is not None else None})
    span_days = max(1.0, (now - (swaps[0]["t"] if swaps else now)) / DAY)
    result = {
        "address": address, "generated_at": now, "sol_price": sol_now,
        "coverage": {"from": sigs[-1].get("blockTime") if sigs else None, "transactions": len(sigs),
                     "swaps": len(swaps), "partial": partial, "unread": unread, "sol_history": bool(hours)},
        "windows": {k: window(swaps, closes, orphan, now - v) for k, v in WINDOWS.items()},
        "open": opened,
        "open_count": len(open_),
        "unrealized_usd": round(sum(o["unrealized_usd"] or 0 for o in opened), 2),
        "tokens": tokens(swaps, closes, open_),
        "swaps_per_day": round(len(swaps) / span_days, 1),
        "bot_like": len(swaps) / span_days > BOT_SWAPS_PER_DAY or partial,
    }
    _cache[address] = (time.time(), result)
    return result
