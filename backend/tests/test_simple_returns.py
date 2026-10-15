"""Simple vs compounded (Lorenzo, 15/10: "il risultato percentuale puro di
ogni trade [...] e poi sommate", "Max Return deve scegliere il migliore in
base al rendimento semplice")."""

from __future__ import annotations

import pytest

from app.analysis.backtest import simple_stats
from app.models import BacktestTrade


def _trades(pcts, capital=1000.0, q=1.0):
    eq, out = capital, []
    for p in pcts:
        pnl = eq * q * p / 100
        eq += pnl
        out.append(BacktestTrade(direction="long", entry_time=0, exit_time=1, entry_price=1, exit_price=1,
                                 pnl_pct=p, pnl_abs=pnl, equity_after=eq))
    return out, eq


def test_simple_is_the_sum_compounded_is_the_product():
    t, eq = _trades([10, 10])
    s = simple_stats(t, 100)
    assert s["simple_return_pct"] == pytest.approx(20.0)
    assert (eq / 1000 - 1) * 100 == pytest.approx(21.0)
    assert s["avg_trade_pct"] == pytest.approx(10.0) and s["median_trade_pct"] == pytest.approx(10.0)


def test_plus_fifty_minus_fifty():
    t, eq = _trades([50, -50])
    s = simple_stats(t, 100)
    assert s["simple_return_pct"] == pytest.approx(0.0)          # same stake: back to the start
    assert (eq / 1000 - 1) * 100 == pytest.approx(-25.0)          # reinvested: -25%
    assert s["simple_max_drawdown_pct"] == pytest.approx(50.0)    # from +50 to 0, in % of the start


def test_position_size_scales_the_stake():
    t, _ = _trades([10, -5, 20], q=0.3)
    s = simple_stats(t, 30)
    assert s["avg_trade_pct"] == pytest.approx(25 / 3)            # % of the position
    assert s["simple_return_pct"] == pytest.approx(25 * 0.3)      # % of the capital


def test_no_trades():
    assert simple_stats([], 100)["simple_return_pct"] == 0.0
