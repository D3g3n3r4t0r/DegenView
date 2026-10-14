"""Claudio 4H (Lorenzo, 15/10: "una strategia 'Claudio' tutta tua adatta al
timeframe 4H [...] massimo profitto e stabilita' da applicare anche su
candele mai viste")."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import optimize
from app.analysis.backtest import run_backtest
from app.analysis.strategies import AVAILABLE_STRATEGIES, CLAUDIO_4H, compute_claudio_signals

N = 2500
_R = np.random.default_rng(8)
_C = 100 * np.exp(np.cumsum(_R.normal(0, 0.012, N))) * (1 + 0.06 * np.sin(np.arange(N) / 15))
DF = pd.DataFrame({"open": _C * (1 + _R.normal(0, 0.002, N)), "high": _C * 1.008, "low": _C * 0.992,
                   "close": _C, "volume": 1.0}, index=pd.date_range("2023-01-01", periods=N, freq="4h", tz="UTC"))


def test_registered_but_hidden_until_approved():
    from app.analysis.strategies import STRATEGY_REGISTRY
    assert CLAUDIO_4H in STRATEGY_REGISTRY and CLAUDIO_4H not in AVAILABLE_STRATEGIES


def test_uses_no_future_candle():
    full = compute_claudio_signals(DF)
    for cut in (600, 1200, 1900):
        part = compute_claudio_signals(DF.iloc[:cut])
        pd.testing.assert_frame_equal(part, full.iloc[:cut])


def test_long_only_alternating_and_trades():
    s = compute_claudio_signals(DF, {"cl_rsi_os": 40, "cl_bb_mult": 1.8})
    assert not s["entry_short"].any() and not s["exit_short"].any()
    pos = 0
    for e, x in zip(s["entry_long"], s["exit_long"]):
        assert not (e and x)
        if e:
            assert pos == 0
            pos = 1
        if x:
            assert pos == 1
            pos = 0
    assert s["entry_long"].sum() >= 5


def test_time_stop_caps_the_holding():
    s = compute_claudio_signals(DF, {"cl_time_stop": 5, "cl_atr_stop": 50})
    i_e = np.flatnonzero(s["entry_long"].to_numpy())
    i_x = np.flatnonzero(s["exit_long"].to_numpy())
    for e in i_e:
        later = i_x[i_x > e]
        if len(later):
            assert later[0] - e <= 5


def test_backtest_and_search_run():
    bt = run_backtest(DF, {"cl_rsi_os": 40, "cl_bb_mult": 1.8}, {}, strategy_name=CLAUDIO_4H)
    assert bt.num_trades >= 3
    dims = (("cl_rsi_os", [25, 30, 35, 40]), ("cl_bb_mult", [1.8, 2.0, 2.2]), ("cl_atr_stop", [2.0, 3.0]))
    params, best, n, out = optimize.max_return_search_nd(
        CLAUDIO_4H, lambda p: run_backtest(DF, p, {}, strategy_name=CLAUDIO_4H), dims=dims, coarse=False)
    assert n == 24 and out and {c["kind"] for c in out} <= {"solid", "profitable", "solid+profitable"}
    assert set(params) >= {"cl_rsi_os", "cl_bb_mult", "cl_atr_stop"}


@pytest.mark.parametrize("coarse", [True])
def test_coarse_search_is_cheaper(coarse):
    dims = (("cl_rsi_os", list(range(25, 41))), ("cl_bb_mult", [1.8, 2.0, 2.2, 2.4]), ("cl_atr_stop", [2.0, 2.5, 3.0]))
    _, _, n, out = optimize.max_return_search_nd(
        CLAUDIO_4H, lambda p: run_backtest(DF, p, {}, strategy_name=CLAUDIO_4H), dims=dims, coarse=coarse)
    assert n < optimize.grid_size_nd(dims) and out
