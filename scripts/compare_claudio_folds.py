"""Every calendar year in turn as the unseen one (Lorenzo, 15/10: "testare
dal 2023 al 2026 [...] e poi applicarla al 2022 oppure al 2021, in modo da
variare gli anni testati con candele mai viste").

For one pair: for each test year Y (2021, 2022, 2023, 2024 and the last 12
months), each strategy is searched with Max return on all the other candles
— Y masked out: no trade opens inside it, and one already open is closed at
its first candle — then its most solid and most profitable picks run on Y
alone, indicators warmed up on the candles before. Strategies: RSI+BB 4H,
Claudio 4H, Claudio v2 (no regime filter, exit at the upper band, trailing
ATR stop), and Lorenzo's trend follower both with its own default values
(nothing searched) and searched the same way. Candles from Binance's public
archive (data.binance.vision, history since 2020, so 2021 and 2022 can be
the unseen year), the current month from MEXC. Runs in CI, one job per pair
(claudio-folds.yml).

    cd backend && PAIR=BTCUSDT PYTHONPATH=. python ../scripts/compare_claudio_folds.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.optimize import CLAUDIO_DIMS, max_return_search_3d, max_return_search_nd
from app.analysis.strategies import CLAUDIO_4H, DEFAULT_PARAMS, RSI_BB_4H, STRATEGY_REGISTRY

BP = {"initial_capital": 1000.0, "qty_pct_of_equity": 100.0, "commission_pct": 0.06,
      "slippage_pct": 0.02, "fill_at": "signal_close"}
WARMUP = 300
LORENZO = "Lorenzo (trend-follower)"
LORENZO_DIMS = (
    ("len", list(range(40, 301, 20))),          # 14
    ("slopeFlen", list(range(3, 22, 2))),       # 10
    ("slopeSlen", list(range(15, 76, 5))),      # 13
)
CLAUDIO_V2 = {"cl_er_max": 1.0, "cl_exit_upper": 1, "cl_trail": 1, "cl_time_stop": 10**6}
# (label, strategy, fixed values, dimensions searched: None = RSI+BB 3D, () = nothing)
VARIANTS = (
    ("RSI+BB 4H", RSI_BB_4H, {}, None),
    ("Claudio 4H", CLAUDIO_4H, {}, CLAUDIO_DIMS),
    ("Claudio v2", CLAUDIO_4H, CLAUDIO_V2, CLAUDIO_DIMS),
    ("Lorenzo default", LORENZO, dict(DEFAULT_PARAMS), ()),
    ("Lorenzo searched", LORENZO, dict(DEFAULT_PARAMS), LORENZO_DIMS),
)
SHORT = {"RSI+BB 4H": "R", "Claudio 4H": "C", "Claudio v2": "C2", "Lorenzo default": "Ld", "Lorenzo searched": "Ls"}
SHOWN = ("rsi_oversold", "rsi_overbought", "bb_mult", "cl_rsi_os", "cl_bb_mult", "cl_atr_stop",
         "len", "slopeFlen", "slopeSlen")


def _binance_month(symbol, y, m):
    url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/4h/{symbol}-4h-{y}-{m:02d}.zip"
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
    except Exception:  # noqa: BLE001 — not listed yet that month
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    rows = [r.split(",") for r in text.splitlines() if r and r[0].isdigit()]
    return rows


def binance(symbol):
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for y in range(2020, now.year + 1):
        for m in range(1, 13):
            if (y, m) >= (now.year, now.month):
                break
            rows += _binance_month(symbol, y, m) or []
    if not rows:
        return None
    ts = pd.Series([int(r[0]) for r in rows])
    ts = ts.where(ts < 10**14, ts // 1000)          # 2025 on: microseconds
    df = pd.DataFrame({k: [float(r[i]) for r in rows] for i, k in
                       enumerate(("open", "high", "low", "close", "volume"), 1)},
                      index=pd.to_datetime(ts.to_numpy(), unit="ms", utc=True))
    return df[~df.index.duplicated()].sort_index()


async def candles(symbol: str) -> tuple[str, pd.DataFrame]:
    from app.providers.kucoin import KucoinProvider
    from app.providers.mexc import MexcProvider
    old = await asyncio.to_thread(binance, symbol)
    if old is not None and len(old) >= 3000:
        try:
            tail = await MexcProvider().fetch_ohlcv(symbol, "4h", 400)
            old = pd.concat([old, tail[tail.index > old.index[-1]][old.columns]])
        except Exception:  # noqa: BLE001 — the archive alone, up to last month
            pass
        return "binance+mexc", old
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
    first = sig.index[inside]
    for side in ("long", "short"):
        sig.loc[inside, f"entry_{side}"] = False
        if len(first):
            sig.loc[first[0], f"exit_{side}"] = True
            sig.loc[inside & (sig.index > first[0]), f"exit_{side}"] = False
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
        for name, strat, fixed, dims in VARIANTS:
            t = time.time()

            def bt(p, strat=strat):
                return run_backtest(df, p, BP, signals=masked(df, strat, p, t0, t1), strategy_name=strat)
            try:
                if dims == ():
                    b = bt(fixed)
                    n, picks = 1, [{"kind": "default", "params": fixed, "backtest": b, "solidity": None}]
                elif dims is None:
                    _, _, n, picks = max_return_search_3d(strat, bt, years=years)
                else:
                    _, _, n, picks = max_return_search_nd(strat, bt, dims=dims, fixed=fixed, years=years)
            except ValueError as exc:
                f[name] = {"error": str(exc)[:60]}
                continue
            row = {"n": n, "s": round(time.time() - t)}
            for c in picks:
                tb = test_on(df, strat, c["params"], t0, t1)
                row[c["kind"]] = {"hist_y": round(annual(c["backtest"].total_return_pct, train_days), 1),
                                  "test": round(tb.total_return_pct, 1), "tr": tb.num_trades,
                                  "dd": round(tb.max_drawdown_pct, 1), "sol": c["solidity"],
                                  "p": {k: v for k, v in c["params"].items() if k in SHOWN}}
            f[name] = row
        res["folds"].append(f)
        print(json.dumps(f), flush=True)
    return res


def solid(row):
    return row.get("solid") or row.get("solid+profitable") or row.get("default")


def line(res):
    bits = [f"{res['symbol']} #{res.get('rank') or '?'} since {res['since']}"]
    for f in res["folds"]:
        cell = [f"{f['test']} B&H {f['hold']:+.0f}%"]
        for name, *_ in VARIANTS:
            r = f.get(name, {})
            s = solid(r) if "error" not in r else None
            cell.append(f"{SHORT[name]} " + (f"{s['test']:+.0f}% ({s['tr']}tr)" if s else "none"))
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
