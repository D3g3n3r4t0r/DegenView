"""Tests for the end-to-end optimisation pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import plateau as P
from app.analysis.pipeline import (
    _MIN_VALIDATION_TRADES,
    _three_way_split,
    pipeline_top_candidates,
    run_pipeline,
)
from app.models import BacktestResult

LORENZO = "Lorenzo (trend-follower)"
GABRIELE = "Gabriele (RSI+BB reversal)"


def _bt(total_return=100.0, dd=20.0, trades=20, pf=2.0) -> BacktestResult:
    return BacktestResult(
        interval="1d", initial_capital=10000.0,
        final_equity=10000 * (1 + total_return / 100),
        total_return_pct=total_return, num_trades=trades, win_rate_pct=55.0,
        max_drawdown_pct=dd, profit_factor=pf, equity_curve=[], trades=[],
        data_start=0, data_end=1, sharpe_ratio=1.0, max_consecutive_losses=2,
    )


def _df(n: int = 900, phi: float = 0.25, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    e = rng.normal(0, 0.02, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]
    close = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": np.full(n, 1e6)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


# --- the split ---------------------------------------------------------------


def test_split_is_three_disjoint_contiguous_slices():
    df = _df(1000)
    a, b, c = _three_way_split(df)
    assert len(a) + len(b) + len(c) == len(df)
    assert a.index[-1] < b.index[0] < b.index[-1] < c.index[0]


def test_split_keeps_a_usable_test_slice_on_short_series():
    a, b, c = _three_way_split(_df(200))
    assert len(a) >= 1 and len(b) > 0 and len(c) > 0


# --- branch selection --------------------------------------------------------


def _fake_branch_backtests(bias: dict):
    """run_backtest stub whose result depends on which branch it is called for.

    Keyed on the switch combination, so each branch can be given a different
    in-sample and validation profile.
    """
    def fake(df, params, bp, strategy_name=None, signals=None):
        key = (bool(params.get("trendfilter")), bool(params.get("volatilityfilter")))
        is_ret, val_ret, trades = bias[key]
        # The validation and test slices are shorter than training; use length
        # to tell which slice this call is scoring.
        return _bt(total_return=is_ret if len(df) > 400 else val_ret,
                   trades=trades)
    return fake


def test_a_richer_branch_does_not_win_on_in_sample_score_alone(monkeypatch):
    """Capacity inflates in-sample score whether or not it is worth anything.
    The 8-parameter branch is given a much better training result and a worse
    validation one; the pipeline must not be fooled."""
    bias = {
        (False, False): (100.0, 30.0, 40),   # simple: modest train, good validation
        (False, True): (300.0, -10.0, 40),
        (True, False): (300.0, -10.0, 40),
        (True, True): (900.0, -20.0, 40),    # richest: huge train, negative validation
    }
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(bias))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(bias))

    r = run_pipeline(LORENZO, _df(900), max_evals_per_branch=200, seed=0)
    assert r.chosen_branch == "trendfilter=False volatilityfilter=False"


def test_falls_back_to_parsimony_when_validation_has_no_evidence(monkeypatch):
    """A one-trade validation return is an anecdote. When no branch clears the
    trade floor the choice must fall back to reproducibility and fewer
    parameters, and must say that it did."""
    thin = {k: (100.0, 50.0, 1) for k in
            [(False, False), (False, True), (True, False), (True, True)]}
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(thin))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(thin))

    r = run_pipeline(LORENZO, _df(900), max_evals_per_branch=200, seed=0)
    assert any("too few trades" in n for n in r.notes)
    assert r.chosen_branch == "trendfilter=False volatilityfilter=False"


def test_validation_evidence_is_used_when_it_exists(monkeypatch):
    rich = {
        (False, False): (100.0, 5.0, 40),
        (False, True): (100.0, 80.0, 40),
        (True, False): (100.0, 5.0, 40),
        (True, True): (100.0, 5.0, 40),
    }
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(rich))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(rich))

    r = run_pipeline(LORENZO, _df(900), max_evals_per_branch=200, seed=0)
    assert any("validation evidence" in n for n in r.notes)
    assert r.chosen_branch == "trendfilter=False volatilityfilter=True"


def test_min_validation_trades_is_a_real_floor():
    assert _MIN_VALIDATION_TRADES >= 2


# --- reporting ---------------------------------------------------------------


def test_result_carries_the_gate_decision(monkeypatch):
    flat = {k: (100.0, 20.0, 30) for k in
            [(False, False), (False, True), (True, False), (True, True)]}
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(flat))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(flat))

    r = run_pipeline(LORENZO, _df(900, phi=0.25), max_evals_per_branch=200, seed=0)
    assert r.gate is not None
    assert isinstance(r.gate.passed, bool)
    assert r.gate.reason
    assert r.series_stats["n"] > 0


def test_a_failed_gate_is_reported_not_hidden(monkeypatch):
    flat = {k: (100.0, 20.0, 30) for k in
            [(False, False), (False, True), (True, False), (True, True)]}
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(flat))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(flat))

    # phi=0 is a random walk: no strategy family has an edge to find.
    r = run_pipeline(LORENZO, _df(900, phi=0.0, seed=3), max_evals_per_branch=200, seed=0)
    if not r.gate.passed:
        assert any("gate did NOT pass" in n for n in r.notes)


def test_sampled_branches_are_flagged_as_not_reproducible(monkeypatch):
    """A branch too large to enumerate reports the maximum of a random subset,
    which carries exactly the selection bias this pipeline removes. The caller
    has to be told, because that result is not reproducible."""
    def varying(df, params, bp, strategy_name=None, signals=None):
        # Vary with the parameters so boundary detection finds real cells; a
        # constant objective would yield one cell per axis and always enumerate.
        v = (params.get("len", 50) % 7) * 13 + (params.get("slopeFlen", 5) % 5) * 9
        return _bt(total_return=float(v), trades=30)

    monkeypatch.setattr(P, "run_backtest", varying)
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", varying)

    r = run_pipeline(LORENZO, _df(900), max_evals_per_branch=5, seed=0)
    assert r.deterministic is False
    assert any("sampled" in n for n in r.notes)


def test_top_candidates_marks_the_chosen_branch(monkeypatch):
    flat = {k: (100.0, 20.0, 30) for k in
            [(False, False), (False, True), (True, False), (True, True)]}
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(flat))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(flat))

    r = run_pipeline(LORENZO, _df(900), max_evals_per_branch=200, seed=0)
    rows = pipeline_top_candidates(r)
    assert rows
    assert sum(1 for row in rows if row["chosen"]) == 1
    assert all("params" in row and "dims" in row for row in rows)


def test_pipeline_is_seed_independent_when_every_branch_enumerates(monkeypatch):
    """The property the whole exercise exists to obtain."""
    flat = {k: (100.0, 20.0, 30) for k in
            [(False, False), (False, True), (True, False), (True, True)]}
    monkeypatch.setattr(P, "run_backtest", _fake_branch_backtests(flat))
    import app.analysis.pipeline as PL
    monkeypatch.setattr(PL, "run_backtest", _fake_branch_backtests(flat))

    runs = [run_pipeline(GABRIELE, _df(900), max_evals_per_branch=100000, seed=s)
            for s in range(3)]
    assert all(r.deterministic for r in runs)
    assert all(r.params == runs[0].params for r in runs)
    assert all(r.chosen_branch == runs[0].chosen_branch for r in runs)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        run_pipeline("Nope", _df(300))
