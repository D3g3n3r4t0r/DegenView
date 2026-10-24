"""Overfitting checks for AlphaTrend 1H (Lorenzo, 24/10: "Hai verificato che
non ci sia troppo overfitting?", then "procedi con tutti i controlli").

Per pair, with the SITE's own code (STRATEGY_REGISTRY, BTC weekly filter
with its exit, run_backtest): every cell of the Lab's grid (period 7-30 x
multiplier 0.2-1.5, 336 cells) once over the whole Binance 1h history,
at the site's costs and at double costs. Output: the simple return of each
calendar month (trades by entry month) per cell — what the summary needs
for walk-forward, PBO and the deflated Sharpe (robust_1h_summary.py).
Plus the chosen cell on MEXC's own candles (the site's provider) over the
months both sources have, because the money flow reads the volumes.

    cd backend && PAIR=BTCUSDT PYTHONPATH=. python ../scripts/robust_1h.py
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import research_1h as R  # noqa: E402

from app.analysis import btc_regime  # noqa: E402
from app.analysis.backtest import run_backtest  # noqa: E402
from app.analysis.optimize import _GRID_ALPHATREND  # noqa: E402
from app.analysis.strategies import ALPHATREND_1H, STRATEGY_REGISTRY  # noqa: E402

COSTS = {"base": (0.06, 0.02), "x2": (0.12, 0.04)}
CHOSEN = (17, 0.4)


def monthly(bt) -> dict:
    out: dict[str, list] = {}
    for t in bt.trades:
        ts = t.entry_time // 1000 if t.entry_time > 10**11 else t.entry_time
        k = f"{pd.Timestamp(ts, unit='s', tz='UTC'):%Y-%m}"
        cell = out.setdefault(k, [0.0, 0])
        cell[0] += t.pnl_pct
        cell[1] += 1
    return {k: [round(v[0], 3), v[1]] for k, v in sorted(out.items())}


def run(df, period, coeff, cost):
    params = {"at_period": period, "at_coeff": coeff, "btc_filter": True, "btc_filter_exit": True}
    sig = STRATEGY_REGISTRY[ALPHATREND_1H](df, params)
    c, s = COSTS[cost]
    bp = {**R.BP, "commission_pct": c, "slippage_pct": s}
    return run_backtest(df, params, bp, signals=sig, strategy_name=ALPHATREND_1H)


async def mexc(symbol):
    from app.providers.mexc import MexcProvider
    since = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp() * 1000)
    return await MexcProvider().fetch_ohlcv(symbol, "1h", 60000, since_ms=since)


def main() -> int:
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        df = R.binance(sym)
        btc = df if sym == "BTCUSDT" else R.binance("BTCUSDT")
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={sym}::{exc}")
        return 0
    btc_regime.set_closes(btc["close"].resample("1D").last().dropna(), pin=True)
    res = {"symbol": sym, "since": f"{df.index[0]:%Y-%m}",
           "hold": {f"{y}": round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1)
                    for y, g in df["close"].groupby(df.index.year) if len(g) > 24 * 30},
           "cells": {}}
    t0 = time.time()
    for period in _GRID_ALPHATREND["at_period"]:
        for coeff in _GRID_ALPHATREND["at_coeff"]:
            for cost in COSTS:
                res["cells"][f"{cost}|{period},{coeff}"] = monthly(run(df, period, coeff, cost))
    print(f"{sym}: grid {time.time() - t0:.0f}s", flush=True)
    # the chosen cell on MEXC's candles, over the months both sources cover
    try:
        mx = asyncio.run(mexc(sym))
        mx = mx[~mx.index.duplicated()].sort_index()
        start = max(mx.index[0], df.index[0]) + pd.Timedelta(days=30)   # indicators warmed up
        res["mexc"] = {"since": f"{mx.index[0]:%Y-%m}", "candles": len(mx),
                       "mexc": monthly(run(mx, *CHOSEN, "base")),
                       "binance": monthly(run(df, *CHOSEN, "base")),
                       "from": f"{start:%Y-%m}"}
    except Exception as exc:  # noqa: BLE001
        res["mexc"] = {"error": str(exc)[:120]}
    with gzip.open(f"rob-{sym}.json.gz", "wt") as fh:
        json.dump(res, fh)
    print(f"{sym}: done, mexc {res['mexc'].get('candles', res['mexc'].get('error'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
