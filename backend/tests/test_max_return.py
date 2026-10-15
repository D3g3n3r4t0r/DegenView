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
    calendar_years,
    max_return_search,
    max_return_size,
    years_without_trades,
)

GAB = "Gabriele (RSI+BB reversal)"
N = 300
_IDX = pd.date_range("2023-01-01", periods=N, freq="D", tz="UTC")
_C = 100 + np.cumsum(np.random.default_rng(3).normal(0, 2, N)) + 12 * np.sin(np.arange(N) / 6)
DF = pd.DataFrame({"open": _C, "high": _C + 1.5, "low": _C - 1.5, "close": _C,
                   "volume": np.full(N, 1000.0)}, index=_IDX)


def _bt(params):
    return run_backtest(DF, params, {}, strategy_name=GAB)


def test_every_pair_from_20_40_by_65_85_is_tried():
    # 15/10: the 4H ranges on every RSI+BB strategy (was 10-40 x 60-90)
    tried = []

    def spy(p):
        tried.append((p["rsi_oversold"], p["rsi_overbought"]))
        return _bt(p)

    _, _, evaluated, _ = max_return_search(GAB, spy)
    assert max_return_size() == 21 * 21 == evaluated
    assert set(tried) == {(o, b) for o in range(20, 41) for b in range(65, 86)}


def test_the_winner_is_the_highest_return_within_the_drawdown_cap():
    params, bt, _, top = max_return_search(GAB, _bt)
    brute = []
    for o in range(20, 41):
        for b in range(65, 86):
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


# Lorenzo, 13/10: "almeno un trade per anno solare testato [...] dal 2022 al
# 2026 deve aver ottenuto almeno un trade in ognuno di questi anni", and "i
# due migliori risultati anziche' uno solo".
def test_first_and_last_year_are_never_judged():
    # Lorenzo, 13/10: "dal 2022 al 2026 [...] solamente gli anni 2023, 2024 e 2025"
    idx = pd.date_range("2022-03-01", "2026-10-13", freq="D", tz="UTC")
    assert calendar_years(idx) == [2023, 2024, 2025]
    assert calendar_years(pd.date_range("2024-01-01", "2025-12-31", freq="D", tz="UTC")) == []


def test_a_year_without_trades_drops_the_result():
    years = calendar_years(DF.index)
    params, bt, _, top = max_return_search(GAB, _bt, years=years)
    assert len(top) <= 2
    for c in top:
        assert years_without_trades(c["backtest"], years) == []
    # the unfiltered winner, if it skips a year, must not survive the filter
    _, free_bt, _, _ = max_return_search(GAB, _bt)
    if years_without_trades(free_bt, years):
        assert bt.total_return_pct <= free_bt.total_return_pct


def test_two_best_results_are_returned():
    _, _, _, top = max_return_search(GAB, _bt)
    assert [c["rank"] for c in top] == [1, 2]
    assert top[0]["backtest"].total_return_pct >= top[1]["backtest"].total_return_pct


def test_enough_trades_in_total_forgive_an_empty_year(monkeypatch):
    # Lorenzo, 13/10: "se il totale dei trade pareggia o supera il numero
    # degli anni presi in esame allora il risultato deve essere considerato valido"
    from app.models import BacktestResult

    def fake(params):
        n = 3 if params["rsi_oversold"] == 20 else 2
        trades = [{"direction": "long", "entry_time": 1704067200 + i * 86400, "exit_time": 1704067200 + i * 86400 + 3600,
                   "entry_price": 1.0, "exit_price": 1.1, "pnl_pct": 10.0, "pnl_abs": 10.0, "equity_after": 1000.0}
                  for i in range(n)]       # all in 2024
        return BacktestResult.model_construct(
            total_return_pct=50.0 + params["rsi_oversold"] / 100, num_trades=n, max_drawdown_pct=-5.0,
            trades=[type("T", (), t)() for t in trades], win_rate_pct=100.0, profit_factor=None,
            sharpe_ratio=None, equity_curve=[])

    years = [2023, 2024, 2025]
    params, _, _, top = max_return_search(GAB, fake, years=years)
    assert params["rsi_oversold"] == 20          # 3 trades >= 3 years: valid despite 2023/2025
    assert all(c["backtest"].num_trades >= 3 for c in top)
    # "conta solo i trade fatti negli anni esaminati": the same 3 trades,
    # all in 2024, do not count when the judged years are 2025-2027
    with pytest.raises(ValueError):
        max_return_search(GAB, fake, years=[2025, 2026, 2027])


def test_in_candle_fills_rerun_only_the_best_pairs():
    # 14/10, "l'ottimizzazione sta procedendo molto lentamente": with fills
    # inside the candle every one of the then 961 backtests replayed the candles.
    exact_calls = []

    def exact(p):
        exact_calls.append(p)
        bt = _bt(p)
        return bt.model_copy(update={"total_return_pct": bt.total_return_pct + 1.0})

    params, bt, evaluated, top = max_return_search(GAB, exact, fast_backtest=_bt, refine=20)
    assert evaluated == 21 * 21
    assert 0 < len(exact_calls) <= 20
    fast_best = max_return_search(GAB, _bt)[1]
    assert bt.total_return_pct == pytest.approx(fast_best.total_return_pct + 1.0)
