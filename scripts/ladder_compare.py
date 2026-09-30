"""Compare the trend follower's timeframe rules on the Top tokens.

Old rule: 1d with >= 60 closed candles, else 8h, else nothing.
New rule (strategy_lab.LADDER): from the widest rung with >= 60 closed
candles down to the first where the trend follower enters at least once.

Self-contained on purpose: it runs inside the production container before
the new rule is deployed, reading the saved lab results and calling
GeckoTerminal through the shared limiter, paced. Read-only: it writes
nothing to the data volume.

    docker compose exec -T app python - < scripts/ladder_compare.py
"""
import asyncio
import json
import statistics
import sys
import time

import httpx

from app.sniper.scanner import GECKO_NETWORKS
from app.trading.onchain import alert_track, system
from app.trading.onchain.storage import data_file

MIN_BARS = 60
LIMIT = 50
PACE_S = 4.0
RETRIES = 6          # GeckoTerminal 429s: back off, never cache a missing answer
LADDER = [("1d", "day", 1), ("12h", "hour", 12), ("8h", "hour", 4), ("6h", "hour", 1), ("4h", "hour", 4),
          ("2h", "hour", 1), ("1h", "hour", 1), ("30m", "minute", 15), ("15m", "minute", 15),
          ("5m", "minute", 5)]
STEP = {"1d": 86400, "12h": 43200, "8h": 28800, "6h": 21600, "4h": 14400, "2h": 7200, "1h": 3600,
        "30m": 1800, "15m": 900, "5m": 300}
NATIVE = {"day": 86400, "hour": 3600, "minute": 60}


def merge(bars, step):
    out = {}
    for b in sorted(bars):
        k = int(b[0]) // step * step
        c = out.get(k)
        if c is None:
            out[k] = [k, b[1], b[2], b[3], b[4], b[5]]
        else:
            c[2], c[3], c[4], c[5] = max(c[2], b[2]), min(c[3], b[3]), b[4], c[5] + b[5]
    return [out[k] for k in sorted(out)]


def closed(bars, step, now):
    return [b for b in bars if b[0] + step <= now]


def summary(iv, res):
    row = next(iter(res.get("rows") or []), {})
    return {"interval": iv, "ret": row.get("return_pct"), "trades": row.get("trades") or 0,
            "in_position": bool(row.get("in_position"))}


def entered(s):
    return bool(s["trades"] or s["in_position"])


class Fetch:
    def __init__(self, client, net, pair, token, now):
        self.client, self.net, self.pair, self.token, self.now = client, net, pair, token, now
        self.got = {}

    async def get(self, tf, agg):
        if self.got.get((tf, agg)) is None:
            for i in range(RETRIES):
                await asyncio.sleep(PACE_S * (2 ** i if i else 1))
                raw = await alert_track._candles(self.client, self.net, self.pair, tf, agg,
                                                 self.now, 1000, self.token)
                if raw is not None:
                    self.got[(tf, agg)] = raw
                    break
        return self.got.get((tf, agg))

    async def rung(self, iv, tf, agg):
        raw = await self.get(tf, agg)
        if raw is None:
            return None
        return closed(sorted(raw) if NATIVE[tf] * agg == STEP[iv] else merge(raw, STEP[iv]), STEP[iv], self.now)


async def old_rule(f):
    for iv, tf, agg in (("1d", "day", 1), ("8h", "hour", 4)):
        bars = await f.rung(iv, tf, agg)
        if bars is None:
            return None
        if len(bars) >= MIN_BARS:
            return summary(iv, system.backtest_one(bars))
    return {"interval": "-", "ret": None, "trades": 0, "in_position": False}


async def new_rule(f):
    fast, day = await f.get("minute", 5), await f.get("day", 1)
    if day is None or fast is None:
        return None
    first = min([b[0] for b in fast + day] or [f.now])
    age = f.now - first
    start = next((i for i, (iv, _, _) in enumerate(LADDER) if age >= MIN_BARS * STEP[iv]), len(LADDER) - 1)
    rungs = []
    for iv, tf, agg in LADDER[start:]:
        bars = await f.rung(iv, tf, agg)
        if bars is None:
            return None
        if len(bars) >= MIN_BARS:
            rungs.append((iv, bars))
    widest = None
    for name, label in (("Lorenzo (trend-follower)", "Trend EMA"), ("Lorenzo HF (minuti on-chain)", "Trend HF")):
        for iv, bars in rungs:
            s = {**summary(iv, system.backtest_one(bars, name, label)), "strategy": label}
            if entered(s):
                return s
            widest = widest or s
    return widest or {"interval": "-", "ret": None, "trades": 0, "in_position": False}


def book(rows, key, cash=10_000.0):
    """Equal slice of the cash per token, each slice grown by the rule's return."""
    each = cash / max(len(rows), 1)
    return sum(each * (1 + ((r[key] or {}).get("ret") or 0) / 100) for r in rows)


async def main():
    store = json.loads(data_file("onchain_strategy_lab.json").read_text())
    res = store.get("results", store)
    items = sorted(((k, v) for k, v in res.items() if isinstance(v, dict) and v.get("pair")
                    and (v.get("daily") or {}).get("rows")),
                   key=lambda kv: -(kv[1].get("at") or 0))[:LIMIT]
    now = time.time()
    out = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for key, v in items:
            chain, token = key.split(":", 1)
            f = Fetch(client, GECKO_NETWORKS[chain], v["pair"], token, now)
            saved = summary(v["daily"].get("interval"), v["daily"])
            old, new = await old_rule(f), await new_rule(f)
            out.append({"symbol": v.get("symbol"), "chain": chain, "saved": saved, "old": old, "new": new})
            print(f"{v.get('symbol', '?'):>10}  saved {saved['interval']:>3} {saved['ret']!s:>8}% "
                  f"{saved['trades']:>2}t | old {(old or {}).get('interval', '?'):>3} {(old or {}).get('ret')!s:>8}% "
                  f"| new {(new or {}).get('interval', '?'):>3} {(new or {}).get('ret')!s:>8}% "
                  f"{(new or {}).get('trades', 0):>2}t", file=sys.stderr, flush=True)
    ok = [r for r in out if r["old"] and r["new"]]
    tot = {}
    for k in ("saved", "old", "new"):
        rets = [r[k]["ret"] for r in ok if r[k]["ret"] is not None]
        tot[k] = {"tokens_with_trades": sum(1 for r in ok if r[k]["trades"]),
                  "mean_ret": round(statistics.mean(rets), 2) if rets else None,
                  "median_ret": round(statistics.median(rets), 2) if rets else None,
                  "book_10k": round(book(ok, k), 2)}
    print(json.dumps({"at": now, "tokens": len(ok), "totals": tot, "rows": out}, indent=1))


asyncio.run(main())
