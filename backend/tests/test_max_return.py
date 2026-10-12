"""
Mode "max_return": every RSI pair, one by one, highest return within 60% DD.

Lorenzo, 12/10: "oversold only from 10 to 40, overbought only from 60 to 90
[...] every value crossed with the other, one by one [...] picking the best
performance with a maximum allowed drawdown of 60%".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest
from app.analysis.optimize import (
    GABRIELE_FIXED,
    MAX_RETURN_DRAWDOWN_CAP,
    Constraints,
    NoCandidateMeetsConstraints,
    max_return_search,
    max_return_size,
)

GAB = "Gabriele (RSI+BB reversal)"
N = 300
_IDX = pd.date_range("2023-01-01", periods=N, freq="D", tz="UTC")
_C = 100 + np.cumsum(np.random.default_rng(3).normal(0, 2, N)) + 12 * np.sin(np.arange(N) / 6)
DF = pd.DataFrame({"open": _C, "high": _C + 1.5, "low": _C - 1.5, "close": _C,
                   "volume": np.full(N, 1000.0)}, index=_IDX)


def _bt(params):
    return run_backtest(DF, params, {}, strategy_name=GAB)


def test_every_pair_from_10_40_by_60_90_is_tried():
    tried = []

    def spy(p):
        tried.append((p["rsi_oversold"], p["rsi_overbought"]))
        return _bt(p)

    _, _, evaluated, _ = max_return_search(GAB, spy)
    assert max_return_size() == 31 * 31 == evaluated
    assert set(tried) == {(o, b) for o in range(10, 41) for b in range(60, 91)}


def test_the_winner_is_the_highest_return_within_the_drawdown_cap():
    params, bt, _, top = max_return_search(GAB, _bt)
    brute = []
    for o in range(10, 41):
        for b in range(60, 91):
            r = _bt({**GABRIELE_FIXED, "rsi_oversold": o, "rsi_overbought": b})
            if r.num_trades >= 1 and abs(r.max_drawdown_pct) <= MAX_RETURN_DRAWDOWN_CAP:
                brute.append(r.total_return_pct)
    assert bt.total_return_pct == pytest.approx(max(brute))
    assert abs(bt.max_drawdown_pct) <= MAX_RETURN_DRAWDOWN_CAP
    assert [c["backtest"].total_return_pct for c in top] == sorted(
        (c["backtest"].total_return_pct for c in top), reverse=True)
    assert params["rsi_length"] == 14 and params["bb_length"] == 20


def test_only_rsi_bb_strategies():
    with pytest.raises(ValueError):
        max_return_search("Lorenzo (trend-follower)", _bt)


def test_lab_filters_still_apply():
    with pytest.raises(NoCandidateMeetsConstraints):
        max_return_search(GAB, _bt, constraints=Constraints(min_losing_trades=10**6))
