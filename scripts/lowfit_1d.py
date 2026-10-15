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
        extra = "".join(f" {x}={r[x]}" for x in ("sec", "full_sec", "wf_med", "wf_pos", "wfe", "mc_dd95", "mc_ploss") if r.get(x) is not None)
        bits.append(f"{k} [{','.join(str(v) for v in r['p'].values())}] train {r['train_simple']:+.0f}% · {cells}{extra}")
    return " | ".join(bits)


async def main():
    sym = os.environ.get("PAIR", "BTCUSDT")
    try:
        src, df = await env.candles(sym)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title={sym}::{exc}")
        return 0
    res = run_pair(sym, df)
    print(f"::notice title={sym}::{line(res)} [{src}]")
    with open(f"lowfit-{sym}.json", "w") as fh:
        json.dump(res, fh)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
