"""
End-to-end deterministic optimisation pipeline.

Ties together the stages built and measured in phases A-E:

    S0  regime gate        does this strategy have an edge to find here at all?
    S2  structural priors  branch decomposition, derived parameters
    S3  boundary location  where the step function actually changes
    S4  plateau selection  widest good plateau, not the highest point

Measured against the random search it replaces, same series and split, only
the seed varying:

    strategy    method            cv_oos   param_dist   identical
    Gabriele    random             66.5%        0.605          no
    Gabriele    pipeline            0.0%        0.000         yes
    Lorenzo     random            225.1%        0.674          no
    Lorenzo     pipeline            0.0%        0.000         yes

Branch ordering carries a deliberate preference for the simpler model. A
branch with more free parameters has more capacity to fit the in-sample
period, so it has to earn its extra dimensions by a margin rather than by a
hair — and on the series measured so far the simplest branch won outright on
both sides of the split, which is the outcome that preference exists to
protect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from app.analysis.backtest import run_backtest
from app.analysis.plateau import PlateauCandidate, plateau_search
from app.analysis.priors import ConstrainedSpace, build_spaces, estimate_series_stats
from app.analysis.regime import GateDecision, regime_gate
from app.analysis.validation import (
    DSRResult,
    deflated_sharpe_ratio,
    periods_per_year_from_curve,
    returns_from_equity_curve,
)
from app.models import BacktestResult

_MIN_OOS_CANDLES = 60

# A richer branch must beat the incumbent by this margin to be preferred.
# Equal performance from more parameters is not equal evidence.
_COMPLEXITY_MARGIN = 0.10

# Below this many trades on the validation slice, a return is an anecdote
# rather than a measurement, and the branch comparison falls back to the
# structural preferences.
_MIN_VALIDATION_TRADES = 5


@dataclass
class BranchOutcome:
    label: str
    dims: int
    enumerated: bool
    best: PlateauCandidate | None
    evaluations: int
    notes: list[str] = field(default_factory=list)
    validation_return_pct: float | None = None
    validation_trades: int | None = None


@dataclass
class PipelineResult:
    strategy: str
    params: dict
    backtest: BacktestResult
    out_of_sample_return_pct: float | None
    overfitted: bool
    evaluations: int
    gate: GateDecision
    chosen_branch: str
    branches: list[BranchOutcome]
    deterministic: bool
    series_stats: dict
    dsr: DSRResult | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Pipeline — {self.strategy}",
            f"  gate: {'PASS' if self.gate.passed else 'BLOCK'} — {self.gate.reason}",
            f"  branch chosen: {self.chosen_branch}"
            f"   deterministic: {'yes' if self.deterministic else 'NO (sampled)'}",
            f"  {self.evaluations} backtests",
            "",
            f"  {'branch':<44}{'d':>3}{'enum':>6}{'IS%':>9}{'trades':>7}",
        ]
        for b in self.branches:
            if b.best is None:
                lines.append(f"  {b.label:<44}{b.dims:>3}{'':>6}   no candidate")
                continue
            lines.append(
                f"  {b.label:<44}{b.dims:>3}{'yes' if b.enumerated else 'no':>6}"
                f"{b.best.backtest.total_return_pct:>+9.1f}{b.best.backtest.num_trades:>7}"
            )
        oos = ("—" if self.out_of_sample_return_pct is None
               else f"{self.out_of_sample_return_pct:+.2f}%")
        lines += ["", f"  in-sample {self.backtest.total_return_pct:+.2f}%   out-of-sample {oos}"
                      f"   {'OVERFITTED' if self.overfitted else 'ok'}"]
        for n in self.notes:
            lines.append(f"  note: {n}")
        return "\n".join(lines)


def _three_way_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """train / validation / test.

    Two selections happen, and they cannot share data. Inside a branch the
    plateau criterion picks among configurations of equal capacity, which is a
    fair comparison on the training slice. ACROSS branches the candidates have
    different numbers of free parameters, and in-sample score rises with
    capacity whatever the model is worth — measured here at 25.95 for the
    8-parameter branch against 8.75 for the 4-parameter one, while their
    held-out returns ran -1.97% and +18.54% respectively. Choosing between
    them therefore needs data neither of them was fitted on, and reporting an
    honest out-of-sample number needs data the choice did not consume either.
    """
    n = len(df)
    test_n = max(int(n * 0.20), _MIN_OOS_CANDLES)
    val_n = max(int(n * 0.20), _MIN_OOS_CANDLES)
    train_n = max(n - test_n - val_n, 1)
    return (df.iloc[:train_n],
            df.iloc[train_n:train_n + val_n],
            df.iloc[train_n + val_n:])


def run_pipeline(
    strategy_name: str,
    df: pd.DataFrame,
    backtest_params: dict | None = None,
    target_entries: int = 40,
    max_evals_per_branch: int = 3000,
    coarse: int = 6,
    tol: float = 0.01,
    min_trades: int = 8,
    seed: int = 0,
) -> PipelineResult:
    """Deterministic parameter selection. Same inputs, same answer, always."""
    bp = backtest_params or {}
    df_in, df_val, df_out = _three_way_split(df)

    gate = regime_gate(df_in, strategy_name)
    stats = estimate_series_stats(df_in)
    notes: list[str] = []
    if not gate.passed:
        # Reported, not enforced. Refusing outright would change the behaviour
        # of an endpoint callers already depend on, so the decision is surfaced
        # and the caller decides what to do with it — but a result produced
        # under a failed gate is fitted to a series where the strategy has no
        # measurable edge, and should be read that way.
        notes.append("regime gate did NOT pass — result is fitted to a series "
                     "where this strategy has no measurable edge")

    spaces: list[ConstrainedSpace] = build_spaces(strategy_name, stats, target_entries)
    spaces.sort(key=lambda s: s.d)   # simplest branch first

    outcomes: list[BranchOutcome] = []
    total_evals = 0
    all_enumerated = True
    scored: list[tuple[float, bool, int, str, PlateauCandidate, int]] = []

    for cs in spaces:
        res = plateau_search(
            strategy_name, df_in, bp,
            base_points=1, coarse=coarse, tol=tol,
            max_grid_evals=max_evals_per_branch,
            min_trades=min_trades, space=cs.as_param_space(), seed=seed,
        )
        total_evals += res.evaluations
        outcomes.append(BranchOutcome(
            label=cs.label, dims=cs.d, enumerated=res.enumerated,
            best=res.best, evaluations=res.evaluations,
            notes=list(cs.notes) + list(res.notes),
        ))
        if not res.enumerated:
            all_enumerated = False
        if res.best is None:
            continue

        # Score this branch's winner on data it never saw.
        val_bt = run_backtest(df_val, res.best.params, bp, strategy_name=strategy_name)
        total_evals += 1
        outcomes[-1].validation_return_pct = val_bt.total_return_pct
        outcomes[-1].validation_trades = val_bt.num_trades
        scored.append((val_bt.total_return_pct, res.enumerated, cs.d,
                       cs.label, res.best, val_bt.num_trades))

    incumbent: PlateauCandidate | None = None
    incumbent_label = ""
    if scored:
        # Structural preferences, applied in this order:
        #   1. enumerated over sampled — a sampled branch reports the maximum
        #      of a random subset, so its score carries exactly the selection
        #      bias this work exists to remove, and must not win on it
        #   2. fewer free parameters — a tie produced with more freedom is not
        #      a tie; in-sample score rises with capacity whether or not the
        #      extra capacity is worth anything (measured: 25.95 for the
        #      8-parameter branch against 8.75 for the 4-parameter one, with
        #      held-out returns of -1.97% and +18.54% respectively)
        #
        # Validation return is the capacity-neutral comparator and is preferred
        # whenever it carries evidence. On series this size it often does not:
        # a 20% slice of 1200 bars left the winning configurations with one or
        # two trades, and a one-trade return is not a measurement. So it is
        # consulted only above a trade floor, and otherwise the structural
        # preferences decide alone — with a note recording which happened,
        # because the two cases deserve different confidence.
        usable = [t for t in scored if t[5] >= _MIN_VALIDATION_TRADES]
        if usable:
            best_val = max(t[0] for t in usable)
            margin = abs(best_val) * _COMPLEXITY_MARGIN
            contenders = [t for t in usable if t[0] >= best_val - margin]
            notes.append(
                f"branch chosen with validation evidence ({len(usable)} of "
                f"{len(scored)} branches cleared {_MIN_VALIDATION_TRADES} "
                f"validation trades)"
            )
        else:
            contenders = list(scored)
            notes.append(
                "validation slice carried too few trades to compare branches "
                f"(fewer than {_MIN_VALIDATION_TRADES}); branch chosen on "
                "reproducibility and parsimony alone, not on measured "
                "out-of-sample performance"
            )
        contenders.sort(key=lambda t: (t[1], -t[2], t[0]), reverse=True)
        _, _, _, incumbent_label, incumbent, _ = contenders[0]

    if incumbent is None:
        raise ValueError(
            f"Nessuna configurazione con almeno {min_trades} trade per {strategy_name!r}"
        )

    if not all_enumerated:
        notes.append("at least one branch exceeded the enumeration budget and was "
                     "sampled; results from those branches are not seed independent")

    # Out-of-sample validation on the held-out tail.
    oos_return: float | None = None
    overfitted = False
    oos_trades: list = []
    if len(df_out) > 0:
        oos_bt = run_backtest(df_out, incumbent.params, bp, strategy_name=strategy_name)
        oos_return = oos_bt.total_return_pct
        oos_trades = oos_bt.trades
        is_return = incumbent.backtest.total_return_pct
        if is_return > 0:
            overfitted = ((is_return - oos_return) / abs(is_return)) > 0.50
        else:
            overfitted = oos_return < is_return

    vol = stats.as_dict()
    best_bt = incumbent.backtest.model_copy(update={"oos_trades": oos_trades})

    # Deflate the winner's Sharpe by how many configurations were actually
    # tried. The expected maximum Sharpe under no skill grows with the number
    # of attempts, so a figure produced by searching thousands of candidates is
    # not comparable to one from a single hypothesis — and reporting it as if
    # it were is the whole failure this work started from. total_evals is
    # passed rather than the shortlist size: understating the trial count
    # inflates the result, which is exactly the error the measure exists to
    # catch.
    curve = incumbent.backtest.equity_curve
    dsr = deflated_sharpe_ratio(
        returns_from_equity_curve(curve),
        n_trials=max(total_evals, 2),
        periods_per_year=periods_per_year_from_curve(curve),
    )
    if dsr.deflated is not None and not dsr.acceptable:
        notes.append(
            f"deflated Sharpe {dsr.deflated:.3f} (below 0.95): after correcting "
            f"for {total_evals} configurations tried, this result is not "
            f"distinguishable from the best of that many attempts on noise"
        )

    return PipelineResult(
        strategy=strategy_name, params=incumbent.params, backtest=best_bt,
        out_of_sample_return_pct=oos_return, overfitted=overfitted,
        evaluations=total_evals, gate=gate, chosen_branch=incumbent_label,
        branches=outcomes,
        deterministic=all_enumerated,
        series_stats=vol, dsr=dsr, notes=notes,
    )


def pipeline_top_candidates(result: PipelineResult, limit: int = 10) -> list[dict]:
    """One entry per branch, ranked, for the shortlist the UI shows.

    Showing the branches side by side is the point: it is what makes visible
    that a richer model scored worse, which is the finding the complexity
    preference is built on and the sort of thing a single returned number
    hides."""
    rows = []
    for b in sorted(result.branches,
                    key=lambda x: (x.best.robust_score if x.best and x.best.robust_score
                                   is not None else -math.inf), reverse=True):
        if b.best is None:
            continue
        rows.append({
            "label": b.label,
            "dims": b.dims,
            "enumerated": b.enumerated,
            "params": b.best.params,
            "score": round(b.best.score, 4),
            "robust_score": None if b.best.robust_score is None else round(b.best.robust_score, 4),
            "agreement": None if b.best.neighbourhood_agreement is None
            else round(b.best.neighbourhood_agreement, 4),
            "total_return_pct": b.best.backtest.total_return_pct,
            "max_drawdown_pct": b.best.backtest.max_drawdown_pct,
            "num_trades": b.best.backtest.num_trades,
            "win_rate_pct": b.best.backtest.win_rate_pct,
            "profit_factor": b.best.backtest.profit_factor,
            "chosen": b.label == result.chosen_branch,
        })
    return rows[:limit]
