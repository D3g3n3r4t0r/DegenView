"""Segnalazione 6da2bba6: chart strategy markers vs. backtest trade count.

On the same candles, every entry/flip marker is a backtest trade, except a
last entry that is still open. The counts shown on the site differ only
because the deep backtest reads more candles than the chart (backtest_candles
vs ltf_candles), and the chart note says so."""

import numpy as np
import pandas as pd
import pytest

from app.analysis import btc_regime
from app.analysis.backtest import run_backtest
from app.analysis.strategies import AVAILABLE_STRATEGIES, build_strategy_state
from app.config import settings


@pytest.fixture(autouse=True)
def _btc():
    """RSI+BB BTC band reads BTC's weekly band: a BTC that rises and falls."""
    idx = pd.date_range("2019-01-01", "2024-12-31", freq="D", tz="UTC")
    btc_regime.set_closes(pd.Series(30_000 + 15_000 * np.sin(np.arange(len(idx)) / 120), index=idx), pin=True)
    yield
    btc_regime.clear()


def _df(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    e = rng.normal(0, 0.03, n)
    for i in range(1, n):
        r[i] = 0.3 * r[i - 1] + e[i]
    close = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame(
        {"open": close, "high": close * 1.02, "low": close * 0.98,
         "close": close, "volume": np.full(n, 1e6)},
        index=pd.date_range("2020-01-01", periods=n, freq="D"),
    )


def _entries(state) -> tuple[int, bool]:
    n = sum(1 for s in state.signals if s.type.startswith(("entry", "flip")))
    still_open = bool(state.signals) and not state.signals[-1].type.startswith("exit")
    return n, still_open


@pytest.mark.parametrize("strategy", list(AVAILABLE_STRATEGIES))
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_markers_match_trades_on_the_same_candles(strategy, seed):
    df = _df(1200, seed)
    entries, still_open = _entries(build_strategy_state(strategy, df, {}))
    bt = run_backtest(df, {}, {}, strategy_name=strategy)
    assert bt.num_trades == entries - int(still_open)


def test_deeper_backtest_counts_trades_before_the_chart():
    strategy = next(iter(AVAILABLE_STRATEGIES))
    deep = _df(2000, 3)
    chart = deep.iloc[-1200:]
    entries, still_open = _entries(build_strategy_state(strategy, chart, {}))
    bt = run_backtest(deep, {}, {}, strategy_name=strategy)
    t0 = int(chart.index[0].timestamp())
    before = sum(1 for t in bt.trades if t.entry_time < t0)
    assert before > 0
    assert bt.num_trades > entries - int(still_open)
    assert settings.backtest_candles > settings.ltf_candles
