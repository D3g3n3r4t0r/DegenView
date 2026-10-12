"""Backtest speed on a fixed synthetic series (overhaul plan, week 1).

    cd backend && PYTHONPATH=. python ../scripts/bench_backtest.py

Prints ms per run for each strategy, 5000 4h candles, with and without
stop/target. Same seed every time, so numbers compare across commits.
"""
import time

import numpy as np
import pandas as pd

from app.analysis.backtest import run_backtest

STRATEGIES = ["Lorenzo (trend-follower)", "Gabriele (RSI+BB reversal)",
              "Gabriele 2 (RSI+BB long/short)", "Accumulo / Distribuzione (long-term)"]


def series(n=5000, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.03, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.03, n))
    idx = pd.date_range("2021-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(1, 100, n)}, index=idx)


def main(reps=5):
    df = series()
    for name in STRATEGIES:
        for bp in ({"initial_capital": 1000}, {"initial_capital": 1000, "stop_loss_pct": 4, "take_profit_pct": 9}):
            t0 = time.perf_counter()
            for _ in range(reps):
                bt = run_backtest(df, None, bp, strategy_name=name)
            ms = (time.perf_counter() - t0) / reps * 1000
            tag = "sl/tp" if "stop_loss_pct" in bp else "plain"
            print(f"{name:40s} {tag:6s} {ms:8.1f} ms  trades={bt.num_trades}")


if __name__ == "__main__":
    main()
