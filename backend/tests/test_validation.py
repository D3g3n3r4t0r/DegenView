"""Tests for PBO and the Deflated Sharpe Ratio (stage S5).

Both measures are checked against constructed cases where the right answer is
known independently: pure noise, a planted edge, and the same returns judged
after different numbers of attempts.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.validation import (
    deflated_sharpe_ratio,
    periods_per_year_from_curve,
    probability_of_backtest_overfitting,
    returns_from_equity_curve,
)


# --- PBO ---------------------------------------------------------------------


def test_pbo_is_high_when_every_candidate_is_noise():
    """With nothing to find, the in-sample winner is whichever column got
    luckiest in-sample, and luck does not carry to the complement. A procedure
    behaving this way has no value, and PBO must say so."""
    rng = np.random.default_rng(0)
    r = probability_of_backtest_overfitting(rng.normal(0, 0.01, (600, 40)), n_blocks=10)
    assert r.pbo is not None
    assert r.pbo > 0.30
    assert not r.acceptable


def test_pbo_is_low_when_one_candidate_has_a_real_edge():
    rng = np.random.default_rng(0)
    m = rng.normal(0, 0.01, (600, 40))
    m[:, 7] += 0.0025
    r = probability_of_backtest_overfitting(m, n_blocks=10)
    assert r.pbo is not None
    assert r.pbo < 0.10
    assert r.acceptable


def test_pbo_is_deterministic():
    """The thinning of the split set must not depend on a seed, or the measure
    would carry the variability it is meant to detect."""
    rng = np.random.default_rng(3)
    m = rng.normal(0, 0.01, (400, 12))
    a = probability_of_backtest_overfitting(m, n_blocks=8)
    b = probability_of_backtest_overfitting(m, n_blocks=8)
    assert a.pbo == b.pbo and a.n_splits == b.n_splits


def test_pbo_reports_when_it_cannot_be_computed():
    short = probability_of_backtest_overfitting(np.zeros((10, 5)), n_blocks=12)
    assert short.pbo is None and "too short" in short.note

    single = probability_of_backtest_overfitting(np.zeros((600, 1)), n_blocks=8)
    assert single.pbo is None and "two candidates" in single.note


def test_pbo_respects_the_split_cap():
    rng = np.random.default_rng(5)
    r = probability_of_backtest_overfitting(rng.normal(0, 0.01, (900, 8)),
                                            n_blocks=16, max_splits=200)
    assert r.n_splits <= 200


# --- DSR ---------------------------------------------------------------------


def test_more_attempts_deflate_the_same_result():
    """The core of the measure: an identical return stream is worth less as
    evidence when it was picked out of more candidates."""
    # A deliberately unambiguous edge, so the assertion tests the deflation
    # and not whether this particular draw happened to look good.
    rng = np.random.default_rng(1)
    r = rng.normal(0.0025, 0.01, 800)
    one = deflated_sharpe_ratio(r, n_trials=1)
    many = deflated_sharpe_ratio(r, n_trials=5000)
    assert one.sharpe == pytest.approx(many.sharpe)          # same raw Sharpe
    assert many.sharpe_threshold > one.sharpe_threshold      # higher bar
    assert many.deflated < one.deflated                      # less credit
    assert one.acceptable, f"a clear edge tried once should survive: {one}"
    assert not many.acceptable, f"the same edge out of 5000 tries should not: {many}"


def test_threshold_grows_with_the_number_of_trials():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0008, 0.01, 800)
    thresholds = [deflated_sharpe_ratio(r, n_trials=n).sharpe_threshold
                  for n in (2, 50, 500, 5000)]
    assert thresholds == sorted(thresholds)


def test_a_lucky_noise_series_does_not_survive_deflation():
    rng = np.random.default_rng(11)
    best = max((rng.normal(0, 0.01, 300) for _ in range(200)),
               key=lambda x: x.mean() / (x.std() + 1e-12))
    d = deflated_sharpe_ratio(best, n_trials=200)
    assert d.deflated is not None
    assert not d.acceptable


def test_dsr_reports_rather_than_guesses_on_thin_input():
    assert deflated_sharpe_ratio(np.array([0.01, 0.02]), n_trials=10).sharpe is None
    flat = deflated_sharpe_ratio(np.zeros(50), n_trials=10)
    assert flat.deflated is None and "zero variance" in flat.note


def test_dsr_records_the_distribution_shape_it_corrected_for():
    rng = np.random.default_rng(4)
    d = deflated_sharpe_ratio(rng.normal(0.001, 0.01, 500), n_trials=100)
    assert d.skew is not None and d.kurtosis is not None


# --- equity curve conversion -------------------------------------------------


def test_returns_from_equity_curve():
    out = returns_from_equity_curve([(0, 100.0), (1, 110.0), (2, 99.0)])
    assert out == pytest.approx([0.10, -0.10])


def test_returns_from_equity_curve_handles_degenerate_input():
    assert returns_from_equity_curve([]).size == 0
    assert returns_from_equity_curve([(0, 100.0)]).size == 0
    assert returns_from_equity_curve([(0, 0.0), (1, 50.0)]).size == 0


# --- annualisation from the curve's own clock --------------------------------


def test_periods_per_year_comes_from_the_curve_not_a_constant():
    """Equity-curve steps are TRADES, not sessions. Annualising 28 trades over
    two and a half years with the 252 of daily returns assumes the strategy
    traded every session, inflating the Sharpe about fourfold — and the
    deflation threshold is computed on the same wrong scale."""
    day = 86400
    curve = [(int(i * 860 / 28) * day, 10000.0 * (1.02 ** i)) for i in range(29)]
    ppy = periods_per_year_from_curve(curve)
    assert 8 < ppy < 20, f"28 trades over 860 days should be ~12/yr, got {ppy}"


def test_annualisation_is_capped_for_degenerate_curves():
    for curve in ([], [(0, 100.0)], [(0, 100.0), (1, 101.0)]):
        assert periods_per_year_from_curve(curve) == 252.0
    same_day = [(0, 100.0), (100, 101.0), (200, 102.0), (300, 103.0)]
    assert periods_per_year_from_curve(same_day) == 252.0


def test_correcting_the_scale_changes_the_number_not_the_verdict():
    day = 86400
    rng = np.random.default_rng(0)
    eq = [10000.0]
    for _ in range(28):
        eq.append(eq[-1] * (1 + rng.normal(0.02, 0.06)))
    curve = [(int(i * 860 / 28) * day, v) for i, v in enumerate(eq)]
    r = returns_from_equity_curve(curve)
    ppy = periods_per_year_from_curve(curve)

    wrong = deflated_sharpe_ratio(r, n_trials=3802, periods_per_year=252)
    right = deflated_sharpe_ratio(r, n_trials=3802, periods_per_year=ppy)
    assert wrong.sharpe > right.sharpe * 3
    assert wrong.acceptable == right.acceptable
