"""Claudio 4H against RSI+BB 4H on real 4h candles, judged on the last 12
months that neither search saw (Lorenzo, 15/10: "prima di renderla
operativa"). Runs in CI (scripts/../.github/workflows/claudio-compare.yml),
which can reach the exchanges; prints a table and one notice per pair.

    cd backend && PYTHONPATH=. python ../scripts/compare_claudio.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.optimize import (
    CLAUDIO_DIMS,
    calendar_years,
    max_return_search_3d,
    max_return_search_nd,
)
from app.analysis.strategies import CLAUDIO_4H, RSI_BB_4H, STRATEGY_REGISTRY

PAIRS = os.environ.get("PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,SUIUSDT,LTCUSDT").split(",")
BP = {"initial_capital": 1000.0, "qty_pct_of_equity": 100.0, "commission_pct": 0.06,
      "slippage_pct": 0.02, "fill_at": "signal_close"}
WARMUP = 300


async def candles(symbol: str) -> tuple[str, pd.DataFrame]:
    from app.providers.kucoin import KucoinProvider
    from app.providers.mexc import MexcProvider
    last = None
    for name, prov in (("mexc", MexcProvider()), ("kucoin", KucoinProvider())):
        try:
            df = await prov.fetch_ohlcv(symbol, "4h", 20000)
            if len(df) > 2000:
                return name, df
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"{symbol}: no candles ({last})")


def held_out_backtest(df: pd.DataFrame, cut, strategy: str, params: dict):
    start = max(0, df.index.searchsorted(cut) - WARMUP)
    frame = df.iloc[start:]
    sig = STRATEGY_REGISTRY[strategy](frame, params).copy()
    sig.loc[sig.index < cut, :] = False
    return run_backtest(frame, params, BP, signals=sig, strategy_name=strategy)


def annual(ret: float, days: float) -> float:
    y = max(days / 365.25, 0.01)
    return ((1 + ret / 100) ** (1 / y) - 1) * 100 if ret > -100 else -100.0


def one(symbol: str, df: pd.DataFrame) -> dict:
    cut = df.index[-1] - pd.Timedelta(days=365)
    train = df[df.index < cut]
    years = calendar_years(train.index)
    hold = (df["close"].iloc[-1] / df["close"].iloc[df.index.searchsorted(cut)] - 1) * 100
    out = {"symbol": symbol, "from": f"{df.index[0]:%Y-%m}", "train_days": (train.index[-1] - train.index[0]).days,
           "hold": hold}
    for strat, search in ((RSI_BB_4H, max_return_search_3d),
                          (CLAUDIO_4H, lambda s, f, **kw: max_return_search_nd(s, f, dims=CLAUDIO_DIMS, **kw))):
        t0 = time.time()
        try:
            _, _, n, picks = search(strat, lambda p: run_backtest(train, p, BP, strategy_name=strat), years=years)
        except ValueError as exc:
            out[strat] = {"error": str(exc)[:80]}
            continue
        res = {"n": n, "secs": round(time.time() - t0)}
        for c in picks:
            tb = held_out_backtest(df, cut, strat, c["params"])
            res[c["kind"]] = {"params": {k: v for k, v in c["params"].items() if k.startswith(("cl_", "rsi_o", "bb_m"))},
                              "train": c["backtest"].total_return_pct,
                              "train_annual": annual(c["backtest"].total_return_pct, out["train_days"]),
                              "test": tb.total_return_pct, "test_trades": tb.num_trades,
                              "test_dd": tb.max_drawdown_pct, "solidity": c["solidity"]}
        out[strat] = res
    return out


def fmt(r: dict) -> str:
    parts = [f"{r['symbol']} (since {r['from']}, B&H last 12m {r['hold']:+.0f}%)"]
    for strat in (RSI_BB_4H, CLAUDIO_4H):
        x = r.get(strat, {})
        if "error" in x:
            parts.append(f"{strat}: none ({x['error']})")
            continue
        s = x.get("solid") or x.get("solid+profitable") or {}
        p = x.get("profitable") or s
        parts.append(f"{strat}: solid {s.get('train_annual', 0):+.0f}%/y hist → {s.get('test', 0):+.0f}% unseen "
                     f"({s.get('test_trades', 0)} tr, DD {s.get('test_dd', 0):.0f}%) {s.get('params')}; "
                     f"profitable → {p.get('test', 0):+.0f}% unseen [{x.get('n')} bt, {x.get('secs')}s]")
    return " | ".join(parts)


async def main() -> int:
    rows = []
    for sym in PAIRS:
        try:
            src, df = await candles(sym)
        except Exception as exc:  # noqa: BLE001
            print(f"::warning::{sym}: {exc}")
            continue
        r = one(sym, df)
        r["src"] = src
        rows.append(r)
        line = fmt(r)
        print(line, flush=True)
        print(f"::notice title={sym}::{line}", flush=True)
    wins = sum(1 for r in rows
               if "error" not in r.get(CLAUDIO_4H, {"error": 1}) and "error" not in r.get(RSI_BB_4H, {"error": 1})
               and (r[CLAUDIO_4H].get("solid") or r[CLAUDIO_4H].get("solid+profitable"))["test"]
               > (r[RSI_BB_4H].get("solid") or r[RSI_BB_4H].get("solid+profitable"))["test"])
    summary = f"Claudio 4H beats RSI+BB 4H (most solid, last 12 months unseen) on {wins} of {len(rows)} pairs"
    print(f"::notice title=summary::{summary}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write("## " + summary + "\n\n" + "\n\n".join(fmt(r) for r in rows) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
