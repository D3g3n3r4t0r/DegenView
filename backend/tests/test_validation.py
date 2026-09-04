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


# --- allineamento delle curve per il PBO ----------------------------------
#
# Il PBO vuole una matrice T x N confrontabile riga per riga. Le curve di equity
# nascono per trade, quindi ognuna ha i suoi istanti: accostarle per posizione
# confronterebbe il terzo trade di una configurazione con il terzo di un'altra,
# avvenuto mesi dopo, e la misura leggerebbe quel disallineamento invece della
# sovra-ottimizzazione. Questi test bloccano quel modo di sbagliare.


def _grid(n, step=86400, start=1_600_000_000):
    return [start + i * step for i in range(n)]


def test_curves_with_different_lengths_produce_one_matrix():
    from app.analysis.validation import align_equity_curves

    g = _grid(10)
    a = [(g[0], 100.0), (g[3], 110.0), (g[7], 120.0)]
    b = [(g[0], 100.0), (g[1], 95.0), (g[8], 130.0)]
    m = align_equity_curves([a, b], g)
    assert m.shape == (9, 2)


def test_equity_is_held_flat_between_trades_not_interpolated():
    """Fra un trade e il successivo la posizione e' chiusa: interpolare
    inventerebbe movimenti mai avvenuti."""
    import numpy as np

    from app.analysis.validation import align_equity_curves

    g = _grid(6)
    curve = [(g[0], 100.0), (g[3], 110.0)]
    m = align_equity_curves([curve, [(g[0], 100.0), (g[2], 90.0), (g[4], 95.0)]], g)
    col = m[:, 0]
    assert np.count_nonzero(np.abs(col) > 1e-12) == 1, "un solo salto, non una rampa"
    assert col[2] == pytest.approx(0.10)


def test_a_trade_lands_on_the_grid_step_that_contains_it():
    from app.analysis.validation import align_equity_curves

    g = _grid(5)
    curve = [(g[0], 100.0), (g[1] + 3600, 105.0)]   # a metà fra due punti
    other = [(g[0], 100.0), (g[3], 80.0)]
    m = align_equity_curves([curve, other], g)
    assert m[0, 0] == pytest.approx(0.0)
    assert m[1, 0] == pytest.approx(0.05), "conta il punto successivo, non quello in corso"


def test_flat_candidates_are_dropped():
    """Una colonna piatta pareggia con qualsiasi altra e falserebbe il
    confronto fra le due metà."""
    from app.analysis.validation import align_equity_curves

    g = _grid(8)
    flat = [(g[0], 100.0), (g[7], 100.0)]
    moving = [(g[0], 100.0), (g[2], 120.0), (g[5], 90.0)]
    m = align_equity_curves([flat, moving], g)
    assert m.shape[1] == 1


def test_no_usable_curve_gives_an_empty_matrix_not_a_crash():
    from app.analysis.validation import align_equity_curves

    assert align_equity_curves([], _grid(5)).size == 0
    assert align_equity_curves([[(1, 100.0)]], _grid(5)).size == 0


def test_the_aligned_matrix_feeds_pbo():
    import numpy as np

    from app.analysis.validation import align_equity_curves, probability_of_backtest_overfitting

    rng = np.random.default_rng(3)
    g = _grid(400)
    curves = []
    for k in range(8):
        eq, v = [], 100.0
        for i in range(0, 400, 4):
            v *= 1 + rng.normal(0.001 * (k - 4) / 4, 0.02)
            eq.append((g[i], v))
        curves.append(eq)
    m = align_equity_curves(curves, g)
    res = probability_of_backtest_overfitting(m)
    assert res.pbo is not None
    assert 0.0 <= res.pbo <= 1.0
    assert res.n_candidates == m.shape[1]
