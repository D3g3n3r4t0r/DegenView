"""
Parameter search for the "Lorenzo (trend-follower)" strategy — random search
over its 10-dimensional parameter space, scored by profit factor on the
deep-history backtest df (see backtest_interval_for in app.main). A full
grid over that many dimensions is intractable; random sampling with a
generous trial budget finds a strong combination in a bounded, predictable
amount of time instead.

Deliberately scoped to Lorenzo only, per how it was asked for — the other
two strategies (Gabriele, Accumulo/Distribuzione) have smaller, differently
shaped parameter spaces and aren't wired up here.
"""

import random

from app.analysis.backtest import run_backtest
from app.analysis.strategies import DEFAULT_PARAMS
from app.models import BacktestResult

_STRATEGY_NAME = "Lorenzo (trend-follower)"
_TRIALS = 120
# Below this many trades a great profit factor is likely luck, not a real
# edge — such a candidate is disqualified rather than risk handing back
# something that looks great on 2 trades and falls apart on trade 3.
_MIN_TRADES = 8


def _random_params(rng: random.Random) -> dict:
    slope_fast = rng.randint(2, 30)
    # Slow must meaningfully trail fast, same relationship the strategy's
    # own inputs imply (fast/slow crossover) — otherwise the "slope" signal
    # degenerates into near-constant noise.
    slope_slow = rng.randint(slope_fast + 3, 80)
    return {
        "average": rng.choice(["EMA", "SMA"]),
        "len": rng.randint(20, 300),
        "slopeFlen": slope_fast,
        "slopeSlen": slope_slow,
        "trendfilter": rng.choice([True, False]),
        "trendfilterperiod": rng.randint(50, 400),
        "trendfiltertype": rng.choice(["EMA", "SMA"]),
        "volatilityfilter": rng.choice([True, False]),
        "volatilitystdevlength": rng.randint(5, 40),
        "volatilitystdevmalength": rng.randint(10, 80),
    }


def _score(bt: BacktestResult) -> float:
    if bt.num_trades < _MIN_TRADES:
        return float("-inf")
    if bt.profit_factor is None:
        # gross_loss == 0 with trades present means every trade won —
        # better than any finite profit factor, not "undefined".
        return float("inf")
    return bt.profit_factor


def optimize_lorenzo(
    df, backtest_params: dict, trials: int = _TRIALS, seed: int | None = None
) -> tuple[dict, BacktestResult, int]:
    """Returns (best_params, best_backtest_result, trials_evaluated). Always
    evaluated at least once against the strategy's own defaults, so the
    result is never worse than what "no optimization" would have given."""
    rng = random.Random(seed)

    best_params = dict(DEFAULT_PARAMS)
    best_bt = run_backtest(df, best_params, backtest_params, strategy_name=_STRATEGY_NAME)
    best_score = _score(best_bt)
    evaluated = 1

    for _ in range(trials):
        candidate = _random_params(rng)
        bt = run_backtest(df, candidate, backtest_params, strategy_name=_STRATEGY_NAME)
        evaluated += 1
        score = _score(bt)
        if score > best_score:
            best_score = score
            best_params = candidate
            best_bt = bt

    return best_params, best_bt, evaluated
