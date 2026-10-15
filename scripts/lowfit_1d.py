"""Low-overfitting optimization, measured in the test environment (1D only).

Lorenzo, 15/10: "un tasto di ottimizzazione [...] per far si' che l'overfitting
sia ridotto al minimo", "prima di tutto di fare un test nel nostro ambiente di
test", "usa sempre il time frame one day".

For one pair and each strategy (RSI+BB reversal, Trend EMA Reversal), the
values are chosen on the candles from 2023 on and then run on 2021 and on 2022,
which the choice never saw — the same rule as compare_claudio_folds.py. Methods:

  default   the strategy's own values, nothing searched
  maxret    the site's Max return (RSI+BB only)
  stable    the site's Stable search (analysis.pipeline.run_pipeline)
  wf        Stable + walk-forward: anchored folds on the training candles —
            search up to a date, test the next 6 months, move on — and the
            values kept are those with the best median out-of-sample result
            across the folds, among every fold's pick and the stable pick

Every pick also gets a Monte Carlo (trades resampled 1 000 times): worst-case
drawdown and chance of a loss. And the time each method takes, on the training
candles and on the whole history (what the site would search).

    cd backend && PAIR=BTCUSDT PYTHONPATH=. python ../scripts/lowfit_1d.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

os.environ.setdefault("TF", "1d")
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import compare_claudio_folds as env  # noqa: E402
from app.analysis.backtest import run_backtest  # noqa: E402
from app.analysis.optimize import calendar_years, max_return_search  # noqa: E402
from app.analysis.pipeline import run_pipeline  # noqa: E402
from app.analysis.strategies import DEFAULT_PARAMS, LKI_DEFAULT_PARAMS  # noqa: E402

# the site's position since 15/10: 1 000 $, 100% a trade, no costs
BP = {"initial_capital": 1000.0, "qty_pct_of_equity": 100.0, "commission_pct": 0.0,
      "slippage_pct": 0.0, "fill_at": "signal_close"}
env.BP = BP
GAB = "Gabriele (RSI+BB reversal)"
LREV = "Lorenzo reversal (long only)"
STRATS = ((GAB, dict(LKI_DEFAULT_PARAMS)), (LREV, dict(DEFAULT_PARAMS)))
TRAIN_FROM = pd.Timestamp("2023-01-01", tz="UTC")
FOLD_MONTHS = 6
FOLDS = 4
WF_EVALS = 300          # lighter search inside each fold
SHOWN = ("rsi_oversold", "rsi_overbought", "len", "slopeFlen", "slopeSlen", "average",
         "trendfilter", "volatilityfilter")


def mc(bt, n=1000, seed=7):
    """Bootstrap of the trades' net %: compounded drawdown at the 95th
    percentile and the share of runs ending in a loss."""
    if not bt.trades:
        return {"mc_dd95": None, "mc_ploss": None}
    q = BP["qty_pct_of_equity"] / 100
    net = np.array([t.pnl_abs / ((t.equity_after - t.pnl_abs) * q) for t in bt.trades])
    rng = np.random.default_rng(seed)
    dds, losses = [], 0
    for _ in range(n):
        s = rng.choice(net, size=len(net), replace=True)
        eq = np.cumprod(1 + s * q)
        peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        dds.append(float(np.max((peak - eq) / peak)) * 100)
        losses += eq[-1] < 1
    return {"mc_dd95": round(float(np.percentile(dds, 95)), 1), "mc_ploss": round(losses / n, 2)}


def tests_of(df):
    out = []
    for y in (2021, 2022):
        t0, t1 = pd.Timestamp(year=y, month=1, day=1, tz="UTC"), pd.Timestamp(year=y + 1, month=1, day=1, tz="UTC")
        if df.index[0] <= t0 - pd.Timedelta(days=60):
            out.append((y, t0, t1))
    return out


def stable(strat, frame, budget=700):
    res = run_pipeline(strat, frame, BP, max_evals_per_branch=budget, locked_params={})
    return res.params


def walk_forward(strat, frame):
    """Anchored folds on `frame`: search up to the fold, test the next six
    months. Returns the kept values and the folds' efficiency."""
    end = frame.index[-1]
    starts = [end - pd.DateOffset(months=FOLD_MONTHS * k) for k in range(FOLDS, 0, -1)]
    folds = [(s, min(s + pd.DateOffset(months=FOLD_MONTHS), end)) for s in starts]
    picks, eff = [], []
    for s, e in folds:
        is_ = frame[frame.index < s]
        if len(is_) < 250:
            continue
        p = run_pipeline(strat, is_, BP, max_evals_per_branch=WF_EVALS, locked_params={}).params
        picks.append(p)
        is_bt = run_backtest(is_, p, BP, strategy_name=strat)
        oos_bt = env.test_on(frame, strat, p, s, e)
        is_days = max((is_.index[-1] - is_.index[0]).days, 1)
        eff.append((env.annual(is_bt.simple_return_pct, is_days), env.annual(oos_bt.simple_return_pct, (e - s).days)))
    return picks, folds, eff


def pick_wf(strat, frame, cands, folds):
    best, best_key = None, None
    for p in cands:
        rets = [env.test_on(frame, strat, p, s, e).simple_return_pct for s, e in folds]
        key = (float(np.median(rets)), sum(r > 0 for r in rets))
        if best_key is None or key > best_key:
            best, best_key = p, key
    return best, best_key


def judge(df, strat, p, tests, train):
    bt = run_backtest(train, p, BP, strategy_name=strat)
    row = {"train_simple": round(bt.simple_return_pct, 1), "train_tr": bt.num_trades,
           "p": {k: v for k, v in p.items() if k in SHOWN}, **mc(bt)}
    for y, t0, t1 in tests:
        tb = env.test_on(df, strat, p, t0, t1)
        row[str(y)] = {"s": round(tb.simple_return_pct, 1), "c": round(tb.total_return_pct, 1),
                       "dd": round(tb.max_drawdown_pct, 1), "tr": tb.num_trades}
    return row


# ── v2 (15/10, after the first run): "Low overfitting" as it would be ──────
# Lorenzo: "rifai il test con questi parametri". Narrow ranges around the
# defaults, at least MIN_TRADES trades in every full year of the training,
# walk-forward as the judge: the procedure (choose on the candles before a
# fold, keep the best by simple return x solidity) has to beat the plain
# defaults out of sample across the folds, otherwise the defaults stay.
MIN_TRADES = 4
NARROW = {
    GAB: (("rsi_oversold", list(range(22, 35))), ("rsi_overbought", list(range(66, 79)))),
    LREV: (("len", list(range(90, 171, 10))), ("slopeFlen", list(range(4, 11))),
           ("slopeSlen", list(range(19, 36, 2)))),
}


def _net(bt):
    q = BP["qty_pct_of_equity"] / 100
    return [(t.entry_time, t.exit_time, t.pnl_abs / ((t.equity_after - t.pnl_abs) * q) * 100) for t in bt.trades]


def _window(trades, a, b, by="exit"):
    a, b = int(a.timestamp()), int(b.timestamp())
    return [x for (en, ex, x) in trades if a <= (ex if by == "exit" else en) < b]


def lowfit(strat, defaults, frame):
    import itertools
    dims = NARROW[strat]
    names = [d[0] for d in dims]
    vals = [d[1] for d in dims]
    grid = list(itertools.product(*[range(len(v)) for v in vals]))
    start, end = frame.index[0], frame.index[-1]
    full_years = [y for y in range(start.year, end.year + 1)
                  if pd.Timestamp(year=y, month=1, day=1, tz="UTC") >= start
                  and pd.Timestamp(year=y, month=12, day=31, tz="UTC") <= end]
    trades = {}
    for key in grid:
        p = {**defaults, **{nm: vals[d][i] for d, (nm, i) in enumerate(zip(names, key))}}
        trades[key] = (p, _net(run_backtest(frame, p, BP, strategy_name=strat)))
    dflt = _net(run_backtest(frame, defaults, BP, strategy_name=strat))

    def choose(until):
        yrs = [y for y in full_years if pd.Timestamp(year=y + 1, month=1, day=1, tz="UTC") <= until]
        score = {}
        for key, (_, tr) in trades.items():
            if any(sum(1 for (en, _, _) in tr if pd.Timestamp(en, unit="s", tz="UTC").year == y) < MIN_TRADES for y in yrs):
                continue
            score[key] = sum(_window(tr, start, until))
        best, best_v = None, None
        for key, own in score.items():
            near = []
            for d in range(len(key)):
                for st in (-1, 1):
                    k = list(key)
                    k[d] += st
                    if tuple(k) in score:
                        near.append(score[tuple(k)])
            sol = 0.0 if own <= 0 or not near else max(0.0, min(1.0, float(np.median(near)) / own))
            v = own * sol
            if best_v is None or v > best_v:
                best, best_v = key, v
        return best
    folds = [(end - pd.DateOffset(months=FOLD_MONTHS * k), end - pd.DateOffset(months=FOLD_MONTHS * (k - 1)))
             for k in range(FOLDS, 0, -1)]
    proc, base = [], []
    for s_, e_ in folds:
        k = choose(s_)
        proc.append(sum(_window(trades[k][1], s_, e_, "entry")) if k else 0.0)
        base.append(sum(_window(dflt, s_, e_, "entry")))
    final = choose(end + pd.Timedelta(days=1))
    beats = final is not None and float(np.median(proc)) > float(np.median(base))
    return (trades[final][0] if beats else dict(defaults)), {
        "kept": "searched" if beats else "default", "wf_proc": round(float(np.median(proc)), 1),
        "wf_def": round(float(np.median(base)), 1), "cells": len(grid)}


# RSI+BB additions to look at (defaults, nothing searched): a stop loss, the
# BTC filter, and the BTC filter closing the long when it turns off.
def _rsi_bb_exit(kind):
    """RSI+BB reversal with another exit (test only): "mid" = close back
    above the middle band, "or" = RSI over overbought OR close over the
    upper band (the site's needs both, which a falling market never gives)."""
    from app.analysis import btc_regime
    from app.analysis.strategies import compute_lki_signals
    from app.analysis.strategies import LKI_DEFAULT_PARAMS as D

    def fn(df, params=None):
        p = {**D, **{k: v for k, v in (params or {}).items() if v is not None and k in D}}
        sig = compute_lki_signals(df, p).copy()
        close = df["close"]
        basis = close.rolling(p["bb_length"]).mean()
        upper = basis + p["bb_mult"] * close.rolling(p["bb_length"]).std(ddof=0)
        delta = close.diff()
        from app.analysis.strategies import _wilder_rma
        g = _wilder_rma(delta.clip(lower=0), p["rsi_length"])
        lo = _wilder_rma(-delta.clip(upper=0), p["rsi_length"])
        rsi = 100 - 100 / (1 + g / lo.replace(0, np.nan))
        sig["exit_long"] = ((close > basis) if kind == "mid" else ((rsi > p["rsi_overbought"]) | (close > upper))).fillna(False)
        return btc_regime.apply(sig, params)
    return fn


GAB_MID, GAB_OR = "RSI+BB exit mid (test)", "RSI+BB exit or (test)"
env.STRATEGY_REGISTRY[GAB_MID] = _rsi_bb_exit("mid")
env.STRATEGY_REGISTRY[GAB_OR] = _rsi_bb_exit("or")
# (name, strategy, extra params, extra backtest settings)
GAB_EXTRA = (("G_mid", GAB_MID, {}, {}), ("G_or", GAB_OR, {}, {}),
             ("G_mid_btc", GAB_MID, {"btc_filter": True}, {}), ("G_or_btc", GAB_OR, {"btc_filter": True}, {}),
             ("G_or_sl15", GAB_OR, {}, {"stop_loss_pct": 15.0}))

GAB_VARIANTS = (("G_sl10", {}, {"stop_loss_pct": 10.0}), ("G_sl20", {}, {"stop_loss_pct": 20.0}),
                ("G_btc", {"btc_filter": True}, {}), ("G_btcx", {"btc_filter": True, "btc_filter_exit": True}, {}),
                ("G_btcx_sl15", {"btc_filter": True, "btc_filter_exit": True}, {"stop_loss_pct": 15.0}))


def judge_bp(df, strat, p, tests, train, bp):
    bt = run_backtest(train, p, bp, strategy_name=strat)
    row = {"train_simple": round(bt.simple_return_pct, 1), "train_tr": bt.num_trades,
           "p": {k: v for k, v in p.items() if k in SHOWN}, **mc(bt)}
    for y, t0, t1 in tests:
        tb = env.test_on(df, strat, p, t0, t1, bp=bp)
        row[str(y)] = {"s": round(tb.simple_return_pct, 1), "c": round(tb.total_return_pct, 1),
                       "dd": round(tb.max_drawdown_pct, 1), "tr": tb.num_trades}
    return row


def run_pair_v2(sym, df):
    train = df[df.index >= TRAIN_FROM]
    tests = tests_of(df)
    res = {"symbol": sym, "since": f"{df.index[0]:%Y-%m}",
           "hold": {str(y): round((df[(df.index >= t0) & (df.index < t1)]["close"].iloc[-1]
                                   / df[(df.index >= t0) & (df.index < t1)]["close"].iloc[0] - 1) * 100, 1)
                    for y, t0, t1 in tests}, "m": {}}
    for strat, defaults in STRATS:
        tag = "G" if strat == GAB else "LR"
        res["m"][f"{tag}_default"] = judge(df, strat, defaults, tests, train)
        t = time.time()
        p, info = lowfit(strat, defaults, train)
        res["m"][f"{tag}_lowfit"] = {**judge(df, strat, p, tests, train), **info, "sec": round(time.time() - t)}
        if strat == GAB:
            for name, extra, bp_extra in GAB_VARIANTS:
                res["m"][name] = judge_bp(df, strat, {**defaults, **extra}, tests, train, {**BP, **bp_extra})
            for name, st, extra, bp_extra in GAB_EXTRA:
                res["m"][name] = judge_bp(df, st, {**defaults, **extra}, tests, train, {**BP, **bp_extra})
        print(json.dumps({k: v for k, v in res["m"].items() if k.startswith(tag)}), flush=True)
    return res


# ── v3 (15/10): Stable + Max return for RSI+BB 1D ──────────────────────────
# Lorenzo: "aggiungere alla versione stabile della RSI piu' BB le
# caratteristiche [...] della max return, ovvero di andare a ottimizzare i
# due valori di RSI nel miglior modo possibile, sempre nei range [...] della
# 4 ore". Every pair 20-40 x 65-85; the most solid (simple return x the share
# of it the +-1 neighbours keep) and the most profitable with solidity >= 25%;
# 60% compounded drawdown cap, a trade in every judged year (or as many trades
# as those years) — the 1D rule. With today's exit and with the middle band.
OS_R, OB_R = list(range(20, 41)), list(range(65, 86))


def solid_search(strat, frame):
    from app.analysis.optimize import trades_in_years, years_without_trades
    years = calendar_years(frame.index)
    ret, ok = {}, set()
    for i, o in enumerate(OS_R):
        for j, b in enumerate(OB_R):
            bt = run_backtest(frame, {**LKI_DEFAULT_PARAMS, "rsi_oversold": o, "rsi_overbought": b}, BP, strategy_name=strat)
            ret[(i, j)] = bt.simple_return_pct
            if bt.num_trades >= 1 and abs(bt.max_drawdown_pct) <= 60 and not (
                    years and trades_in_years(bt, years) < len(years) and years_without_trades(bt, years)):
                ok.add((i, j))
    sol = {}
    for k in ok:
        near = [ret[(k[0] + a, k[1] + b)] for a, b in ((-1, 0), (1, 0), (0, -1), (0, 1)) if (k[0] + a, k[1] + b) in ret]
        own = ret[k]
        sol[k] = 0.0 if own <= 0 or not near else max(0.0, min(1.0, float(np.median(near)) / own))
    if not ok:
        return None, None, None
    # a loss is never "solid": positive returns first, then by return x solidity
    solid = max(ok, key=lambda k: (ret[k] > 0, ret[k] * sol[k] if ret[k] > 0 else ret[k]))
    prof = [k for k in ok if sol[k] >= 0.25]
    prof = max(prof, key=lambda k: ret[k]) if prof else None
    best = max(ok, key=lambda k: ret[k])                     # = Max return
    mk = lambda k: None if k is None else {**LKI_DEFAULT_PARAMS, "rsi_oversold": OS_R[k[0]], "rsi_overbought": OB_R[k[1]]}  # noqa: E731
    return mk(solid), mk(prof), mk(best)


def run_pair_v3(sym, df):
    train = df[df.index >= TRAIN_FROM]
    tests = tests_of(df)
    res = {"symbol": sym, "since": f"{df.index[0]:%Y-%m}",
           "hold": {str(y): round((df[(df.index >= t0) & (df.index < t1)]["close"].iloc[-1]
                                   / df[(df.index >= t0) & (df.index < t1)]["close"].iloc[0] - 1) * 100, 1)
                    for y, t0, t1 in tests}, "m": {}}
    for strat, tag in ((GAB, "G"), (GAB_MID, "Gmid")):
        res["m"][f"{tag}_default"] = judge(df, strat, dict(LKI_DEFAULT_PARAMS), tests, train)
        if strat == GAB:
            try:
                res["m"][f"{tag}_stable"] = judge(df, strat, stable(strat, train), tests, train)
            except Exception:  # noqa: BLE001
                res["m"][f"{tag}_stable"] = {"error": "none"}
        t = time.time()
        solid, prof, best = solid_search(strat, train)
        for kind, p in (("maxret", best), ("solid", solid), ("prof", prof)):
            res["m"][f"{tag}_{kind}"] = ({**judge(df, strat, p, tests, train), "sec": round(time.time() - t)}
                                         if p else {"error": "none"})
        print(json.dumps({k: v for k, v in res["m"].items() if k.startswith(tag)}), flush=True)
    return res


def run_pair(sym, df):
    train = df[df.index >= TRAIN_FROM]
    tests = tests_of(df)
    years = calendar_years(train.index)
    res = {"symbol": sym, "since": f"{df.index[0]:%Y-%m}",
           "hold": {str(y): round((df[(df.index >= t0) & (df.index < t1)]["close"].iloc[-1]
                                   / df[(df.index >= t0) & (df.index < t1)]["close"].iloc[0] - 1) * 100, 1)
                    for y, t0, t1 in tests}, "m": {}}
    for strat, defaults in STRATS:
        tag = "G" if strat == GAB else "LR"
        res["m"][f"{tag}_default"] = judge(df, strat, defaults, tests, train)
        if strat == GAB:
            t = time.time()
            try:
                p, *_ = max_return_search(strat, lambda q: run_backtest(train, q, BP, strategy_name=strat), years=years)
                res["m"][f"{tag}_maxret"] = {**judge(df, strat, p, tests, train), "sec": round(time.time() - t)}
            except ValueError as exc:
                res["m"][f"{tag}_maxret"] = {"error": str(exc)[:60]}
        t = time.time()
        try:
            sp = stable(strat, train)
            res["m"][f"{tag}_stable"] = {**judge(df, strat, sp, tests, train), "sec": round(time.time() - t)}
        except Exception as exc:  # noqa: BLE001
            res["m"][f"{tag}_stable"] = {"error": str(exc)[:60]}
            sp = None
        t = time.time()
        try:
            picks, folds, eff = walk_forward(strat, train)
            cands = picks + ([sp] if sp else [])
            wp, key = pick_wf(strat, train, cands, folds)
            is_m = np.mean([a for a, _ in eff]) if eff else None
            oos_m = np.mean([b for _, b in eff]) if eff else None
            res["m"][f"{tag}_wf"] = {**judge(df, strat, wp, tests, train), "sec": round(time.time() - t + 0),
                                     "wf_med": round(key[0], 1), "wf_pos": f"{key[1]}/{len(folds)}",
                                     "wfe": None if not is_m else round(oos_m / is_m, 2) if is_m > 0 else None}
        except Exception as exc:  # noqa: BLE001
            res["m"][f"{tag}_wf"] = {"error": str(exc)[:60]}
        # what the site would take: the same two searches on the whole history
        if os.environ.get("TIMING", "1") == "1":
            t = time.time()
            try:
                stable(strat, df)
                res["m"][f"{tag}_stable"]["full_sec"] = round(time.time() - t)
                t = time.time()
                walk_forward(strat, df)
                res["m"][f"{tag}_wf"]["full_sec"] = round(time.time() - t) + res["m"][f"{tag}_stable"]["full_sec"]
            except Exception:  # noqa: BLE001
                pass
        print(json.dumps({k: v for k, v in res["m"].items() if k.startswith(tag)}), flush=True)
    return res


def line(res):
    hold = " ".join(f"{y} {h:+.0f}%" for y, h in res["hold"].items())
    bits = [f"{res['symbol']} since {res['since']} · B&H {hold}"]
    for k, r in res["m"].items():
        if "error" in r:
            bits.append(f"{k} none")
            continue
        cells = " ".join(f"{y} {r[y]['s']:+.0f}%/{r[y]['c']:+.0f}% dd{r[y]['dd']:.0f} ({r[y]['tr']}tr)" for y in res["hold"] if y in r)
        extra = "".join(f" {x}={r[x]}" for x in ("sec", "full_sec", "wf_med", "wf_pos", "wfe", "kept", "wf_proc", "wf_def", "mc_dd95", "mc_ploss") if r.get(x) is not None)
        bits.append(f"{k} [{','.join(str(v) for v in r['p'].values())}] train {r['train_simple']:+.0f}% · {cells}{extra}")
    return " | ".join(bits)


async def main():
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        src, df = await env.candles(sym)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={sym}::{exc}")
        return 0
    from app.analysis import btc_regime
    btc = df if sym == "BTCUSDT" else (await env.candles("BTCUSDT"))[1]
    btc_regime.set_closes(btc["close"], pin=True)
    mode = os.environ.get("MODE")
    res = run_pair_v2(sym, df) if mode == "v2" else run_pair_v3(sym, df) if mode == "v3" else run_pair(sym, df)
    print(f"::notice title={sym}::{line(res)} [{src}]")
    with open(f"lowfit-{sym}.json", "w") as fh:
        json.dump(res, fh)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
