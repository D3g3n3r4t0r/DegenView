"""AlphaTrend 1H (long only): the strategy chosen in the 1H test environment
out of eighteen public GitHub / TradingView trend strategies (Lorenzo,
24/10: "solo long piu' uscita, quindi reversal")."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import btc_regime
from app.analysis.backtest import run_backtest
from app.analysis.optimize import grid_size, is_optimizable
from app.analysis.regime import STRATEGY_FAMILY
from app.analysis.strategies import (
    ALPHATREND_1H,
    ALPHATREND_DEFAULT_PARAMS,
    AVAILABLE_STRATEGIES,
    STRATEGY_REGISTRY,
    compute_alphatrend_signals,
)

N = 3000
IDX = pd.date_range("2024-01-01", periods=N, freq="1h", tz="UTC")


def _frame(seed=11, drift=0.0):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(drift, 0.008, N)) + 0.15 * np.sin(np.arange(N) / 90))
    return pd.DataFrame({"open": np.r_[c[0], c[:-1]], "high": c * (1 + np.abs(r.normal(0, 0.004, N))),
                         "low": c * (1 - np.abs(r.normal(0, 0.004, N))), "close": c,
                         "volume": 1000 * (1 + r.random(N))}, index=IDX)


@pytest.fixture(autouse=True)
def _clean():
    btc_regime.clear()
    yield
    btc_regime.clear()


def test_offered_in_the_menu_as_a_trend_strategy():
    assert ALPHATREND_1H in AVAILABLE_STRATEGIES
    assert STRATEGY_FAMILY[ALPHATREND_1H] == "trend"
    assert is_optimizable(ALPHATREND_1H)
    assert grid_size(ALPHATREND_1H) == 24 * 14
    assert ALPHATREND_DEFAULT_PARAMS["at_period"] == 17 and ALPHATREND_DEFAULT_PARAMS["at_coeff"] == 0.4


def test_long_only_entries_and_exits_alternate():
    sig = compute_alphatrend_signals(_frame())
    assert not sig["entry_short"].any() and not sig["exit_short"].any()
    assert sig["entry_long"].sum() > 10
    events = [1 if e else -1 for e, x in zip(sig["entry_long"], sig["exit_long"]) if e or x]
    assert events[0] == 1
    assert all(a != b for a, b in zip(events, events[1:]))     # never two buys in a row
    assert not (sig["entry_long"] & sig["exit_long"]).any()


def test_signals_only_look_back():
    df = _frame(seed=3)
    full = compute_alphatrend_signals(df)
    cut = compute_alphatrend_signals(df.iloc[:2000])
    assert (full.iloc[:2000].to_numpy() == cut.to_numpy()).all()


def test_rsi_switch_ignores_volumes():
    df = _frame(seed=5)
    other = df.assign(volume=df["volume"].to_numpy()[::-1])
    a = compute_alphatrend_signals(df, {"at_use_rsi": True})
    b = compute_alphatrend_signals(other, {"at_use_rsi": "true"})
    assert (a.to_numpy() == b.to_numpy()).all()
    assert not (compute_alphatrend_signals(df).to_numpy() == compute_alphatrend_signals(other).to_numpy()).all()


def test_rides_a_trend_and_runs_in_the_engine():
    df = _frame(seed=8, drift=0.0015)
    bt = run_backtest(df, {}, {"initial_capital": 1000, "qty_pct_of_equity": 100},
                      strategy_name=ALPHATREND_1H)
    assert bt.num_trades >= 1 and all(t.direction == "long" for t in bt.trades)
    assert bt.total_return_pct > 0


def test_btc_filter_and_its_exit_close_the_long_when_btc_turns():
    days = pd.date_range("2023-01-01", "2024-12-31", freq="D", tz="UTC")
    turn = days.searchsorted(pd.Timestamp("2024-02-15", tz="UTC"))
    btc_regime.set_closes(pd.Series(np.r_[np.linspace(20_000, 60_000, turn),
                                          np.linspace(60_000, 10_000, len(days) - turn)], index=days), pin=True)
    df = _frame(seed=8, drift=0.0015)
    on = STRATEGY_REGISTRY[ALPHATREND_1H](df, {"btc_filter": True, "btc_filter_exit": True})
    up = btc_regime.up_mask(df.index)
    assert not up.all() and up.any()
    assert not on["entry_long"].to_numpy()[~up].any()          # no buy while BTC is down
    assert on["exit_long"].to_numpy()[~up].all()               # and out
