"""Every calendar year in turn as the unseen one (Lorenzo, 15/10: "testare
dal 2023 al 2026 [...] e poi applicarla al 2022 oppure al 2021, in modo da
variare gli anni testati con candele mai viste").

For one pair: for each test year Y (2021, 2022, 2023, 2024 and the last 12
months), each strategy is searched with Max return on all the other candles
— Y masked out: no trade opens inside it, and one already open is closed at
its first candle — then its most solid and most profitable picks run on Y
alone, indicators warmed up on the candles before. Strategies: RSI+BB 4H,
Claudio 4H, and Claudio without its regime filter (to see if the filter
earns its place). Runs in CI, one job per pair (claudio-folds.yml).

    cd backend && PAIR=BTCUSDT PYTHONPATH=. python ../scripts/compare_claudio_folds.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.optimize import CLAUDIO_DIMS, max_return_search_3d, max_return_search_nd
from app.analysis.strategies import CLAUDIO_4H, RSI_BB_4H, STRATEGY_REGISTRY

BP = {"initial_capital": 1000.0, "qty_pct_of_equity": 100.0, "commission_pct": 0.06,
      "slippage_pct": 0.02, "fill_at": "signal_close"}
WARMUP = 300
VARIANTS = (
    ("RSI+BB 4H", RSI_BB_4H, {}),
    ("Claudio 4H", CLAUDIO_4H, {}),
    ("Claudio no-regime", CLAUDIO_4H, {"cl_er_max": 1.0}),   # every candle counts as ranging
)


async def candles(symbol: str) -> tuple[str, pd.DataFrame]:
    from app.providers.kucoin import KucoinProvider
    from app.providers.mexc import MexcProvider
    best, last = None, None
    for name, prov in (("kucoin", KucoinProvider()), ("mexc", MexcProvider())):
        try:
            df = await prov.fetch_ohlcv(symbol, "4h", 20000)
            if best is None or len(df) > len(best[1]):
                best = (name, df)
        except Exception as exc:  # noqa: BLE001
            last = exc
    if best is None or len(best[1]) < 3000:
        raise RuntimeError(f"{symbol}: not enough candles ({last})")
    return best


async def rank(symbol: str) -> int | None:
    try:
        from app import market_rank
        return market_rank.rank_for(symbol, await market_rank.ranks())
    except Exception:  # noqa: BLE001
        return None


def masked(df, strategy, params, t0, t1):
    """Signals with the test window [t0, t1) taken out of the training."""
    sig = STRATEGY_REGISTRY[strategy](df, params).copy()
    inside = (sig.index >= t0) & (sig.index < t1)
    sig.loc[inside, "entry_long"] = False
    first = sig.index[inside]
    if len(first):
        sig.loc[first[0], "exit_long"] = True
        sig.loc[inside & (sig.index > first[0]), "exit_long"] = False
    return sig


def judged_years(df, t0, t1):
    """Calendar years of the training: not the first, not the last, not Y."""
    years = range(df.index[0].year + 1, df.index[-1].year)
    return [y for y in years if not (pd.Timestamp(year=y, month=1, day=1, tz=df.index.tz) >= t0
                                     and pd.Timestamp(year=y, month=12, day=31, tz=df.index.tz) < t1 + pd.Timedelta(days=1))]


def test_on(df, strategy, params, t0, t1):
    start = max(0, df.index.searchsorted(t0) - WARMUP)
    frame = df[(df.index < t1)].iloc[start:]
    sig = STRATEGY_REGISTRY[strategy](frame, params).copy()
    sig.loc[sig.index < t0, :] = False
    return run_backtest(frame, params, BP, signals=sig, strategy_name=strategy)


def folds(df):
    tz = df.index.tz
    out = []
    for y in (2021, 2022, 2023, 2024):
        t0, t1 = pd.Timestamp(year=y, month=1, day=1, tz=tz), pd.Timestamp(year=y + 1, month=1, day=1, tz=tz)
        if df.index[0] <= t0 - pd.Timedelta(days=60) and df.index[-1] >= t1:
            out.append((str(y), t0, t1))
    t1 = df.index[-1] + pd.Timedelta(hours=4)
    out.append(("last 12m", df.index[-1] - pd.Timedelta(days=365), t1))
    return out


def annual(ret, days):
    yrs = max(days / 365.25, 0.01)
    return ((1 + ret / 100) ** (1 / yrs) - 1) * 100 if ret > -100 else -100.0


def run_pair(symbol, df):
    res = {"symbol": symbol, "since": f"{df.index[0]:%Y-%m}", "folds": []}
    for label, t0, t1 in folds(df):
        seg = df[(df.index >= t0) & (df.index < t1)]
        hold = (seg["close"].iloc[-1] / seg["close"].iloc[0] - 1) * 100
        years = judged_years(df, t0, t1)
        train_days = (df.index[-1] - df.index[0]).days - (t1 - t0).days
        f = {"test": label, "hold": round(hold, 1), "years": years}
        for name, strat, fixed in VARIANTS:
            t = time.time()

            def bt(p, strat=strat):
                return run_backtest(df, p, BP, signals=masked(df, strat, p, t0, t1), strategy_name=strat)
            try:
                if strat == CLAUDIO_4H:
                    _, _, n, picks = max_return_search_nd(strat, bt, dims=CLAUDIO_DIMS, fixed=fixed, years=years)
                else:
                    _, _, n, picks = max_return_search_3d(strat, bt, years=years)
            except ValueError as exc:
                f[name] = {"error": str(exc)[:60]}
                continue
            row = {"n": n, "s": round(time.time() - t)}
            for c in picks:
                tb = test_on(df, strat, c["params"], t0, t1)
                row[c["kind"]] = {"hist_y": round(annual(c["backtest"].total_return_pct, train_days), 1),
                                  "test": round(tb.total_return_pct, 1), "tr": tb.num_trades,
                                  "dd": round(tb.max_drawdown_pct, 1), "sol": c["solidity"],
                                  "p": {k: v for k, v in c["params"].items() if k in ("rsi_oversold", "rsi_overbought", "bb_mult", "cl_rsi_os", "cl_bb_mult", "cl_atr_stop")}}
            f[name] = row
        res["folds"].append(f)
        print(json.dumps(f), flush=True)
    return res


def solid(row):
    return row.get("solid") or row.get("solid+profitable")


def line(res):
    bits = [f"{res['symbol']} #{res.get('rank') or '?'} since {res['since']}"]
    for f in res["folds"]:
        cell = [f"{f['test']} B&H {f['hold']:+.0f}%"]
        for name, _, _ in VARIANTS:
            r = f.get(name, {})
            s = solid(r) if "error" not in r else None
            cell.append(f"{name.split()[0][0]}{'n' if 'no-regime' in name else ''} "
                        + (f"{s['test']:+.0f}% ({s['tr']}tr)" if s else "none"))
        bits.append(" / ".join(cell))
    return " | ".join(bits)


async def main():
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        src, df = await candles(sym)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={sym}::{exc}")
        return 0
    res = run_pair(sym, df)
    res["rank"], res["src"] = await rank(sym), src
    msg = line(res) + f" [{src}]"
    print(msg)
    print(f"::notice title={sym}::{msg}")
    with open(f"folds-{sym}.json", "w") as fh:
        json.dump(res, fh)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
