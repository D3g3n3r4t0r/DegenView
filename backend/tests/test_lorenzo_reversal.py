"""Trend EMA Reversal (Lorenzo, 15/10: "uguale alla trend EMA per quanto
riguarda i valori, ma non andare short. Invece di aprire lo short deve uscire
dalla posizione e chiudere il long, come funziona la RSI BB reversal")."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.strategies import AVAILABLE_STRATEGIES, LORENZO_REVERSAL, STRATEGY_REGISTRY, compute_signals

N = 1500
_C = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.02, N)))
DF = pd.DataFrame({"open": _C, "high": _C * 1.01, "low": _C * 0.99, "close": _C, "volume": 1.0},
                  index=pd.date_range("2021-01-01", periods=N, freq="D", tz="UTC"))


def test_offered_like_the_others():
    assert LORENZO_REVERSAL in AVAILABLE_STRATEGIES


def test_same_long_entries_and_exits_never_a_short():
    trend = compute_signals(DF, {})
    rev = STRATEGY_REGISTRY[LORENZO_REVERSAL](DF, {})
    assert rev["entry_long"].equals(trend["entry_long"]) and rev["exit_long"].equals(trend["exit_long"])
    assert not rev["entry_short"].any() and not rev["exit_short"].any()
    bt = run_backtest(DF, {}, {}, strategy_name=LORENZO_REVERSAL)
    assert bt.num_trades > 0 and all(t.direction == "long" for t in bt.trades)
    # where the trend follower flips to short, the reversal is flat instead
    lorenzo = run_backtest(DF, {}, {}, strategy_name="Lorenzo (trend-follower)")
    assert any(t.direction == "short" for t in lorenzo.trades)
