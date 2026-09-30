"""Old timeframe rule against the new ladder, on the Top's saved tokens.

Also RSI+BB: its 5-minute row of the saved backtest against the same
ladder (rsi_5m / rsi_new).

Old: 1d, else 8h, first with 60 closed candles, Trend EMA only.
New (strategy_lab.LADDER_RULE): from the widest rung with 60 closed candles
down to the first where Trend EMA enters, then the same with Trend HF.

Runs the lab's own run_daily both ways on the candles in
data/candle_archive.sqlite (filled by candle_archive.archive_loop), so it
needs the deployed code. Read-only: the archive is opened with mode=ro and
GeckoTerminal is never called; a series not archived yet counts as empty.

    docker compose exec -T app python - < scripts/ladder_compare.py > ladder_compare.json
"""
import asyncio
import json
import sqlite3
import statistics
import sys
import time

import httpx

from app.sniper.scanner import GECKO_NETWORKS
from app.trading.onchain import candle_archive
from app.trading.onchain import strategy_lab as lab

LIMIT = 50


def summary(d):
    if not d:
        return None
    row = next(iter(d.get("rows") or []), {})
    return {"interval": d.get("interval"), "strategy": row.get("label"), "ret": row.get("return_pct"),
            "trades": row.get("trades") or 0, "in_position": bool(row.get("in_position")),
            "error": d.get("error")}


def book(rows, k, cash=10_000.0):
    each = cash / max(len(rows), 1)
    return round(sum(each * (1 + ((r[k] or {}).get("ret") or 0) / 100) for r in rows), 2)


_ro = sqlite3.connect(f"file:{candle_archive._DB_FILE}?mode=ro", uri=True)


async def archived_rows(net, pair, tf, agg, token=""):
    rows = _ro.execute("SELECT t, o, h, l, c, v FROM candles WHERE k = ? ORDER BY t",
                       (candle_archive.key(net, pair, tf, agg, token),)).fetchall()
    return [list(r) for r in rows]


async def archived(client, net, pair, tf, agg, now, token=""):
    """candle_archive.candles without the network and without writes."""
    return await archived_rows(net, pair, tf, agg, token)


async def main():
    candle_archive.candles = archived
    lab._load()
    items = sorted(((k, v) for k, v in lab._results.items() if v.get("pair") and (v.get("daily") or {}).get("rows")),
                   key=lambda kv: -(kv[1].get("at") or 0))[:LIMIT]
    now = time.time()
    out = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for key, v in items:
            chain, token = key.split(":", 1)
            got = {}
            for rule in (False, True):
                lab.LADDER_RULE = rule
                got[rule] = summary(await lab.run_daily(client, GECKO_NETWORKS[chain], v["pair"], token, now))
            lab.LADDER_RULE = True
            rsi_new = summary(await lab.run_daily(client, GECKO_NETWORKS[chain], v["pair"], token, now,
                                                  strategies=lab.RSI_BB))
            rsi_row = next((r for r in (v.get("backtests") or {}).get("rows") or [] if r.get("label") == "RSI+BB"), None)
            rsi_5m = summary({"interval": "5m", "rows": [rsi_row]}) if rsi_row else None
            net = GECKO_NETWORKS[chain]
            series = {f"{tf}{agg}": len(await archived_rows(net, v["pair"], tf, agg, token))
                        for tf, agg in candle_archive.SOURCES}
            row = {"symbol": v.get("symbol"), "chain": chain, "saved": summary(v["daily"]),
                   "old": got[False], "new": got[True], "rsi_5m": rsi_5m, "rsi_new": rsi_new, "archived": series}
            out.append(row)
            print(json.dumps(row), file=sys.stderr, flush=True)
    lab.LADDER_RULE = False
    ok = [r for r in out if r["old"] and r["new"]]
    tot = {}
    # RSI+BB: today's 5-minute result against the same ladder.
    for k in ("saved", "old", "new", "rsi_5m", "rsi_new"):
        rets = [r[k]["ret"] for r in ok if r[k] and r[k]["ret"] is not None]
        tot[k] = {"with_trades": sum(1 for r in ok if r[k] and r[k]["trades"]),
                  "mean_ret": round(statistics.mean(rets), 2) if rets else None,
                  "median_ret": round(statistics.median(rets), 2) if rets else None,
                  "book_10k": book(ok, k)}
    # A rung whose source is not archived yet counts as "too few candles":
    # the comparison is only fair once every source is there.
    cover = {f"{tf}{agg}": sum(1 for r in out if r["archived"][f"{tf}{agg}"]) for tf, agg in candle_archive.SOURCES}
    print(json.dumps({"at": now, "tokens": len(ok), "archived_series": cover, "totals": tot, "rows": out}, indent=1))


asyncio.run(main())
