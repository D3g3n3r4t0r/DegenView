"""Combined Reversal (Lorenzo, 16/10: "una strategia sola, che pero' ha piu'
segnali di ingresso e piu' segnali di uscita", "aggiungi anche la combinata"):
Trend EMA Reversal + RSI+BB reversal, one position, either entry, first exit."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.strategies import (
    AVAILABLE_STRATEGIES,
    COMBINED_REVERSAL,
    STRATEGY_REGISTRY,
    compute_lki_signals,
    compute_lorenzo_reversal_signals,
)

N = 1500
_C = 100 * np.exp(np.cumsum(np.random.default_rng(9).normal(0, 0.025, N)))
DF = pd.DataFrame({"open": _C, "high": _C * 1.01, "low": _C * 0.99, "close": _C, "volume": 1.0},
                  index=pd.date_range("2021-01-01", periods=N, freq="D", tz="UTC"))


def test_offered():
    assert COMBINED_REVERSAL in AVAILABLE_STRATEGIES


def test_one_position_either_entry_first_exit():
    sig = STRATEGY_REGISTRY[COMBINED_REVERSAL](DF, {})
    lo, ga = compute_lorenzo_reversal_signals(DF, {}), compute_lki_signals(DF, {})
    any_in = lo["entry_long"] | ga["entry_long"]
    any_out = lo["exit_long"] | ga["exit_long"]
    assert not sig["entry_short"].any()
    pos = False
    for i in range(N):
        if sig["entry_long"].iat[i]:
            assert not pos and any_in.iat[i]
            pos = True
        elif sig["exit_long"].iat[i]:
            assert pos and any_out.iat[i]
            pos = False
        elif not pos:
            assert not any_in.iat[i]          # flat with a signal = it would have entered
    # more trades than either one alone
    n = run_backtest(DF, {}, {}, strategy_name=COMBINED_REVERSAL).num_trades
    assert n >= run_backtest(DF, {}, {}, strategy_name="Lorenzo reversal (long only)").num_trades
