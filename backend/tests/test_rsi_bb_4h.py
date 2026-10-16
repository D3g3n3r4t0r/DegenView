"""RSI+BB 4H (Lorenzo, 13/10): "Deve funzionare esattamente come le altre due
RSI+BB, l'unica differenza deve essere il Bollinger Multiplier settato di
default a 2.5" — the long-only one, he chose."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.optimize import (
    GABRIELE_STRATEGIES,
    gabriele_fixed,
    grid_size,
    is_optimizable,
    max_return_search,
)
from app.analysis.backtest import run_backtest
from app.analysis.strategies import (
    AVAILABLE_STRATEGIES,
    HIDDEN_STRATEGIES,
    LKI4H_DEFAULT_PARAMS,
    RSI_BB_4H,
    compute_lki4h_signals,
    compute_lki_signals,
)

N = 400
_C = 100 + np.cumsum(np.random.default_rng(5).normal(0, 2, N)) + 10 * np.sin(np.arange(N) / 6)
DF = pd.DataFrame({"open": _C, "high": _C + 1.5, "low": _C - 1.5, "close": _C, "volume": 1.0},
                  index=pd.date_range("2023-01-01", periods=N, freq="4h", tz="UTC"))


def test_registered_and_searchable():
    # a trial, out of the menus since 16/10, but still registered and searchable
    assert RSI_BB_4H in HIDDEN_STRATEGIES and RSI_BB_4H not in AVAILABLE_STRATEGIES
    assert RSI_BB_4H in GABRIELE_STRATEGIES
    assert is_optimizable(RSI_BB_4H) and grid_size(RSI_BB_4H) == 36 * 36
    assert LKI4H_DEFAULT_PARAMS["bb_mult"] == 2.5


def test_same_rules_as_the_long_only_rsi_bb_with_2_5():
    a = compute_lki4h_signals(DF)
    b = compute_lki_signals(DF, {"bb_mult": 2.5})
    pd.testing.assert_frame_equal(a, b)
    # an unset multiplier (None, as the shared query sends it) keeps 2.5
    pd.testing.assert_frame_equal(compute_lki4h_signals(DF, {"bb_mult": None}), b)
    # and an explicit one wins, exactly like the original
    pd.testing.assert_frame_equal(compute_lki4h_signals(DF, {"bb_mult": 2.0}), compute_lki_signals(DF))


def test_optimizations_keep_2_5():
    assert gabriele_fixed(RSI_BB_4H)["bb_mult"] == 2.5
    assert gabriele_fixed("Gabriele (RSI+BB reversal)")["bb_mult"] == 2.0
    params, _, _, top = max_return_search(
        RSI_BB_4H, lambda p: run_backtest(DF, p, {}, strategy_name=RSI_BB_4H))
    assert params["bb_mult"] == 2.5 and all(c["params"]["bb_mult"] == 2.5 for c in top)


def test_quick_and_grid_search_keep_2_5():
    from app.analysis.optimize import optimize_strategy
    for mode in ("random", "grid"):
        params, _, _, _, _, top = optimize_strategy(RSI_BB_4H, DF, {}, trials=20, seed=1, mode=mode)
        assert params["bb_mult"] == 2.5
        assert all(c["params"]["bb_mult"] == 2.5 for c in top)
