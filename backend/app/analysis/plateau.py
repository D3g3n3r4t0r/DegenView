"""
Plateau search (pipeline stages S3-S4).

Built on the structure measured in phase C: the objective is not a rugged
continuous surface, it is a step function. Sweeping one parameter across 200
evenly spaced values produced 5 distinct objective values, with 98% of steps
changing nothing at all. The reason is mechanical — a backtest is a function of
the trade sequence, which is discrete, so a parameter only matters when it
crosses a threshold that adds or removes a signal. Between two thresholds the
result is identical to the last decimal.

Three consequences drive the design here:

  * Sampling on a fixed lattice wastes almost every evaluation. In the measured
    sweep, 80 consecutive points returned the same number. What carries
    information is the location of the BOUNDARIES, and a step function with k
    jumps over n values is mapped in O(k log n) evaluations by bisection
    instead of O(n).

  * Local refinement has nothing to descend. 98% of local moves have exactly
    zero gradient and the rest are discontinuities, so Nelder-Mead, CMA-ES and
    smooth-kernel Bayesian optimisation are all inapplicable.

  * Plateau width becomes free. Once boundaries are known, the width of the
    cell containing a candidate is read off the partition rather than
    estimated by sampling around it — and width is exactly the quantity that
    separates a robust configuration from a lucky one.

The known weakness is stated in the research note and handled explicitly here:
boundaries along one axis depend on where the other axes sit, so an axis-wise
partition is an approximation, not an identity. It is used as a sampling
structure, never trusted as an exact decomposition, and every finalist is
re-checked by direct perturbation. The disagreement between the width the
partition predicts and the stability actually measured is reported as
`axis_approximation_error`, so the cost of the approximation is a number in the
output instead of an assumption in the design.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.sensitivity import PARAM_SPACES, ParamSpace
from app.models import BacktestResult

# A candidate is identified by what its trades actually were, not by its
# nominal parameters: non-binding parameters produce byte-identical sequences.
Fingerprint = tuple


# Fixed seed for the drift perturbations. Not a tunable: changing it changes
# the answer, and the point of this module is that the answer does not move.
_DRIFT_SEED = 20260903


def _fingerprint(bt: BacktestResult) -> Fingerprint:
    return (round(bt.total_return_pct, 6), bt.num_trades, round(bt.max_drawdown_pct, 6))


@dataclass
class AxisPartition:
    """The cells one axis is divided into, in unit-cube coordinates."""

    dim: int
    name: str
    boundaries: tuple[float, ...]     # interior boundaries, sorted, in (0,1)

    @property
    def edges(self) -> tuple[float, ...]:
        return (0.0,) + self.boundaries + (1.0,)

    @property
    def n_cells(self) -> int:
        return len(self.boundaries) + 1

    def cell_index(self, u: float) -> int:
        return int(np.searchsorted(np.asarray(self.boundaries), u, side="right"))

    def cell_bounds(self, idx: int) -> tuple[float, float]:
        e = self.edges
        return e[idx], e[idx + 1]

    def width_at(self, u: float) -> float:
        lo, hi = self.cell_bounds(self.cell_index(u))
        return hi - lo

    def centers(self) -> list[float]:
        e = self.edges
        return [(e[i] + e[i + 1]) / 2.0 for i in range(len(e) - 1)]


@dataclass
class PlateauCandidate:
    u: np.ndarray
    params: dict
    backtest: BacktestResult
    score: float
    cell_widths: np.ndarray
    log_volume: float
    # Filled in only for finalists that go through direct verification.
    neighbourhood_mean: float | None = None
    neighbourhood_std: float | None = None
    neighbourhood_agreement: float | None = None   # fraction of probes unchanged
    robust_score: float | None = None
    axis_approximation_error: float | None = None

    @property
    def min_width(self) -> float:
        return float(np.min(self.cell_widths)) if self.cell_widths.size else 0.0


@dataclass
class PlateauResult:
    strategy: str
    partitions: list[AxisPartition]
    candidates: list[PlateauCandidate]        # finalists, best robust first
    evaluations: int
    boundary_evaluations: int
    grid_cells: int
    enumerated: bool
    naive_best: PlateauCandidate | None = None   # argmax of raw score, for contrast
    notes: list[str] = field(default_factory=list)

    @property
    def best(self) -> PlateauCandidate | None:
        return self.candidates[0] if self.candidates else None

    def summary(self) -> str:
        lines = [
            f"Plateau search — {self.strategy}",
            f"  {self.evaluations} backtests "
            f"({self.boundary_evaluations} locating boundaries)"
            f"  ·  grid {self.grid_cells} cells"
            f"  ·  {'enumerated' if self.enumerated else 'sampled'}",
            "",
            "  axis partition (cells per dimension):",
        ]
        for p in self.partitions:
            widths = [f"{hi - lo:.3f}" for lo, hi in
                      (p.cell_bounds(i) for i in range(p.n_cells))]
            lines.append(f"    {p.name:<26} {p.n_cells:>3} cells   widths {', '.join(widths[:8])}"
                         + (" …" if len(widths) > 8 else ""))
        lines.append("")
        lines.append(f"  {'#':>2} {'score':>9} {'robust':>9} {'min_w':>8} {'agree':>7} {'ret%':>9} {'trades':>7}")
        lines.append("  " + "-" * 60)
        for i, c in enumerate(self.candidates[:10], start=1):
            rs = f"{c.robust_score:9.3f}" if c.robust_score is not None else "        —"
            ag = f"{c.neighbourhood_agreement:6.0%}" if c.neighbourhood_agreement is not None else "     —"
            lines.append(
                f"  {i:>2} {c.score:>9.3f} {rs} {c.min_width:>8.3f} {ag:>7} "
                f"{c.backtest.total_return_pct:>+9.1f} {c.backtest.num_trades:>7}"
            )
        if self.naive_best is not None and self.candidates:
            nb, rb = self.naive_best, self.candidates[0]
            lines.append("")
            lines.append(
                f"  naive argmax score={nb.score:.3f} min_width={nb.min_width:.3f}"
                f"  vs  plateau pick score={rb.score:.3f} min_width={rb.min_width:.3f}"
            )
        for n in self.notes:
            lines.append(f"  note: {n}")
        return "\n".join(lines)


# --- boundary location -------------------------------------------------------


def _bisect_boundary(
    probe: Callable[[float], Fingerprint],
    a: float, fa: Fingerprint,
    b: float,
    tol: float,
) -> float:
    """Locate the single transition between a and b, assuming fa != fb."""
    while (b - a) > tol:
        m = 0.5 * (a + b)
        fm = probe(m)
        if fm == fa:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


def locate_boundaries(
    probe: Callable[[float], Fingerprint],
    coarse: int = 10,
    tol: float = 0.004,
) -> list[float]:
    """Find where a step function along one axis changes value.

    A coarse scan seeds the search, then every interval whose endpoints differ
    is bisected. Bisection alone would be unsound here: it assumes a single
    transition per bracket, and a plateau that departs and returns to the same
    value inside one bracket is invisible to it. The coarse scan bounds how
    much can hide — it cannot eliminate the risk, and the resolution limit is
    reported rather than papered over.
    """
    xs = np.linspace(0.0, 1.0, coarse)
    vals = [probe(float(x)) for x in xs]
    out: list[float] = []
    for i in range(len(xs) - 1):
        if vals[i] != vals[i + 1]:
            out.append(_bisect_boundary(probe, float(xs[i]), vals[i],
                                        float(xs[i + 1]), tol))
    return sorted(out)


def partition_axes(
    df: pd.DataFrame,
    strategy_name: str,
    space: ParamSpace,
    backtest_params: dict,
    base_points: np.ndarray,
    coarse: int = 10,
    tol: float = 0.004,
    counter: dict | None = None,
) -> list[AxisPartition]:
    """Partition every axis into cells, taking the union of boundaries found
    from several base points.

    The union is deliberate. Boundaries move when the other coordinates move,
    so a partition built from one base point describes one slice of the space.
    Taking the union over several slices yields a refinement that is at least
    as fine as any single slice — cells may be split more than strictly
    necessary, which costs a little search budget, but a boundary that matters
    somewhere is not silently erased.
    """
    parts: list[AxisPartition] = []
    for dim, name in enumerate(space.dims):
        found: list[float] = []
        for base in base_points:
            def probe(u: float, _dim=dim, _base=base) -> Fingerprint:
                point = np.array(_base, dtype=float)
                point[_dim] = u
                bt = run_backtest(df, space.to_params(point), backtest_params,
                                  strategy_name=strategy_name)
                if counter is not None:
                    counter["n"] = counter.get("n", 0) + 1
                    counter["boundary"] = counter.get("boundary", 0) + 1
                return _fingerprint(bt)

            found.extend(locate_boundaries(probe, coarse=coarse, tol=tol))

        # Merge boundaries that are closer together than the bisection tolerance
        # can distinguish — keeping both would create cells narrower than the
        # resolution that produced them.
        merged: list[float] = []
        for b in sorted(found):
            if not merged or (b - merged[-1]) > tol * 2:
                merged.append(b)
        parts.append(AxisPartition(dim=dim, name=name, boundaries=tuple(merged)))
    return parts


# --- scoring -----------------------------------------------------------------


def _plateau_objective(bt: BacktestResult, min_trades: int = 8) -> float:
    """Calmar, tempered by trade count and profit factor. Finite everywhere:
    ranking happens later, so a hard filter here would only destroy the
    ordering information the plateau geometry needs."""
    dd = max(abs(bt.max_drawdown_pct), 0.5)
    calmar = bt.total_return_pct / dd
    conf = bt.num_trades / (bt.num_trades + min_trades)
    pf = bt.profit_factor if bt.profit_factor is not None else 1.0
    pf_bonus = min(max(pf, 0.0), 5.0) / 5.0
    return calmar * (0.6 + 0.4 * pf_bonus) * conf


# --- search ------------------------------------------------------------------


def plateau_search(
    strategy_name: str,
    df: pd.DataFrame,
    backtest_params: dict | None = None,
    base_points: int = 2,
    coarse: int = 8,
    tol: float = 0.004,
    max_grid_evals: int = 1200,
    finalists: int = 12,
    min_trades: int = 8,
    probe_radius: float = 0.05,
    probe_samples: int = 14,
    lam: float = 0.75,
    seed: int = 0,
    objective: Callable[[BacktestResult], float] = _plateau_objective,
) -> PlateauResult:
    """Find the widest good plateau rather than the highest point.

    Deterministic given (strategy, df, settings, seed): the sampling of cell
    combinations is seeded, and nothing else draws randomness. Two runs on the
    same inputs return the same answer — which is the property the whole
    exercise exists to obtain.
    """
    if strategy_name not in PARAM_SPACES:
        raise ValueError(f"Nessuno spazio parametri per {strategy_name!r}")
    space = PARAM_SPACES[strategy_name]
    bp = backtest_params or {}
    rng = np.random.default_rng(seed)
    counter: dict = {"n": 0, "boundary": 0}
    notes: list[str] = []

    def evaluate(u: np.ndarray) -> tuple[BacktestResult, float]:
        bt = run_backtest(df, space.to_params(u), bp, strategy_name=strategy_name)
        counter["n"] += 1
        return bt, objective(bt)

    # --- S3: partition every axis
    bases = np.vstack([np.full(space.d, 0.5), rng.random((max(base_points - 1, 0), space.d))])
    parts = partition_axes(df, strategy_name, space, bp, bases,
                           coarse=coarse, tol=tol, counter=counter)

    grid_cells = 1
    for p in parts:
        grid_cells *= p.n_cells

    # --- S4a: evaluate cell centres, exhaustively when that fits the budget
    centers = [p.centers() for p in parts]
    enumerated = grid_cells <= max_grid_evals

    points: list[np.ndarray] = []
    if enumerated:
        idx = np.zeros(space.d, dtype=int)
        for _ in range(grid_cells):
            points.append(np.array([centers[d][idx[d]] for d in range(space.d)]))
            for d in range(space.d - 1, -1, -1):
                idx[d] += 1
                if idx[d] < len(centers[d]):
                    break
                idx[d] = 0
    else:
        notes.append(
            f"grid of {grid_cells} cells exceeds budget {max_grid_evals}; "
            f"sampling cell-centre combinations instead of enumerating"
        )
        seen: set[tuple[int, ...]] = set()
        while len(points) < max_grid_evals:
            combo = tuple(int(rng.integers(len(centers[d]))) for d in range(space.d))
            if combo in seen:
                continue
            seen.add(combo)
            points.append(np.array([centers[d][combo[d]] for d in range(space.d)]))

    seen_fp: set[Fingerprint] = set()
    cands: list[PlateauCandidate] = []
    for u in points:
        bt, sc = evaluate(u)
        if not math.isfinite(sc):
            continue
        fp = _fingerprint(bt)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        widths = np.array([parts[d].width_at(float(u[d])) for d in range(space.d)])
        cands.append(PlateauCandidate(
            u=u, params=space.to_params(u), backtest=bt, score=sc,
            cell_widths=widths,
            log_volume=float(np.sum(np.log(np.maximum(widths, 1e-12)))),
        ))

    if not cands:
        return PlateauResult(strategy_name, parts, [], counter["n"], counter["boundary"],
                             grid_cells, enumerated, None,
                             notes + ["no finite-score candidate found"])

    _naive_pool = [c for c in cands if c.backtest.num_trades >= min_trades] or cands
    naive_best = max(_naive_pool, key=lambda c: c.score)

    # --- S4b: verify the finalists by direct perturbation
    #
    # The partition predicts each candidate sits in a cell of a given width.
    # That prediction comes from an axis-wise decomposition of a surface known
    # to have interactions, so it is checked rather than believed: probe each
    # axis at +/- half the cell width and see whether the result actually holds.
    # Trade-count floor, applied HERE and not in the objective. The objective
    # has to stay finite everywhere for boundary detection to work at all, so
    # the filter cannot live there — but without it the search happily returns
    # a 3-trade configuration showing +226%, which is one lucky sequence and
    # not an edge. Enforcing it at selection keeps both properties.
    eligible = [c for c in cands if c.backtest.num_trades >= min_trades]
    if not eligible:
        notes.append(
            f"no candidate reached {min_trades} trades "
            f"(best was {max(c.backtest.num_trades for c in cands)}); "
            f"reporting unfiltered, treat as unusable"
        )
        eligible = cands

    drift_rng = np.random.default_rng(_DRIFT_SEED)
    drift_set = [drift_rng.uniform(-probe_radius, probe_radius, size=space.d)
                 for _ in range(probe_samples)]

    by_promise = sorted(eligible, key=lambda c: (c.score, c.log_volume), reverse=True)
    for c in by_promise[:finalists]:
        # Estimate J = (f * K)(theta) by sampling JOINT perturbations, not one
        # parameter at a time. One-at-a-time probing measures the wrong thing
        # here: with d dimensions, a configuration that is a knife edge in a
        # single parameter still scores (2d-2)/2d agreement because the probes
        # along every other axis leave it untouched. Drift does not arrive one
        # coordinate at a time, and the objective in the research note is an
        # expectation over the joint kernel — so the probes have to be joint
        # too, or they estimate a quantity nobody cares about.
        #
        # The perturbation set is fixed and shared by every candidate, and is
        # deliberately NOT derived from `seed`. Drift is a property of the
        # problem, not of the search that happens to be running, so tying it to
        # the search seed would reintroduce exactly the run-to-run variance
        # this module exists to remove — measured: it took cv_oos from 0% back
        # up to 46%. Sharing one set across candidates also pairs the
        # comparison, so differences in robust_score reflect the candidates
        # rather than the draw.
        base_fp = _fingerprint(c.backtest)
        probes: list[float] = []
        unchanged = 0
        for eps in drift_set:
            probe_u = np.clip(c.u + eps, 0.0, 1.0)
            bt, sc = evaluate(probe_u)
            probes.append(sc)
            if _fingerprint(bt) == base_fp:
                unchanged += 1

        if probes:
            arr = np.array(probes + [c.score])
            c.neighbourhood_mean = float(np.mean(arr))
            c.neighbourhood_std = float(np.std(arr))
            c.neighbourhood_agreement = unchanged / len(probes)
            c.robust_score = c.neighbourhood_mean - lam * c.neighbourhood_std
            predicted_stable = float(np.mean(c.cell_widths >= 2.0 * probe_radius))
            c.axis_approximation_error = abs(predicted_stable - c.neighbourhood_agreement)
        else:
            c.neighbourhood_mean = c.score
            c.neighbourhood_std = 0.0
            c.neighbourhood_agreement = 1.0
            c.robust_score = c.score
            c.axis_approximation_error = 0.0

    verified = [c for c in by_promise[:finalists] if c.robust_score is not None]
    # Rank on what was measured, not on what the partition predicted. Phase-E
    # measurement put the axis-approximation error above 50%, so cell width is
    # demoted to a tiebreak and neighbourhood agreement carries the decision.
    verified.sort(
        key=lambda c: (c.robust_score, c.neighbourhood_agreement or 0.0, c.log_volume),
        reverse=True,
    )

    errs = [c.axis_approximation_error for c in verified if c.axis_approximation_error is not None]
    if errs:
        notes.append(
            f"axis approximation error: mean {np.mean(errs):.1%}, worst {max(errs):.1%} "
            f"disagreement between predicted and measured stability"
        )

    return PlateauResult(
        strategy=strategy_name, partitions=parts, candidates=verified,
        evaluations=counter["n"], boundary_evaluations=counter["boundary"],
        grid_cells=grid_cells, enumerated=enumerated,
        naive_best=naive_best, notes=notes,
    )
