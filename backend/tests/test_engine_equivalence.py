"""The week-2 engine speed-up must not move a single number (overhaul plan).

Live engine vs the frozen copy in tests/reference/engine_v1.py: same
events, same trades, same equity curve, field by field.
"""
import numpy as np
import pandas as pd
import pytest

from app.analysis import backtest as live_bt
from app.analysis import strategies as live_st
from tests.reference import engine_v1 as ref


def _ohlc(seed: int, n: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.03, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.03, n))
    idx = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(1, 100, n)}, index=idx)


def _signals(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 1000)
    n = len(df)
    return pd.DataFrame({c: rng.random(n) < 0.03 for c in
                         ("entry_long", "entry_short", "exit_long", "exit_short")}, index=df.index)


BPS = [
    {"initial_capital": 1000, "qty_pct_of_equity": 100, "commission_pct": 0, "slippage_pct": 0},
    {"initial_capital": 10000, "qty_pct_of_equity": 30, "commission_pct": 0.06, "slippage_pct": 0.02},
    {"initial_capital": 1000, "qty_pct_of_equity": 50, "stop_loss_pct": 4, "take_profit_pct": 9},
    {"initial_capital": 1000, "qty_pct_of_equity": 100, "fill_at": "next_open"},
    {"initial_capital": 1000, "qty_pct_of_equity": 100, "fill_at": "on_condition"},
]

# 15/10: the simple figures are computed after the loop from the trades the
# two engines already agree on (simple_stats); the reference engine predates them.
_SIMPLE = {"simple_return_pct", "simple_max_drawdown_pct", "avg_trade_pct", "median_trade_pct", "position_pct"}


def _core(bt):
    return {k: v for k, v in bt.model_dump().items() if k not in _SIMPLE}


@pytest.mark.parametrize("seed", range(6))
def test_events_identical(seed):
    df = _ohlc(seed)
    sig = _signals(df, seed)
    for closed in (False, True):
        a = live_st.confirmed_events(df, None, signals=sig, last_bar_closed=closed)
        b = ref.confirmed_events(df, None, signals=sig, last_bar_closed=closed)
        assert a[1] == b[1]
        assert [e.model_dump() for e in a[0]] == [e.model_dump() for e in b[0]]


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("bp", BPS)
def test_backtest_identical_on_given_signals(seed, bp):
    df = _ohlc(seed)
    sig = _signals(df, seed)
    a = live_bt.run_backtest(df, None, bp, signals=sig)
    b = ref.run_backtest(df, None, bp, signals=sig)
    assert _core(a) == _core(b)


@pytest.mark.parametrize("name", ["Lorenzo (trend-follower)", "Gabriele (RSI+BB reversal)",
                                  "Gabriele 2 (RSI+BB long/short)", "Accumulo / Distribuzione (long-term)"])
@pytest.mark.parametrize("seed", range(3))
def test_backtest_identical_on_real_strategies(name, seed):
    df = _ohlc(seed, 2500)
    for bp in BPS[:3]:
        a = live_bt.run_backtest(df, None, bp, strategy_name=name)
        b = ref.run_backtest(df, None, bp, strategy_name=name)
        assert _core(a) == _core(b)
