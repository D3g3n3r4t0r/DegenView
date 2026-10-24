"""Public 1H trend strategies, ported as their authors wrote them (Lorenzo,
24/10: "L'obiettivo pero' era quello di trovare nuove fonti per la strategia
1h sui GitHub pubblici degli utenti e sulle strategie pubbliche di
TradingView").

Sources (every rule and default value below is the author's):
  TradingView, open-source scripts (Pine, mirrored in
  github.com/hasnocool/tradingview-pine-scripts):
    AT     AlphaTrend Strategy (only_fibonacci, indicator by KivancOzbilgic)
    OTT    Optimized Trend Tracker (Anil Ozeksi / KivancOzbilgic; strategy by
           melihtuna — its "src instead of 0" typo in the CMO is not kept)
    PMAX   Profit Maximizer PMax Strategy Long-Short (melihtuna)
    CEZ    Chandelier Exit ZLSMA Strategy
    HULL   Hull Suite Strategy (HMA 55, "55 for swing entry")
    TURTLE Noro's Turtles Strategy (20/10 and 55/20, long only by default)
    UTBOT  Strategy for UT Bot Alerts indicator (key 3, ATR 1, EMA 200 trend)
    RF     Range Filter B&S Signals (20, 3.5, EMA 200; its 1% SL/TP left out:
           that is scalping, not trend)
    TRF    Twin Range Filter Algo (colinmck, 27/1.6 + 55/2)
    CRUNCH Crunchster's Normalised Trend Strategy (HMA 100 of normalised
           price, 1 ATR hard stop)
    DST    Dual-Supertrend with MACD [presentTrading] (10/3, 20/5, 12/26/9)
  GitHub:
    FST    freqtrade/freqtrade-strategies Supertrend.py (3+3 SuperTrends,
           hyperopted by its author on 1h from 2021; ROI table, -26.5% SL)
    STADX  SuperTrendADX.py (assinscreedFC/trading_strategie; ST 10x3, ADX>25,
           EMA 200, out on flip or ADX<20; -6% SL, 2% trail after +3%)
    ADXSMA freqtrade-strategies FAdxSmaStrategy.py (ADX>30, SMA 12/48 cross,
           out when ADX<30; -5% SL, 7.5% ROI)
    DEMA   paulcpk DoubleEMACrossoverWithTrend.py (EMA 9/21 over EMA 200)
    MACDT  paulcpk MACDCrossoverWithTrend.py (MACD cross under 0, EMA 100)
    JTURT  jesse-ai/example-strategies TurtleRules (20/10, 2 ATR stop)
    RIBBON EternaHybridExchange/tradingview-strategies ema-ribbon (9/21/55)

Every strategy gets the author's values (s=1, w=1) and, to see whether a
script written for another chart holds on the hour, two scale factors:
s on every length, w on every band width / multiplier. Same modes, regimes,
engine, costs and per-year output as research_1h.py, so the same summary
(research_1h_summary.py) reads both.

    cd backend && PAIR=BTCUSDT PYTHONPATH=. python ../scripts/public_1h.py
"""
from __future__ import annotations

import gzip
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import research_1h as R  # noqa: E402

from app.analysis.backtest import run_backtest  # noqa: E402

S_GRID = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
W_GRID = [0.5, 0.75, 1.0, 1.5, 2.0]
# GRIDSET=v3 (24/10, long only — Lorenzo: "la strategia deve essere solo long
# piu' uscita, quindi reversal"): finer grids on the four best long-only
# scripts of the first run, past the edges they picked (AlphaTrend took the
# smallest multiplier). AlphaTrend: period 7-21, multiplier 0.2-1.0.
GRIDS_V3 = {
    "AT": ([7 / 14, 8 / 14, 10 / 14, 12 / 14, 1.0, 17 / 14, 21 / 14], [0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0]),
    "ATRSI": ([7 / 14, 8 / 14, 10 / 14, 12 / 14, 1.0, 17 / 14, 21 / 14], [0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0]),
    "OTT": ([0.5, 1.0, 1.5, 2.0, 3.0], [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]),
    "HULL": ([1.0, 1.5, 2.0, 2.5, 3.0, 4.0], [1.0]),
    "STADX": ([0.75, 1.0, 1.5, 2.0, 3.0], [1.0, 1.5, 2.0, 2.5, 3.0]),
}
MODES = tuple(os.environ.get("MODES", "L,LS").split(","))
REGIMES = tuple(os.environ.get("REGIMES", "none,btc,w21").split(","))
ONLY = [x for x in os.environ.get("ONLY", "").split(",") if x]


# ── indicators ──────────────────────────────────────────────────────────────
def L(n, s):
    return max(1, int(round(n * s)))


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def wma(x, n):
    x = np.asarray(x, dtype=float)
    k = np.arange(n, 0, -1, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        v = np.convolve(np.nan_to_num(x), k, "valid") / k.sum()
        out[n - 1:] = v
        bad = pd.Series(np.isnan(x)).rolling(n).max().to_numpy() > 0
        out[bad] = np.nan
    return out


def hma(x, n):
    return wma(2 * wma(x, max(1, n // 2)) - wma(x, n), max(1, int(round(math.sqrt(n)))))


def linreg(x, n):
    """ta.linreg(x, n, 0): the regression line's value on the last bar."""
    x = pd.Series(x)
    t = np.arange(n, dtype=float)
    tm, tv = t.mean(), ((t - t.mean()) ** 2).sum()

    def f(w):
        b = ((t - tm) * (w - w.mean())).sum() / tv
        return w.mean() + b * (n - 1 - tm)
    return x.rolling(n).apply(f, raw=True).to_numpy()


def tr(df):
    return R.true_range(df).to_numpy()


def mfi(df, n):
    tp = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy()
    mf = tp * df["volume"].to_numpy()
    up = np.where(np.diff(tp, prepend=np.nan) > 0, mf, 0.0)
    dn = np.where(np.diff(tp, prepend=np.nan) < 0, mf, 0.0)
    su, sd = sma(up, n) * n, sma(dn, n) * n
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, 100 - 100 / (1 + su / sd), 100.0)


def var_ma(src, n):
    """VIDYA with the 9-bar CMO (Kivanc's VAR, used by OTT and PMax)."""
    d = np.diff(src, prepend=src[0])
    ud = pd.Series(np.where(d > 0, d, 0.0)).rolling(9).sum().to_numpy()
    dd = pd.Series(np.where(d < 0, -d, 0.0)).rolling(9).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.abs(np.nan_to_num((ud - dd) / (ud + dd)))
    a = 2 / (n + 1)
    out = np.zeros(len(src))
    v = 0.0
    for i in range(len(src)):
        v = a * k[i] * src[i] + (1 - a * k[i]) * v
        out[i] = v
    return out


def trail_dir(ma, band_lo, band_hi):
    """The PMax/OTT stop: bands that only tighten, direction on the MA."""
    n = len(ma)
    stop = np.zeros(n)
    d = np.ones(n, dtype=np.int8)
    ls, ss, dr = band_lo[0], band_hi[0], 1
    for i in range(n):
        lsp, ssp = ls, ss
        ls = max(band_lo[i], lsp) if ma[i] > lsp else band_lo[i]
        ss = min(band_hi[i], ssp) if ma[i] < ssp else band_hi[i]
        dr = 1 if (dr == -1 and ma[i] > ssp) else (-1 if (dr == 1 and ma[i] < lsp) else dr)
        d[i] = dr
        stop[i] = ls if dr == 1 else ss
    return stop, d


def cross_up(a, b):
    a, b = np.asarray(a), np.asarray(b)
    out = np.zeros(len(a), dtype=bool)
    out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return out


def cross_dn(a, b):
    return cross_up(b, a)


def shift(x, k):
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    return out


def range_filter(src, r):
    out = np.zeros(len(src))
    f = src[0]
    for i in range(len(src)):
        ri = r[i] if np.isfinite(r[i]) else 0.0
        if src[i] > f:
            f = f if src[i] - ri < f else src[i] - ri
        else:
            f = f if src[i] + ri > f else src[i] + ri
        out[i] = f
    return out


def smooth_rng(src, t, m):
    return ema(ema(np.abs(np.diff(src, prepend=src[0])), t), t * 2 - 1) * m


def rf_signals(src, filt):
    up = np.zeros(len(src))
    dn = np.zeros(len(src))
    for i in range(1, len(src)):
        up[i] = up[i - 1] + 1 if filt[i] > filt[i - 1] else (0 if filt[i] < filt[i - 1] else up[i - 1])
        dn[i] = dn[i - 1] + 1 if filt[i] < filt[i - 1] else (0 if filt[i] > filt[i - 1] else dn[i - 1])
    lc = (src > filt) & (up > 0)
    sc = (src < filt) & (dn > 0)
    ini = np.zeros(len(src), dtype=np.int8)
    c = 0
    for i in range(len(src)):
        c = 1 if lc[i] else (-1 if sc[i] else c)
        ini[i] = c
    prev = np.concatenate([[0], ini[:-1]])
    return lc & (prev == -1), sc & (prev == 1)


# ── strategies: raw signals + the author's risk rules ───────────────────────
# Each returns (entry_long, exit_long, entry_short, exit_short, risk). An
# entry on one side also closes the other (TradingView's strategy.entry).
def rsi(c, n):
    d = np.diff(c, prepend=c[0])
    up, dn = rma(np.where(d > 0, d, 0.0), n), rma(np.where(d < 0, -d, 0.0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(dn > 0, 100 - 100 / (1 + up / dn), 100.0)


def s_at(df, s, w, use_rsi=False):
    """use_rsi: the script's own "no volume data" switch (RSI >= 50 instead
    of MFI >= 50) — volumes differ from one exchange to the next."""
    ap, coeff = L(14, s), 1.0 * w
    a = sma(tr(df), ap)
    up_t = df["low"].to_numpy() - a * coeff
    dn_t = df["high"].to_numpy() + a * coeff
    m = (rsi(df["close"].to_numpy(), ap) if use_rsi else mfi(df, ap)) >= 50
    at = np.zeros(len(a))
    prev = 0.0
    for i in range(len(a)):
        if not np.isfinite(a[i]):
            at[i] = prev
            continue
        prev = (prev if up_t[i] < prev else up_t[i]) if m[i] else (prev if dn_t[i] > prev else dn_t[i])
        at[i] = prev
    at2 = shift(at, 2)
    buy, sell = cross_up(at, at2), cross_dn(at, at2)
    # O1 > K2: signals alternate — a buy only after a sell, and back
    el, es = np.zeros(len(a), bool), np.zeros(len(a), bool)
    last = 0
    for i in range(len(a)):
        if buy[i] and last != 1:
            el[i], last = True, 1
        elif sell[i] and last != -1:
            es[i], last = True, -1
    return el, es, es, el, {}


def s_ott(df, s, w):
    pds, pct = L(2, s), 1.4 * w
    src = df["close"].to_numpy()
    v = var_ma(src, pds)
    fark = v * pct * 0.01
    mt, _ = trail_dir(v, v - fark, v + fark)
    ott = np.where(v > mt, mt * (200 + pct) / 200, mt * (200 - pct) / 200)
    o2 = shift(ott, 2)
    b, sl = cross_up(v, o2), cross_dn(v, o2)
    return b, sl, sl, b, {}


def s_pmax(df, s, w):
    n, mult = L(10, s), 3.0 * w
    src = ((df["high"] + df["low"]) / 2).to_numpy()
    a = rma(tr(df), n)
    ma = ema(src, n)
    pm, _ = trail_dir(ma, ma - mult * a, ma + mult * a)
    b, sl = cross_up(ma, pm), cross_dn(ma, pm)
    return b, sl, sl, b, {}


def s_cez(df, s, w):
    mult, zl = 2.0 * w, L(50, s)
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ha = shift((o + h + lo + c) / 4, 1)
    a = mult * shift(tr(df), 1)            # ta.atr(1)[1]
    n = len(c)
    d = np.ones(n, dtype=np.int8)
    ls = ss = np.nan
    dr = 1
    for i in range(n):
        if not (np.isfinite(ha[i]) and np.isfinite(a[i])):
            continue
        lsp = ls if np.isfinite(ls) else ha[i] - a[i]
        ssp = ss if np.isfinite(ss) else ha[i] + a[i]
        ls = max(ha[i] - a[i], lsp) if ha[i] > lsp else ha[i] - a[i]
        ss = min(ha[i] + a[i], ssp) if ha[i] < ssp else ha[i] + a[i]
        dr = 1 if ha[i] > ssp else (-1 if ha[i] < lsp else dr)
        d[i] = dr
    pd_ = np.concatenate([[1], d[:-1]])
    lsma = linreg(ha, zl)
    zlsma = 2 * lsma - linreg(lsma, zl)
    el = (d == 1) & (pd_ == -1) & cross_up(ha, zlsma)
    es = (d == -1) & (pd_ == 1) & cross_dn(ha, zlsma)
    return el, cross_dn(ha, zlsma), es, cross_up(ha, zlsma), {}


def s_hull(df, s, w):
    hu = hma(df["close"].to_numpy(), L(55, s))
    h2 = shift(hu, 2)
    up, dn = hu > h2, hu < h2
    return up, dn, dn, up, {}


def s_turtle(df, s, w):
    h, lo, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()

    def hh(n):
        return shift(pd.Series(h).rolling(n).max().to_numpy(), 1)

    def ll(n):
        return shift(pd.Series(lo).rolling(n).min().to_numpy(), 1)
    ef, xf, es_ = L(20, s), L(10, s), L(55, s)
    el = (c > hh(ef)) | (c > hh(es_))
    es = (c < ll(ef)) | (c < ll(es_))
    # the exit of the faster system: the first to act
    return el, c < ll(xf), es, c > hh(xf), {"no_flip": True}


def s_jturt(df, s, w):
    h, lo, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    en, ex = L(20, s), L(10, s)
    hh = shift(pd.Series(h).rolling(en).max().to_numpy(), 1)
    ll = shift(pd.Series(lo).rolling(en).min().to_numpy(), 1)
    xh = shift(pd.Series(h).rolling(ex).max().to_numpy(), 1)
    xl = shift(pd.Series(lo).rolling(ex).min().to_numpy(), 1)
    return c > hh, c < xl, c < ll, c > xh, {"atr_stop": (2.0 * w, rma(tr(df), L(20, s))), "no_flip": True}


def s_utbot(df, s, w):
    key, n = 3.0 * w, L(1, s)
    c = df["close"].to_numpy()
    nl = key * rma(tr(df), n)
    t = np.zeros(len(c))
    prev = 0.0
    for i in range(len(c)):
        p1 = c[i - 1] if i else c[i]
        if c[i] > prev and p1 > prev:
            prev = max(prev, c[i] - nl[i])
        elif c[i] < prev and p1 < prev:
            prev = min(prev, c[i] + nl[i])
        else:
            prev = c[i] - nl[i] if c[i] > prev else c[i] + nl[i]
        t[i] = prev
    above, below = cross_up(c, t), cross_dn(c, t)
    e200 = ema(c, 200)
    buy, sell = above & (c > t), below & (c < t)
    return buy & (c > e200), sell, sell & (c < e200), buy, {"no_flip": True}


def s_rf(df, s, w):
    per, q = L(20, s), 3.5 * w
    c = df["close"].to_numpy()
    filt = range_filter(c, ema(ema(np.abs(np.diff(c, prepend=c[0])), per), per * 2 - 1) * q)
    lc, sc = rf_signals(c, filt)
    e200 = ema(c, 200)
    return lc & (c > e200), sc, sc & (c < e200), lc, {"no_flip": True}


def s_trf(df, s, w):
    c = df["close"].to_numpy()
    r = (smooth_rng(c, L(27, s), 1.6 * w) + smooth_rng(c, L(55, s), 2.0 * w)) / 2
    lc, sc = rf_signals(c, range_filter(c, r))
    return lc, sc, sc, lc, {}


def s_crunch(df, s, w):
    c = df["close"].to_numpy()
    d = np.diff(c, prepend=np.nan)
    sd = pd.Series(d).rolling(14).std().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        npr = np.nancumsum(np.where(sd > 0, d / sd, 0.0))
    f = hma(npr, L(100, s))
    up, dn = cross_up(npr, f), cross_dn(npr, f)
    return up, dn, dn, up, {"atr_stop": (1.0 * w, sma(tr(df), 14))}


def _st_up(df, n, m):
    return R.supertrend_dir(df, n, m) == 1


def s_dst(df, s, w):
    c = df["close"].to_numpy()
    d1, d2 = _st_up(df, L(10, s), 3.0 * w), _st_up(df, L(20, s), 5.0 * w)
    macd = ema(c, L(12, s)) - ema(c, L(26, s))
    hist = macd - ema(macd, L(9, s))
    bull, bear = d1 & d2 & (hist > 0), ~d1 & ~d2 & (hist < 0)
    return bull, ~d1 | ~d2 | (hist < 0), bear, d1 | d2 | (hist > 0), {"no_flip": True}


def s_fst(df, s, w):
    buy = [(4, 8), (7, 9), (1, 8)]
    sell = [(1, 16), (3, 18), (6, 18)]
    bu = np.logical_and.reduce([_st_up(df, L(p, s), m * w) for m, p in buy])
    sd = np.logical_and.reduce([~_st_up(df, L(p, s), m * w) for m, p in sell])
    bd = np.logical_and.reduce([~_st_up(df, L(p, s), m * w) for m, p in buy])
    su = np.logical_and.reduce([_st_up(df, L(p, s), m * w) for m, p in sell])
    risk = {"sl": 26.5, "roi": [(0, 8.7), (6.2, 5.8), (14.35, 2.9), (37.0, 0.0)],
            "trail": (14.4, 5.0, 26.5), "no_flip": True}
    return bu, sd, bd, su, risk


def s_stadx(df, s, w):
    c = df["close"].to_numpy()
    up = _st_up(df, L(10, s), 3.0 * w)
    ax = R.adx(df, 14).to_numpy()
    e = ema(c, L(200, s))
    return (up & (ax > 25) & (c > e), ~up | (ax < 20), ~up & (ax > 25) & (c < e), up | (ax < 20),
            {"sl": 6.0, "trail": (3.0, 2.0, None), "no_flip": True})


def s_adxsma(df, s, w):
    c = df["close"].to_numpy()
    ax = R.adx(df, 14).to_numpy()
    a, b = sma(c, L(12, s)), sma(c, L(48, s))
    return ((ax > 30) & cross_up(a, b), ax < 30, (ax > 30) & cross_dn(a, b), ax < 30,
            {"sl": 5.0, "roi": [(0, 5.0), (0.5, 10.0), (1.0, 7.5)], "no_flip": True})


def s_dema(df, s, w):
    c, lo, h = df["close"].to_numpy(), df["low"].to_numpy(), df["high"].to_numpy()
    f, m, t = ema(c, L(9, s)), ema(c, L(21, s)), ema(c, 200)
    return (cross_up(f, m) & (lo > t), cross_dn(f, m) | (lo < t),
            cross_dn(f, m) & (h < t), cross_up(f, m) | (h > t), {"sl": 20.0, "no_flip": True})


def s_macdt(df, s, w):
    c, lo, h = df["close"].to_numpy(), df["low"].to_numpy(), df["high"].to_numpy()
    macd = ema(c, L(12, s)) - ema(c, L(26, s))
    sig = ema(macd, L(9, s))
    t = ema(c, 100)
    return ((macd < 0) & cross_up(macd, sig) & (lo > t), cross_dn(macd, 0 * macd) | (lo < t),
            (macd > 0) & cross_dn(macd, sig) & (h < t), cross_up(macd, 0 * macd) | (h > t),
            {"sl": 20.0, "no_flip": True})


def s_ribbon(df, s, w):
    c = df["close"].to_numpy()
    a, b, d = ema(c, L(9, s)), ema(c, L(21, s)), ema(c, L(55, s))
    return ((a > b) & (b > d) & cross_up(c, a), cross_dn(a, b),
            (a < b) & (b < d) & cross_dn(c, a), cross_up(a, b), {})


STRATS = {  # name: (function, has a width to scale)
    "AT": (s_at, True), "OTT": (s_ott, True), "PMAX": (s_pmax, True), "CEZ": (s_cez, True),
    "HULL": (s_hull, False), "TURTLE": (s_turtle, False), "UTBOT": (s_utbot, True),
    "RF": (s_rf, True), "TRF": (s_trf, True), "CRUNCH": (s_crunch, True), "DST": (s_dst, True),
    "FST": (s_fst, True), "STADX": (s_stadx, True), "ADXSMA": (s_adxsma, False),
    "DEMA": (s_dema, False), "MACDT": (s_macdt, False), "JTURT": (s_jturt, True),
    "RIBBON": (s_ribbon, False),
    "ATRSI": (lambda df, s, w: s_at(df, s, w, use_rsi=True), True),
}


# ── one position, the author's exits, our modes and regimes ────────────────
def position(df, sig, ls, reg, rx):
    el, xl, es, xs, risk = sig
    el, xl, es, xs = (np.nan_to_num(np.asarray(x, dtype=float)).astype(bool) for x in (el, xl, es, xs))
    if not risk.get("no_flip"):
        xl, xs = xl | es, xs | el
    c = df["close"].to_numpy()
    sl, roi, trail = risk.get("sl"), risk.get("roi"), risk.get("trail")
    atr_k, atr_a = risk.get("atr_stop", (None, None))
    n = len(c)
    w = np.zeros(n, dtype=np.int8)
    pos, entry, peak, stop, t0 = 0, 0.0, 0.0, 0.0, 0
    for i in range(200, n):
        if pos:
            px = c[i]
            peak = max(peak, px) if pos == 1 else min(peak, px)
            gain = (px / entry - 1) * 100 * pos
            best = (peak / entry - 1) * 100 * pos
            out = (xl[i] if pos == 1 else xs[i])
            if sl and gain <= -sl:
                out = True
            if atr_k and (px - stop) * pos <= 0:
                out = True
            if roi:
                hrs = i - t0
                need = [r for h, r in roi if hrs >= h]
                if need and gain >= need[-1]:
                    out = True
            if trail:
                act, dist, before = trail
                d = dist if best >= act else before
                if d is not None and (peak * (1 - d / 100 * pos) - px) * pos >= 0:
                    out = True
            if reg is not None and rx and reg[i] != pos:
                out = True
            if out:
                pos = 0
        if pos == 0:
            side = 0
            if el[i] and (reg is None or reg[i] == 1):
                side = 1
            elif ls and es[i] and (reg is None or reg[i] == -1):
                side = -1
            if side and not (w[i - 1] == side):      # not back in on the bar it left
                pos, entry, peak, t0 = side, c[i], c[i], i
                if atr_k:
                    stop = c[i] - side * atr_k * atr_a[i]
        w[i] = pos
    return w


def run_pair(symbol, df, btc):
    idx = df.index
    regimes = {"none": None, "d200": R.daily_up(df, idx), "btc": R.daily_up(btc, idx),
               "w21": R.weekly_up(btc, idx)}
    years = list(range(max(R.START_YEAR + 1, idx[0].year), idx[-1].year + 1))
    hold = {}
    for y in years:
        seg = df[df.index.year == y]["close"]
        if len(seg) > 24 * 30:
            hold[str(y)] = round((seg.iloc[-1] / seg.iloc[0] - 1) * 100, 1)
    res = {"symbol": symbol, "since": f"{idx[0]:%Y-%m}", "hold": hold, "cells": {}}
    t0 = time.time()
    for name, (fn, wide) in STRATS.items():
        if (ONLY and name not in ONLY) or (os.environ.get("GRIDSET") == "v3" and name not in GRIDS_V3):
            continue
        sg, wg = (GRIDS_V3[name] if os.environ.get("GRIDSET") == "v3" else (S_GRID, W_GRID))
        for s in sg:
            for w_ in (wg if wide else [1.0]):
                sig = fn(df, s, w_)
                for mode in MODES:
                    for rg in REGIMES:
                        x = rg.endswith("x")
                        pos = position(df, sig, mode == "LS", regimes[rg[:-1] if x else rg], x)
                        bt = run_backtest(df, {}, R.BP, signals=R.signals_from(pos, idx), strategy_name=R.LORENZO)
                        vals = f"{s:g},{w_:g}" if wide else f"{s:g}"
                        res["cells"][f"{name}|{mode}|{rg}|{vals}"] = R.by_year(bt, years)
        print(f"{symbol} {name}: {len(res['cells'])} cells, {time.time() - t0:.0f}s", flush=True)
    return res


def main() -> int:
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        df = R.binance(sym)
        btc = df if sym == "BTCUSDT" else R.binance("BTCUSDT")
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={sym}::{exc}")
        return 0
    res = run_pair(sym, df, btc)
    with gzip.open(f"r1h-{sym}.json.gz", "wt") as fh:
        json.dump(res, fh)
    print(f"{sym}: {len(df)} candles since {res['since']}, B&H {res['hold']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
