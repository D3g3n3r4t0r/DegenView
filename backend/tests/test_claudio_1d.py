"""Claudio 1D (Lorenzo, 15/10: "metti a punto una tua strategia che reputi la
migliore per il time frame di un giorno"): pullback in an uptrend, long only."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.strategies import AVAILABLE_STRATEGIES, CLAUDIO_1D, STRATEGY_REGISTRY, compute_claudio_1d_signals

N = 1400
_R = np.random.default_rng(5)
_drift = np.where(np.arange(N) < N // 2, 0.004, -0.004)
_C = 100 * np.exp(np.cumsum(_R.normal(0, 0.012, N) + _drift))
DF = pd.DataFrame({"open": _C, "high": _C * 1.02, "low": _C * 0.98, "close": _C, "volume": 1.0},
                  index=pd.date_range("2020-01-01", periods=N, freq="1D", tz="UTC"))


def test_registered_but_hidden():
    assert CLAUDIO_1D in STRATEGY_REGISTRY and CLAUDIO_1D not in AVAILABLE_STRATEGIES


def test_no_future_candle():
    full = compute_claudio_1d_signals(DF)
    for cut in (400, 800, 1200):
        assert (compute_claudio_1d_signals(DF.iloc[:cut]) == full.iloc[:cut]).all().all()


def test_long_only_trades_the_bull_half_not_the_bear_one():
    sig = compute_claudio_1d_signals(DF)
    assert not sig["entry_short"].any()
    # in a clean bull it gets in and rides it on the trailing stop; once the
    # long EMA turns down it stays out
    assert sig["entry_long"].iloc[:N // 2].sum() >= 1
    assert sig["entry_long"].iloc[N // 2 + 150:].sum() == 0
