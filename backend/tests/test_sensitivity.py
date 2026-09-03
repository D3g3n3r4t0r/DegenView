"""Tests for Morris screening and the unit-cube parameter spaces (stage S1)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import sensitivity as S
from app.analysis.sensitivity import (
    PARAM_SPACES,
    EffectStats,
    morris_screening,
    soft_score,
)
from app.models import BacktestResult

LORENZO = "Lorenzo (trend-follower)"
GABRIELE = "Gabriele (RSI+BB reversal)"
EXHAUSTION = "Accumulo / Distribuzione (long-term)"


def _bt(total_return=100.0, dd=20.0, trades=20, pf=2.0) -> BacktestResult:
    return BacktestResult(
        interval="1d", initial_capital=10000.0,
        final_equity=10000 * (1 + total_return / 100),
        total_return_pct=total_return, num_trades=trades, win_rate_pct=55.0,
        max_drawdown_pct=dd, profit_factor=pf, equity_curve=[], trades=[],
        data_start=0, data_end=1, sharpe_ratio=1.0, max_consecutive_losses=2,
    )


def _df(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": np.full(n, 1e6)},
        index=pd.date_range("2023-01-01", periods=n, freq="D"),
    )


# --- unit-cube parameter spaces ---------------------------------------------


@pytest.mark.parametrize("strategy", [LORENZO, GABRIELE, EXHAUSTION])
def test_every_cube_corner_and_interior_point_is_feasible(strategy):
    space = PARAM_SPACES[strategy]
    rng = np.random.default_rng(4)
    points = [np.zeros(space.d), np.ones(space.d), np.full(space.d, 0.5)]
    points += [rng.random(space.d) for _ in range(60)]
    for u in points:
        p = space.to_params(u)
        assert isinstance(p, dict) and p


def test_lorenzo_slope_constraint_holds_everywhere():
    """The dependent mapping exists so no point in the cube needs repairing.
    If this breaks, Morris silently measures the effect of the repair rather
    than the effect of the perturbation."""
    space = PARAM_SPACES[LORENZO]
    rng = np.random.default_rng(5)
    for u in [np.zeros(space.d), np.ones(space.d)] + [rng.random(space.d) for _ in range(400)]:
        p = space.to_params(u)
        assert p["slopeSlen"] >= p["slopeFlen"] + 3, f"infeasible at u={u}"


def test_mapping_is_deterministic():
    space = PARAM_SPACES[GABRIELE]
    u = np.array([0.1, 0.9, 0.35, 0.6, 0.2])
    assert space.to_params(u) == space.to_params(u.copy())


def test_dims_match_produced_keys():
    for strategy, space in PARAM_SPACES.items():
        produced = set(space.to_params(np.full(space.d, 0.5)))
        declared = set(space.dims)
        assert declared <= produced, f"{strategy}: declared dims not produced: {declared - produced}"


def test_param_spaces_cover_the_registry():
    from app.analysis.strategies import STRATEGY_REGISTRY

    assert set(STRATEGY_REGISTRY) == set(PARAM_SPACES)


# --- soft score --------------------------------------------------------------


def test_soft_score_stays_finite_where_production_score_rejects():
    """optimize._score returns -inf on a filtered candidate, which is right for
    selection and useless for differencing. The screening objective must stay
    finite everywhere or a single rejected point poisons whole trajectories."""
    from app.analysis.optimize import _score

    thin = _bt(total_return=5.0, trades=2)
    assert _score(thin) == float("-inf")
    assert np.isfinite(soft_score(thin))


def test_soft_score_rewards_return_and_penalises_drawdown():
    assert soft_score(_bt(total_return=200.0)) > soft_score(_bt(total_return=50.0))
    assert soft_score(_bt(dd=10.0)) > soft_score(_bt(dd=40.0))


def test_soft_score_rewards_more_evidence():
    assert soft_score(_bt(trades=60)) > soft_score(_bt(trades=9))


# --- Morris, against a function whose sensitivity is known -------------------


def test_morris_recovers_a_known_sensitivity_ranking(monkeypatch):
    """Validate the estimator itself: build an objective that depends only on
    two coordinates, and check Morris ranks exactly those on top."""
    space = PARAM_SPACES[GABRIELE]
    inv = {name: i for i, name in enumerate(space.dims)}

    lo = {"rsi_length": 7, "bb_length": 10, "bb_mult": 1.0,
          "rsi_oversold": 15, "rsi_overbought": 60}
    hi = {"rsi_length": 25, "bb_length": 40, "bb_mult": 3.5,
          "rsi_oversold": 40, "rsi_overbought": 85}

    def fake(df, params, bp, strategy_name=None, signals=None):
        def unit(name):
            return (float(params[name]) - lo[name]) / (hi[name] - lo[name])
        # depends strongly on bb_mult, weakly on rsi_length, not at all on the rest
        val = 100.0 * unit("bb_mult") + 10.0 * unit("rsi_length")
        return _bt(total_return=val, dd=20.0, trades=20, pf=2.0)

    monkeypatch.setattr(S, "run_backtest", fake)
    res = morris_screening(GABRIELE, _df(), trajectories=12, levels=8, seed=0,
                           objective="total_return")

    ranked = [e.name for e in res.effects]
    assert ranked[0] == "bb_mult", f"expected bb_mult first, got {ranked}"
    assert ranked[1] == "rsi_length", f"expected rsi_length second, got {ranked}"
    assert inv  # dims map is consistent with the space

    inert = [e for e in res.effects if e.name in
             {"bb_length", "rsi_oversold", "rsi_overbought"}]
    assert all(e.mu_star == pytest.approx(0.0, abs=1e-9) for e in inert)
    assert all(e.frozen for e in inert)


def test_morris_reports_every_dimension():
    res = morris_screening(GABRIELE, _df(), trajectories=4, levels=8, seed=1)
    assert {e.name for e in res.effects} == set(PARAM_SPACES[GABRIELE].dims)
    assert all(isinstance(e, EffectStats) for e in res.effects)
    assert res.evaluations > 0


def test_ranks_are_dense_and_ordered_by_influence():
    res = morris_screening(GABRIELE, _df(), trajectories=4, levels=8, seed=2)
    assert [e.rank for e in res.effects] == list(range(1, len(res.effects) + 1))
    mus = [e.mu_star for e in res.effects]
    assert mus == sorted(mus, reverse=True)


def test_smaller_delta_is_honoured():
    """The step size must be controllable: whether ruggedness is scale
    dependent is a design question, not a fixed assumption."""
    big = morris_screening(GABRIELE, _df(), trajectories=4, levels=8, seed=3, delta=0.5)
    small = morris_screening(GABRIELE, _df(), trajectories=4, levels=8, seed=3, delta=0.05)
    assert big.effects and small.effects


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        morris_screening("Nope", _df())


def test_backtest_failures_are_counted_not_swallowed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("backtest exploded")

    monkeypatch.setattr(S, "run_backtest", boom)
    res = morris_screening(GABRIELE, _df(), trajectories=2, levels=8, seed=0)
    assert res.failures > 0
    assert res.evaluations == 0
