"""The test environment for 1H trend strategies (Lorenzo, 24/10: "analizzare
[...] i parametri per la creazione della miglior strategia sul time frame
un'ora [...] che sarebbe bene funzionasse in tutte le condizioni di mercato
[...] sfruttando l'andamento del trend [...] testarla in anni decisivi [...]
2021, fortissimo rialzo [...] e 2022 fase di grandi ribassi", then "Crea un
ambiente di test sul nostro GitHub").

Candidate families, from what GitHub (freqtrade Supertrend / SuperTrendADX /
abeille, all 1h) and TradingView publish for crypto on the hour:
  ST  SuperTrend flip, ADX floor at entry          (atr_len, mult, adx_min)
  DC  Donchian breakout, Chandelier trailing exit   (n, k)
  EX  EMA cross, optional ATR trailing exit         (fast, slow, k)
  LZ  the site's Lorenzo trend follower on 1h       (len, slopeFlen, slopeSlen)
each long only (L) or long/short (LS), and with no regime, the pair's own
daily EMA 200 (d200) or BTC's (btc) — previous day's close, known before the
hour opens. With a regime, longs only above it and shorts only below.

Every cell of every grid runs ONCE on the whole history (Binance's public
archive from 2020) with the site's engine and costs; the trades are then
split by entry year. Nothing is chosen here: the per-pair JSON goes to the
summary job (scripts/research_1h_summary.py), which chooses on the candles
from TRAIN_FROM (2023) only and reads 2021 and 2022 as never seen — the rule
of the 4H/1D environments (Lorenzo, 15/10: "lascerei in questo ambiente di
test sempre 2021 e 2022 come anni di candele mai viste").

    cd backend && PAIR=BTCUSDT PYTHONPATH=. python ../scripts/research_1h.py
"""
from __future__ import annotations

import gzip
import io
import itertools
import json
import os
import sys
import time
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.strategies import DEFAULT_PARAMS, STRATEGY_REGISTRY

TF = "1h"
START_YEAR = 2020
# the site's position for the environments: whole equity, real costs
BP = {"initial_capital": 1000.0, "qty_pct_of_equity": 100.0, "commission_pct": 0.06,
      "slippage_pct": 0.02, "fill_at": "signal_close"}
LORENZO = "Lorenzo (trend-follower)"

GRIDS = {
    "ST": (("atr_len", [7, 10, 14, 21]),
           ("mult", [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]),
           ("adx_min", [0, 15, 20, 25, 30])),
    "DC": (("n", [12, 24, 48, 72, 120, 168, 240, 336]),
           ("k", [2.0, 3.0, 4.0, 5.0, 6.0, 8.0])),
    "EX": (("fast", [8, 13, 21, 34, 55]),
           ("slow", [89, 144, 200, 300, 500]),
           ("k", [0.0, 3.0, 5.0, 8.0])),
    "LZ": (("len", [40, 80, 130, 200, 300]),
           ("slopeFlen", [3, 7, 11, 15]),
           ("slopeSlen", [15, 27, 45, 75])),
}
# GRIDSET=v2 (24/10, after the first run: most picks sat on an edge of the
# grids above — EMA 8/89, Lorenzo 300/15/75, trailing 8 ATR): the grids
# moved past those edges, and two more BTC regimes — the site's own weekly
# EMA 21 (btc_regime.py) — each also with "x": the position is closed when
# the regime turns against it.
if os.environ.get("GRIDSET") == "v2":
    GRIDS = {
        "ST": (("atr_len", [7, 14, 21, 30]),
               ("mult", [3.0, 4.0, 5.0, 6.0, 8.0, 10.0]),
               ("adx_min", [0, 20, 30, 35, 40])),
        "DC": (("n", [120, 240, 336, 480, 720]),
               ("k", [6.0, 8.0, 10.0, 12.0, 16.0])),
        "EX": (("fast", [3, 5, 8, 13, 21]),
               ("slow", [34, 55, 89, 144, 200]),
               ("k", [0.0, 6.0, 8.0, 12.0, 16.0])),
        "LZ": (("len", [200, 300, 400, 500, 700]),
               ("slopeFlen", [11, 15, 21, 30]),
               ("slopeSlen", [45, 75, 100, 150])),
    }
MODES = tuple(os.environ.get("MODES", "L,LS").split(","))
REGIMES = tuple(os.environ.get("REGIMES", "none,d200,btc").split(","))


# ── candles ─────────────────────────────────────────────────────────────────
def _binance_month(symbol, y, m):
    url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/{TF}/{symbol}-{TF}-{y}-{m:02d}.zip"
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
    except Exception:  # noqa: BLE001 — not listed that month
        return []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    return [r.split(",") for r in text.splitlines() if r and r[0].isdigit()]


def binance(symbol: str) -> pd.DataFrame:
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for y in range(START_YEAR, now.year + 1):
        for m in range(1, 13):
            if (y, m) >= (now.year, now.month):
                break
            rows += _binance_month(symbol, y, m)
    if not rows:
        raise RuntimeError(f"{symbol}: nothing in the archive")
    ts = pd.Series([int(r[0]) for r in rows])
    ts = ts.where(ts < 10**14, ts // 1000)          # 2025 on: microseconds
    df = pd.DataFrame({k: [float(r[i]) for r in rows] for i, k in
                       enumerate(("open", "high", "low", "close", "volume"), 1)},
                      index=pd.to_datetime(ts.to_numpy(), unit="ms", utc=True))
    return df[~df.index.duplicated()].sort_index()


def daily_up(df: pd.DataFrame, idx: pd.DatetimeIndex) -> np.ndarray:
    """1 / -1 on an hour when the PREVIOUS day closed above / below its EMA
    200, 0 while the EMA is warming up: known before the hour opens."""
    day = df["close"].resample("1D").last().dropna()
    ema = day.ewm(span=200, adjust=False, min_periods=200).mean()
    side = np.sign(day - ema).where(ema.notna(), 0.0).shift(1, freq="D")
    return side.reindex(idx, method="ffill").fillna(0.0).to_numpy()


def weekly_up(btc: pd.DataFrame, idx: pd.DatetimeIndex) -> np.ndarray:
    """The site's BTC filter (btc_regime.py): last CLOSED weekly close vs its
    EMA 21, from the Monday after the Sunday close. 1 / -1, 0 warming up."""
    day = btc["close"].resample("1D").last().dropna()
    week = day.resample("W-SUN").last().dropna()
    ema = week.ewm(span=21, adjust=False, min_periods=21).mean()
    side = np.sign(week - ema).where(ema.notna(), 0.0).shift(1, freq="D")
    return side.reindex(idx, method="ffill").fillna(0.0).to_numpy()


# ── indicators ──────────────────────────────────────────────────────────────
def _rma(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False).mean()


def true_range(df):
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df, n):
    return _rma(true_range(df), n)


def adx(df, n=14):
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = _rma(true_range(df), n)
    pdi, mdi = 100 * _rma(plus, n) / tr, 100 * _rma(minus, n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return _rma(dx.fillna(0), n)


def supertrend_dir(df, n, mult):
    """1 / -1, the classic SuperTrend (hl2 ± mult·ATR, bands that only
    tighten, flip on a close through the band) — the freqtrade one."""
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    a = atr(df, n).to_numpy()
    c = df["close"].to_numpy()
    ub, lb = hl2 + mult * a, hl2 - mult * a
    out = np.ones(len(c), dtype=np.int8)
    fu, fl, d = ub[0], lb[0], 1
    for i in range(1, len(c)):
        fl = lb[i] if (lb[i] > fl or c[i - 1] < fl) else fl
        fu = ub[i] if (ub[i] < fu or c[i - 1] > fu) else fu
        d = (-1 if c[i] < fl else 1) if d == 1 else (1 if c[i] > fu else -1)
        out[i] = d
    return out


# ── strategies: the wanted position on every hour (1 / 0 / -1) ─────────────
class Pair:
    """Indicator cache for one pair: every grid reuses the same arrays."""

    def __init__(self, df, regimes):
        self.df, self.regimes, self._c = df, regimes, {}
        self.close = df["close"].to_numpy()
        self.high = df["high"].to_numpy()
        self.low = df["low"].to_numpy()

    def get(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]


def _allowed(reg, i, side):
    return reg is None or reg[i] == side


def _against(rx, reg, i, pos):
    """'x' regimes: the regime no longer on the position's side."""
    return rx and pos != 0 and reg[i] != pos


def want_st(P, p, ls, reg, rx=False):
    d = P.get(("st", p["atr_len"], p["mult"]), lambda: supertrend_dir(P.df, p["atr_len"], p["mult"]))
    ax = P.get(("adx", 14), lambda: adx(P.df, 14).to_numpy())
    floor = p["adx_min"]
    n = len(d)
    w = np.zeros(n, dtype=np.int8)
    pos = 0
    for i in range(30, n):
        if pos == 1 and d[i] == -1:
            pos = 0
        elif pos == -1 and d[i] == 1:
            pos = 0
        if _against(rx, reg, i, pos):
            pos = 0
        if pos == 0 and ax[i] >= floor:
            if d[i] == 1 and _allowed(reg, i, 1) and not (i > 0 and w[i - 1] == 1):
                pos = 1
            elif ls and d[i] == -1 and _allowed(reg, i, -1) and not (i > 0 and w[i - 1] == -1):
                pos = -1
        w[i] = pos
    return w


def want_dc(P, p, ls, reg, rx=False):
    n_, k = p["n"], p["k"]
    hh = P.get(("hh", n_), lambda: P.df["high"].rolling(n_).max().shift(1).to_numpy())
    ll = P.get(("ll", n_), lambda: P.df["low"].rolling(n_).min().shift(1).to_numpy())
    a = P.get(("atr", 22), lambda: atr(P.df, 22).to_numpy())
    c, h, lo = P.close, P.high, P.low
    w = np.zeros(len(c), dtype=np.int8)
    pos, ext = 0, 0.0
    for i in range(n_ + 1, len(c)):
        if pos == 1:
            ext = max(ext, h[i])
            if c[i] < ext - k * a[i]:
                pos = 0
        elif pos == -1:
            ext = min(ext, lo[i])
            if c[i] > ext + k * a[i]:
                pos = 0
        if _against(rx, reg, i, pos):
            pos = 0
        if pos == 0:
            if c[i] > hh[i] and _allowed(reg, i, 1):
                pos, ext = 1, h[i]
            elif ls and c[i] < ll[i] and _allowed(reg, i, -1):
                pos, ext = -1, lo[i]
        w[i] = pos
    return w


def want_ex(P, p, ls, reg, rx=False):
    f = P.get(("ema", p["fast"]), lambda: P.df["close"].ewm(span=p["fast"], adjust=False).mean().to_numpy())
    s = P.get(("ema", p["slow"]), lambda: P.df["close"].ewm(span=p["slow"], adjust=False).mean().to_numpy())
    a = P.get(("atr", 22), lambda: atr(P.df, 22).to_numpy())
    k = p["k"]
    c, h, lo = P.close, P.high, P.low
    w = np.zeros(len(c), dtype=np.int8)
    pos, ext, armed = 0, 0.0, 0     # armed: the side of the last cross not yet traded
    for i in range(p["slow"], len(c)):
        up = f[i] > s[i]
        if up != (f[i - 1] > s[i - 1]):
            armed = 1 if up else -1
            if pos and pos != armed:
                pos = 0
        if pos == 1 and k:
            ext = max(ext, h[i])
            if c[i] < ext - k * a[i]:
                pos = 0
        elif pos == -1 and k:
            ext = min(ext, lo[i])
            if c[i] > ext + k * a[i]:
                pos = 0
        if _against(rx, reg, i, pos):
            pos = 0
        if pos == 0 and armed:
            if armed == 1 and _allowed(reg, i, 1):
                pos, ext, armed = 1, h[i], 0
            elif armed == -1 and ls and _allowed(reg, i, -1):
                pos, ext, armed = -1, lo[i], 0
        w[i] = pos
    return w


def want_lz(P, p, ls, reg, rx=False):
    params = {**DEFAULT_PARAMS, **p}
    sig = STRATEGY_REGISTRY[LORENZO](P.df, params)
    el, es = sig["entry_long"].to_numpy(bool), sig["entry_short"].to_numpy(bool)
    xl, xs = sig["exit_long"].to_numpy(bool), sig["exit_short"].to_numpy(bool)
    w = np.full(len(el), np.nan)
    w[0] = 0
    pos = 0
    flips = np.zeros(len(el), dtype=bool)
    if rx:
        flips[1:] = reg[1:] != reg[:-1]
    for i in np.flatnonzero(el | es | xl | xs | flips):
        if _against(rx, reg, i, pos):
            pos = 0
        if pos == 1 and (xl[i] or es[i]):
            pos = 0
        elif pos == -1 and (xs[i] or el[i]):
            pos = 0
        if pos == 0:
            if el[i] and _allowed(reg, i, 1):
                pos = 1
            elif ls and es[i] and _allowed(reg, i, -1):
                pos = -1
        w[i] = pos
    return pd.Series(w).ffill().to_numpy().astype(np.int8)


WANT = {"ST": want_st, "DC": want_dc, "EX": want_ex, "LZ": want_lz}


def signals_from(want: np.ndarray, idx) -> pd.DataFrame:
    prev = np.concatenate([[0], want[:-1]])
    ch = want != prev
    return pd.DataFrame({
        "entry_long": ch & (want == 1),
        "entry_short": ch & (want == -1),
        "exit_long": ch & (prev == 1) & (want == 0),
        "exit_short": ch & (prev == -1) & (want == 0),
    }, index=idx)


def by_year(bt, years):
    """Per entry year: simple return (sum of trade %), trades, and the
    drawdown of the compounded trade path inside that year."""
    out = {y: [0.0, 0, 0.0] for y in years}
    eq = {y: [1.0, 1.0] for y in years}       # equity, peak
    for t in bt.trades:
        ts = t.entry_time // 1000 if t.entry_time > 10**11 else t.entry_time
        y = pd.Timestamp(ts, unit="s", tz="UTC").year
        if y not in out:
            continue
        out[y][0] += t.pnl_pct
        out[y][1] += 1
        e = eq[y]
        e[0] *= 1 + t.pnl_pct / 100
        e[1] = max(e[1], e[0])
        out[y][2] = max(out[y][2], (1 - e[0] / e[1]) * 100)
    return {str(y): [round(v[0], 1), v[1], round(v[2], 1)] for y, v in out.items()}


def run_pair(symbol: str, df: pd.DataFrame, btc: pd.DataFrame) -> dict:
    idx = df.index
    regimes = {"none": None, "d200": daily_up(df, idx), "btc": daily_up(btc, idx),
               "w21": weekly_up(btc, idx)}
    P = Pair(df, regimes)
    years = list(range(max(START_YEAR + 1, idx[0].year), idx[-1].year + 1))
    hold = {}
    for y in years:
        seg = df[df.index.year == y]["close"]
        if len(seg) > 24 * 30:
            hold[str(y)] = round((seg.iloc[-1] / seg.iloc[0] - 1) * 100, 1)
    res = {"symbol": symbol, "since": f"{idx[0]:%Y-%m}", "hold": hold, "cells": {}}
    t0 = time.time()
    for fam, dims in GRIDS.items():
        names = [d[0] for d in dims]
        for combo in itertools.product(*[d[1] for d in dims]):
            p = dict(zip(names, combo))
            if fam == "EX" and p["fast"] >= p["slow"]:
                continue
            for mode in MODES:
                for rg in REGIMES:
                    x = rg.endswith("x")
                    w = WANT[fam](P, p, mode == "LS", regimes[rg[:-1] if x else rg], x)
                    bt = run_backtest(df, p, BP, signals=signals_from(w, idx), strategy_name=LORENZO)
                    key = f"{fam}|{mode}|{rg}|" + ",".join(str(v) for v in combo)
                    res["cells"][key] = by_year(bt, years)
        print(f"{symbol} {fam}: {len(res['cells'])} cells, {time.time() - t0:.0f}s", flush=True)
    return res


def main() -> int:
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        df = binance(sym)
        btc = df if sym == "BTCUSDT" else binance("BTCUSDT")
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={sym}::{exc}")
        return 0
    if os.environ.get("SAVE_CANDLES"):
        os.makedirs("candles", exist_ok=True)
        df.to_csv(f"candles/{sym}-1h.csv.gz", compression="gzip")
    res = run_pair(sym, df, btc)
    with gzip.open(f"r1h-{sym}.json.gz", "wt") as fh:
        json.dump(res, fh)
    print(f"{sym}: {len(df)} candles since {res['since']}, B&H {res['hold']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
