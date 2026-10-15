"""The test environment for 4H strategies (Lorenzo, 15/10: "testare dal 2023
al 2026, fare un backtest con i dati e poi quella strategia applicarla al
2022 oppure al 2021" and "lascerei in questo ambiente di test sempre 2021 e
2022 come anni di candele mai viste [...] per qualsiasi tipo di strategia").

For one pair: each strategy is searched with Max return on the candles from
TRAIN_FROM (2023-01-01) on — the same search as the site, most solid and
most profitable pick — and both picks then run on each TEST_YEARS year
(2021, a strong bull year, and 2022, a strong bear year), never seen by the
search, indicators warmed up on the candles before. Every strategy is long
only ("solo long e uscita senza short"): RSI+BB 4H, Claudio 4H, Lorenzo's
trend follower with its own default values (nothing searched) and searched,
each also with a daily EMA 200 filter (no entry under it).
Candles from Binance's public archive (data.binance.vision, since 2020), the
current month from MEXC. Runs in CI, one job per pair (claudio-folds.yml).

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
from app.analysis.optimize import CLAUDIO_DIMS, max_return_search, max_return_search_3d, max_return_search_nd
from app.analysis.strategies import (
    CLAUDIO_1D,
    CLAUDIO_4H,
    CLAUDIO_TREND_4H,
    DEFAULT_PARAMS,
    RSI_BB_4H,
    STRATEGY_REGISTRY,
)

# Lorenzo, 15/10: "lascerei in questo ambiente di test sempre 2021 e 2022 come
# anni di candele mai viste [...] per qualsiasi tipo di strategia": a strong
# bull year and a strong bear year. TEST_YEARS overrides (e.g. "2021,2022,2023").
TEST_YEARS = tuple(int(y) for y in os.environ.get("TEST_YEARS", "2021,2022").split(",") if y)
TRAIN_FROM = pd.Timestamp(os.environ.get("TRAIN_FROM", "2023-01-01"), tz="UTC")

BP = {"initial_capital": 1000.0, "qty_pct_of_equity": 100.0, "commission_pct": 0.06,
      "slippage_pct": 0.02, "fill_at": "signal_close"}
# Lorenzo, 15/10: the same environment for the daily chart ("facciamo
# ambiente di test per timeframe 1D"). TF=4h (default) or TF=1d.
TF = os.environ.get("TF", "4h")
WARMUP = 1500 if TF == "4h" else 300   # ~250 days either way: a daily EMA 200 needs them
LORENZO = "Lorenzo (trend-follower)"
LORENZO_DIMS = (
    ("len", list(range(40, 301, 20))),          # 14
    ("slopeFlen", list(range(3, 22, 2))),       # 10
    ("slopeSlen", list(range(15, 76, 5))),      # 13
)
# (label, strategy, fixed values, dimensions searched: None = RSI+BB 3D,
# () = nothing, trend filter). Claudio v2 dropped after the 2021/22 test.
# Lorenzo, 15/10: "la devi utilizzare come reversal, cioe' solo long e uscita
# senza short" — here only: the site's Lorenzo stays long/short. The short
# signal only closes the long (its exit_long, the slope cross-under).
CLAUDIO_TREND_DIMS = (
    ("ct_len", list(range(30, 241, 15))),                          # 15
    ("ct_atr", [round(2.0 + 0.5 * i, 1) for i in range(9)]),       # 2.0 … 6.0
    ("ct_ema_days", [100, 150, 200]),
)
VARIANTS = (
    ("Claudio Trend 4H", CLAUDIO_TREND_4H, {}, CLAUDIO_TREND_DIMS, False),
    # the values fixed before the first test (120 candles, 4 ATR, EMA 200d), nothing searched
    ("Claudio Trend default", CLAUDIO_TREND_4H, {"ct_len": 120, "ct_atr": 4.0, "ct_ema_days": 200}, (), False),
    ("RSI+BB 4H", RSI_BB_4H, {}, None, False),
    ("Claudio 4H", CLAUDIO_4H, {}, CLAUDIO_DIMS, False),
    ("Lorenzo default", LORENZO, dict(DEFAULT_PARAMS), (), False),
    ("Lorenzo searched", LORENZO, dict(DEFAULT_PARAMS), LORENZO_DIMS, False),
    # 15/10 "provalo": no entry while the price is under the daily EMA 200
    ("RSI+BB 4H +EMA200d", RSI_BB_4H, {}, None, True),
    ("Claudio 4H +EMA200d", CLAUDIO_4H, {}, CLAUDIO_DIMS, True),
    ("Lorenzo default +EMA200d", LORENZO, dict(DEFAULT_PARAMS), (), True),
    ("Lorenzo searched +EMA200d", LORENZO, dict(DEFAULT_PARAMS), LORENZO_DIMS, True),
    # 15/10 "efficace sia nel 2021 sia nel 2022": long above the daily EMA
    # 200, short below it, Lorenzo's own values (nothing searched)
    ("Lorenzo default L/S regime", LORENZO, dict(DEFAULT_PARAMS), (), "ls"),
)
GABRIELE = "Gabriele (RSI+BB reversal)"
CLAUDIO_1D_DIMS = (
    ("c1_ema", [50, 75, 100, 125, 150, 200]),
    ("c1_pb", [10, 15, 20, 25, 30]),
    ("c1_atr", [round(2.0 + 0.5 * i, 1) for i in range(7)]),        # 2.0 … 5.0
)
if TF == "1d":
    # dims "2d" = the site's Max return for RSI+BB (oversold 10-40 × overbought 60-90)
    VARIANTS = (
        # Lorenzo, 15/10: "i valori si scelgono sulle candele dal 2023 a oggi,
        # poi si provano su 2021 e 2022" — no hand-set values for Claudio 1D
        ("Claudio 1D", CLAUDIO_1D, {}, CLAUDIO_1D_DIMS, False),
        ("Claudio 1D +BTC", CLAUDIO_1D, {}, CLAUDIO_1D_DIMS, "btc"),
        ("RSI+BB reversal", GABRIELE, {}, "2d", False),
        ("Lorenzo default", LORENZO, dict(DEFAULT_PARAMS), (), False),
        ("Lorenzo searched", LORENZO, dict(DEFAULT_PARAMS), LORENZO_DIMS, False),
        # is it the strategy or the BTC filter? the same filter on Lorenzo
        ("Lorenzo default +BTC", LORENZO, dict(DEFAULT_PARAMS), (), "btc"),
    )
GABRIELE2 = "Gabriele 2 (RSI+BB long/short)"
# Lorenzo, 15/10: "il filtro BTC [...] testalo su tutto". SET=btc: every site
# strategy of the timeframe with and without it. "ls" filters = the site's
# long/short version (no long-only stripping); "ls_btc" blocks only the longs.
if os.environ.get("SET") == "btc":
    _L = dict(DEFAULT_PARAMS)
    if TF == "4h":
        VARIANTS = (
            ("RSI+BB 4H", RSI_BB_4H, {}, None, False),
            ("RSI+BB 4H +BTC", RSI_BB_4H, {}, None, "btc"),
            ("Lorenzo default", LORENZO, _L, (), False),
            ("Lorenzo default +BTC", LORENZO, _L, (), "btc"),
            ("Lorenzo searched", LORENZO, _L, LORENZO_DIMS, False),
            ("Lorenzo searched +BTC", LORENZO, _L, LORENZO_DIMS, "btc"),
            ("Lorenzo L/S", LORENZO, _L, (), "ls_raw"),
            ("Lorenzo L/S +BTC", LORENZO, _L, (), "ls_btc"),
        )
    else:
        VARIANTS = (
            ("RSI+BB reversal", GABRIELE, {}, "2d", False),
            ("RSI+BB reversal +BTC", GABRIELE, {}, "2d", "btc"),
            ("Gabriele 2 L/S", GABRIELE2, {}, "2d", "ls_raw"),
            ("Gabriele 2 L/S +BTC", GABRIELE2, {}, "2d", "ls_btc"),
            ("Lorenzo default", LORENZO, _L, (), False),
            ("Lorenzo default +BTC", LORENZO, _L, (), "btc"),
            ("Lorenzo searched", LORENZO, _L, LORENZO_DIMS, False),
            ("Lorenzo searched +BTC", LORENZO, _L, LORENZO_DIMS, "btc"),
            ("Lorenzo L/S", LORENZO, _L, (), "ls_raw"),
            ("Lorenzo L/S +BTC", LORENZO, _L, (), "ls_btc"),
        )
LONG_ONLY = {LORENZO}
BTC_UP: pd.Series | None = None   # BTC's previous daily close above its EMA 200
SHORT = {"Claudio Trend 4H": "CT", "Claudio Trend default": "CTd", "RSI+BB 4H": "R", "Claudio 4H": "C", "Lorenzo default": "Ld", "Lorenzo searched": "Ls"}
SHORT.update({f"{k} +EMA200d": f"{v}f" for k, v in list(SHORT.items())})
SHORT["Lorenzo default L/S regime"] = "Lrs"
SHORT.update({"Claudio 1D": "C1", "Claudio 1D +BTC": "C1b",
              "RSI+BB reversal": "G", "Lorenzo default +BTC": "Ldb"})
SHORT.update({"RSI+BB 4H +BTC": "Rb", "Lorenzo searched +BTC": "Lsb", "Lorenzo L/S": "LS",
              "Lorenzo L/S +BTC": "LSb", "RSI+BB reversal +BTC": "Gb", "Gabriele 2 L/S": "G2",
              "Gabriele 2 L/S +BTC": "G2b"})
TREND: pd.Series | None = None   # close above the daily EMA 200, set per pair


def daily_trend(df):
    """True on a 4h candle when the PREVIOUS day closed above its EMA 200:
    known before the candle opens, so no look-ahead."""
    day = df["close"].resample("1D").last().dropna()
    up = (day > day.ewm(span=200, adjust=False, min_periods=200).mean()).shift(1)
    return up.reindex(df.index, method="ffill").fillna(False).astype(bool)
SHOWN = ("c1_ema", "c1_pb", "c1_atr", "ct_len", "ct_atr", "ct_ema_days", "rsi_oversold", "rsi_overbought", "bb_mult", "cl_rsi_os", "cl_bb_mult", "cl_atr_stop",
         "len", "slopeFlen", "slopeSlen")


def _binance_month(symbol, y, m):
    url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/{TF}/{symbol}-{TF}-{y}-{m:02d}.zip"
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
    for y in range(2020 if TF == "4h" else 2018, now.year + 1):
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
    if old is not None and len(old) >= (3000 if TF == "4h" else 900):
        try:
            tail = await MexcProvider().fetch_ohlcv(symbol, TF, 400)
            old = pd.concat([old, tail[tail.index > old.index[-1]][old.columns]])
        except Exception:  # noqa: BLE001 — the archive alone, up to last month
            pass
        return "binance+mexc", old
    best, last = None, None
    for name, prov in (("kucoin", KucoinProvider()), ("mexc", MexcProvider())):
        try:
            df = await prov.fetch_ohlcv(symbol, TF, 20000)
            if best is None or len(df) > len(best[1]):
                best = (name, df)
        except Exception as exc:  # noqa: BLE001
            last = exc
    if best is None or len(best[1]) < (3000 if TF == "4h" else 900):
        raise RuntimeError(f"{symbol}: not enough candles ({last})")
    return best


async def rank(symbol: str) -> int | None:
    try:
        from app import market_rank
        return market_rank.rank_for(symbol, await market_rank.ranks())
    except Exception:  # noqa: BLE001
        return None


def signals(df, strategy, params, filt=False):
    sig = STRATEGY_REGISTRY[strategy](df, params).copy()
    if filt in ("ls_raw", "ls_btc"):      # the site's long/short version
        if filt == "ls_btc":
            sig["entry_long"] = sig["entry_long"] & BTC_UP.reindex(
                sig.index, method="ffill").fillna(False).to_numpy().astype(bool)
        return sig
    trend = BTC_UP if filt == "btc" else TREND
    up = trend.reindex(sig.index, method="ffill").fillna(False).to_numpy().astype(bool) if filt else None
    if filt == "ls":              # both sides, each only on its side of the regime
        sig["entry_long"] = sig["entry_long"] & up
        sig["entry_short"] = sig["entry_short"] & ~up
        return sig
    if filt:
        sig["entry_long"] = sig["entry_long"] & up
    if strategy in LONG_ONLY:
        sig["entry_short"] = False
        sig["exit_short"] = False
    return sig


def test_on(df, strategy, params, t0, t1, filt=False):
    start = max(0, df.index.searchsorted(t0) - WARMUP)
    frame = df[(df.index < t1)].iloc[start:]
    sig = signals(frame, strategy, params, filt)
    sig.loc[sig.index < t0, :] = False
    # 15/10: a trade still open on the last candle of the year was not
    # counted (the backtest only books closed trades), so a long bought in a
    # 2022 dip and never sold read as 0%. Close everything on the
    # second-last candle: a signal on the very last one is not confirmed yet
    # (confirmed_events) and never fills.
    sig.loc[sig.index[-2]:, ["entry_long", "entry_short"]] = False
    sig.loc[sig.index[-2], ["exit_long", "exit_short"]] = True
    return run_backtest(frame, params, BP, signals=sig, strategy_name=strategy)


def annual(ret, days):
    yrs = max(days / 365.25, 0.01)
    return ((1 + ret / 100) ** (1 / yrs) - 1) * 100 if ret > -100 else -100.0


def run_pair(symbol, df):
    global TREND
    TREND = daily_trend(df)
    tz = df.index.tz
    train = df[df.index >= TRAIN_FROM]
    years = list(range(train.index[0].year + 1, train.index[-1].year))   # first and last not judged
    tests = []
    for y in TEST_YEARS:
        t0, t1 = pd.Timestamp(year=y, month=1, day=1, tz=tz), pd.Timestamp(year=y + 1, month=1, day=1, tz=tz)
        if df.index[0] <= t0 - pd.Timedelta(days=60) and t1 <= TRAIN_FROM:
            seg = df[(df.index >= t0) & (df.index < t1)]
            tests.append((y, t0, t1, round((seg["close"].iloc[-1] / seg["close"].iloc[0] - 1) * 100, 1)))
    res = {"symbol": symbol, "since": f"{df.index[0]:%Y-%m}", "train_years": years,
           "hold": {str(y): h for y, _, _, h in tests}, "variants": {}}
    train_days = (train.index[-1] - train.index[0]).days
    for name, strat, fixed, dims, filt in VARIANTS:
        t = time.time()

        def bt(p, strat=strat, filt=filt):
            return run_backtest(train, p, BP, signals=signals(train, strat, p, filt), strategy_name=strat)
        try:
            if dims == ():
                n, picks = 1, [{"kind": "default", "params": fixed, "backtest": bt(fixed), "solidity": None}]
            elif dims == "2d":
                _, _, n, picks = max_return_search(strat, bt, years=years)
                picks = [{**c, "kind": f"top{c['rank']}", "solidity": None} for c in picks]
            elif dims is None:
                _, _, n, picks = max_return_search_3d(strat, bt, years=years)
            else:
                _, _, n, picks = max_return_search_nd(strat, bt, dims=dims, fixed=fixed, years=years)
        except ValueError as exc:
            res["variants"][name] = {"error": str(exc)[:80]}
            continue
        row = {"n": n, "s": round(time.time() - t)}
        for c in picks:
            pick = {"train_y": round(annual(c["backtest"].total_return_pct, train_days), 1),
                    "train_tr": c["backtest"].num_trades, "sol": c["solidity"],
                    "p": {k: v for k, v in c["params"].items() if k in SHOWN}}
            for y, t0, t1, _ in tests:
                tb = test_on(df, strat, c["params"], t0, t1, filt)
                pick[str(y)] = {"ret": round(tb.total_return_pct, 1), "tr": tb.num_trades,
                                "dd": round(tb.max_drawdown_pct, 1)}
            row[c["kind"]] = pick
        res["variants"][name] = row
        print(json.dumps({name: row}), flush=True)
    return res


def solid(row):
    return row.get("solid") or row.get("solid+profitable") or row.get("default") or row.get("top1")


def line(res):
    hold = " ".join(f"{y} {h:+.0f}%" for y, h in res["hold"].items())
    bits = [f"{res['symbol']} #{res.get('rank') or '?'} since {res['since']} · B&H {hold}"]
    for name, *_ in VARIANTS:
        r = res["variants"].get(name, {})
        s = solid(r) if "error" not in r else None
        if not s:
            bits.append(f"{SHORT[name]} none")
            continue
        cells = " ".join(f"{y} {s[y]['ret']:+.0f}% ({s[y]['tr']}tr)" for y in res["hold"])
        p = ",".join(f"{v}" for v in s["p"].values())
        bits.append(f"{SHORT[name]} [{p}] train {s['train_y']:+.0f}%/y · {cells}")
    return " | ".join(bits)


async def main():
    global BTC_UP
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        src, df = await candles(sym)
        btc = df if sym == "BTCUSDT" else (await candles("BTCUSDT"))[1]
        BTC_UP = daily_trend(btc)
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
