"""
Certification of a search result (pipeline stage S5).

Everything upstream tries to select well. This module answers a different
question: given that a selection was made over many candidates, how much of
the winner's apparent quality is selection itself?

Two measures, both from the backtest-overfitting literature:

  PBO — Probability of Backtest Overfitting, via combinatorially symmetric
        cross-validation. Splits the period into S blocks, and for every way of
        assigning half of them to a training half, checks whether the
        configuration that wins in training also ranks above median on the
        complement. PBO is the fraction of splits where it does not. It judges
        the SELECTION PROCEDURE rather than any single configuration, which is
        the right unit: a procedure whose winners land below median half the
        time is worthless however good its winner looks.

  DSR — Deflated Sharpe Ratio. The expected maximum Sharpe under no skill grows
        with the number of configurations tried, so an unadjusted Sharpe from a
        search over thousands of candidates is not comparable to one from a
        single hypothesis. DSR is the probability that the observed Sharpe
        exceeds what selection alone would have produced.

Cost is dominated by building the returns matrix once. Every CSCV split after
that is arithmetic on rows of that matrix, not a re-optimisation — which is
what makes evaluating thousands of splits affordable.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np

_NORM = statistics.NormalDist()
_EULER = 0.5772156649015329


@dataclass
class PBOResult:
    pbo: float | None
    n_splits: int
    n_candidates: int
    n_blocks: int
    median_logit: float | None = None
    note: str = ""

    @property
    def acceptable(self) -> bool:
        return self.pbo is not None and self.pbo < 0.20


@dataclass
class DSRResult:
    sharpe: float | None
    deflated: float | None          # probability the Sharpe survives deflation
    sharpe_threshold: float | None  # expected max Sharpe under no skill
    n_trials: int
    skew: float | None = None
    kurtosis: float | None = None
    note: str = ""

    @property
    def acceptable(self) -> bool:
        return self.deflated is not None and self.deflated > 0.95


def _annualised_sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 3:
        return None
    sd = float(np.std(r, ddof=1))
    if sd <= 0:
        return None
    return float(np.mean(r) / sd * math.sqrt(periods_per_year))


def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray,
    n_blocks: int = 12,
    max_splits: int = 4000,
) -> PBOResult:
    """CSCV over a T x N matrix of per-period returns, one column per candidate.

    The matrix is built once by the caller; each split here is a row-subset
    aggregation, so thousands of splits cost arithmetic rather than thousands
    of re-optimisations.
    """
    m = np.asarray(returns_matrix, dtype=float)
    if m.ndim != 2 or m.shape[1] < 2:
        return PBOResult(None, 0, 0 if m.ndim != 2 else m.shape[1], n_blocks,
                         note="at least two candidates are required")
    t, n = m.shape
    if n_blocks % 2 != 0:
        n_blocks -= 1
    if n_blocks < 4 or t < n_blocks * 3:
        return PBOResult(None, 0, n, n_blocks,
                         note=f"series too short for {n_blocks} blocks ({t} periods)")

    bounds = np.linspace(0, t, n_blocks + 1).astype(int)
    blocks = [np.arange(bounds[i], bounds[i + 1]) for i in range(n_blocks)]

    half = n_blocks // 2
    all_splits = list(combinations(range(n_blocks), half))
    if len(all_splits) > max_splits:
        # Deterministic thinning: take an evenly spaced subset rather than a
        # random sample, so the measure does not itself depend on a seed.
        step = len(all_splits) / max_splits
        all_splits = [all_splits[int(i * step)] for i in range(max_splits)]

    logits: list[float] = []
    for train_idx in all_splits:
        train_rows = np.concatenate([blocks[i] for i in train_idx])
        test_rows = np.concatenate([blocks[i] for i in range(n_blocks) if i not in train_idx])

        train_perf = np.nansum(m[train_rows], axis=0)
        test_perf = np.nansum(m[test_rows], axis=0)
        if not np.any(np.isfinite(train_perf)):
            continue
        winner = int(np.nanargmax(train_perf))

        # Relative rank of the training winner within the out-of-sample results.
        order = np.argsort(np.argsort(test_perf))
        rank = float(order[winner] + 1) / (n + 1)
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))

    if not logits:
        return PBOResult(None, 0, n, n_blocks, note="no usable split")

    pbo = float(np.mean([1.0 if x < 0 else 0.0 for x in logits]))
    return PBOResult(pbo=pbo, n_splits=len(logits), n_candidates=n,
                     n_blocks=n_blocks, median_logit=float(np.median(logits)))


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int,
    trial_sharpe_variance: float | None = None,
    periods_per_year: int = 252,
) -> DSRResult:
    """Bailey & Lopez de Prado (2014).

    n_trials is the number of configurations the search actually evaluated —
    understating it inflates the result, which is the failure mode the measure
    exists to prevent, so the caller should pass the true count rather than the
    size of the shortlist it kept.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 8:
        return DSRResult(None, None, None, n_trials, note="too few observations")

    sr = _annualised_sharpe(r, periods_per_year)
    if sr is None:
        return DSRResult(None, None, None, n_trials, note="zero variance")

    t = r.size
    mean, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    skew = float(np.mean(((r - mean) / sd) ** 3))
    kurt = float(np.mean(((r - mean) / sd) ** 4))

    # Expected maximum Sharpe under the null of no skill across n_trials.
    n = max(int(n_trials), 2)
    var_sr = trial_sharpe_variance if trial_sharpe_variance is not None else (1.0 + 0.5 * sr**2) / t
    var_sr = max(var_sr, 1e-12)
    z1 = _NORM.inv_cdf(min(1 - 1.0 / n, 1 - 1e-12))
    z2 = _NORM.inv_cdf(min(1 - 1.0 / (n * math.e), 1 - 1e-12))
    sr0 = math.sqrt(var_sr) * ((1 - _EULER) * z1 + _EULER * z2)

    # Non-normality correction: negative skew and fat tails make a given Sharpe
    # less impressive, and ignoring them is how a lottery ticket passes.
    sr_per_period = sr / math.sqrt(periods_per_year)
    denom = 1.0 - skew * sr_per_period + ((kurt - 1.0) / 4.0) * sr_per_period**2
    if denom <= 0:
        return DSRResult(sr, None, sr0 * math.sqrt(periods_per_year), n_trials,
                         skew=skew, kurtosis=kurt,
                         note="non-normality correction degenerate")

    z = ((sr_per_period - sr0) * math.sqrt(t - 1)) / math.sqrt(denom)
    return DSRResult(
        sharpe=sr,
        deflated=float(_NORM.cdf(z)),
        sharpe_threshold=sr0 * math.sqrt(periods_per_year),
        n_trials=n_trials, skew=skew, kurtosis=kurt,
    )


def align_equity_curves(
    curves: Sequence[Sequence[tuple[int, float]]],
    grid: Sequence[int],
) -> np.ndarray:
    """Curve di equity diverse, riportate sulla stessa griglia temporale.

    Serve al PBO, che vuole una matrice T x N di rendimenti confrontabili riga
    per riga. Le curve nascono per trade, quindi ognuna ha i suoi istanti e le
    sue lunghezze: accostarle per posizione confronterebbe il terzo trade di una
    configurazione con il terzo di un'altra, avvenuto mesi dopo — e il PBO
    misurerebbe quel disallineamento invece della sovra-ottimizzazione.

    L'equity fra un trade e il successivo e' costante (la posizione e' chiusa),
    quindi il valore su ogni punto della griglia e' l'ultimo noto a quell'istante
    — nessuna interpolazione, che inventerebbe movimenti mai avvenuti. Prima del
    primo trade vale il capitale iniziale della curva.

    Restituisce una matrice (len(grid) - 1) x N di rendimenti per periodo.
    Le colonne senza dati utilizzabili vengono scartate.
    """
    g = np.asarray(list(grid), dtype=float)
    cols: list[np.ndarray] = []
    for curve in curves:
        if not curve or len(curve) < 2:
            continue
        ts = np.array([t for t, _ in curve], dtype=float)
        vals = np.array([v for _, v in curve], dtype=float)
        # searchsorted a destra: l'ultimo punto con tempo <= t della griglia.
        idx = np.searchsorted(ts, g, side="right") - 1
        idx = np.clip(idx, 0, len(vals) - 1)
        level = vals[idx]
        prev = level[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            ret = np.where(prev > 0, (level[1:] - prev) / prev, np.nan)
        if not np.any(np.isfinite(ret)) or np.allclose(np.nan_to_num(ret), 0.0):
            # Una colonna piatta non porta informazione e, sommata, pareggia
            # con qualsiasi altra: falserebbe i confronti fra le meta'.
            continue
        cols.append(ret)
    if not cols:
        return np.empty((0, 0), dtype=float)
    return np.column_stack(cols)


def periods_per_year_from_curve(equity_curve: list[tuple[int, float]]) -> float:
    """How many equity-curve steps a year actually contains.

    The steps are TRADES, not calendar days, so annualising them with the 252
    of daily returns silently assumes the strategy trades every session. On a
    28-trade backtest spanning two and a half years that inflates the Sharpe by
    roughly a factor of three, and the deflation threshold it is compared
    against is computed on the same wrong scale — the verdict survives, the
    number does not. Derive the factor from the curve's own timestamps instead.
    """
    if not equity_curve or len(equity_curve) < 3:
        return 252.0
    t0, t1 = equity_curve[0][0], equity_curve[-1][0]
    span_days = (t1 - t0) / 86400.0
    if span_days <= 1:
        return 252.0
    steps = len(equity_curve) - 1
    return float(np.clip(steps / (span_days / 365.25), 1.0, 365.0))


def returns_from_equity_curve(equity_curve: list[tuple[int, float]]) -> np.ndarray:
    """Per-trade returns from an equity curve, for the Sharpe input."""
    if not equity_curve or len(equity_curve) < 2:
        return np.array([], dtype=float)
    vals = np.array([v for _, v in equity_curve], dtype=float)
    prev = vals[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(prev > 0, (vals[1:] - prev) / prev, np.nan)
    return out[np.isfinite(out)]
