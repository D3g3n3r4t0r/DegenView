"""Claudio Trend 4H (Lorenzo, 15/10: "efficace sia in un mercato fortemente
rialzista come il 2021, sia in un mercato fortemente ribassista come il 2022
[...] senza grosse perdite"): long only, breakout under a daily regime."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.strategies import (
    AVAILABLE_STRATEGIES,
    CLAUDIO_TREND_4H,
    STRATEGY_REGISTRY,
    compute_claudio_trend_signals,
    daily_regime,
)

N = 6 * 600
_R = np.random.default_rng(4)
_drift = np.where(np.arange(N) < N // 2, 0.0015, -0.0015)       # a bull half, then a bear half
_C = 100 * np.exp(np.cumsum(_R.normal(0, 0.01, N) + _drift))
DF = pd.DataFrame({"open": _C, "high": _C * 1.006, "low": _C * 0.994, "close": _C, "volume": 1.0},
                  index=pd.date_range("2021-01-01", periods=N, freq="4h", tz="UTC"))


def test_registered_but_hidden():
    assert CLAUDIO_TREND_4H in STRATEGY_REGISTRY and CLAUDIO_TREND_4H not in AVAILABLE_STRATEGIES


def test_no_future_candle():
    full = compute_claudio_trend_signals(DF)
    for cut in (1500, 2400, 3100):
        part = compute_claudio_trend_signals(DF.iloc[:cut])
        assert (part == full.iloc[:cut]).all().all()


def test_regime_is_yesterdays():
    r = daily_regime(DF, 150)
    day = DF.index[2000].normalize()
    assert r[DF.index.normalize() == day].nunique() == 1      # one value for the whole day


def test_long_only_and_out_in_the_bear_half():
    sig = compute_claudio_trend_signals(DF, {"ct_ema_days": 100})
    assert not sig["entry_short"].any() and sig["entry_long"].any()
    bear = sig.index >= DF.index[N // 2 + 6 * 130]              # well after the turn
    assert sig["entry_long"][bear].sum() <= 2
    bt = run_backtest(DF, {"ct_ema_days": 100}, {}, signals=sig, strategy_name=CLAUDIO_TREND_4H)
    assert bt.num_trades >= 1
