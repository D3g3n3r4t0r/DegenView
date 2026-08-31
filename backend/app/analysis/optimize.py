"""
Parameter search for every strategy in the registry — random search over
each strategy's own parameter space, scored by profit factor on the
deep-history backtest df (see backtest_interval_for in app.main). A full
grid over these dimensions (5 to 20, depending on the strategy) is
intractable; random sampling with a generous trial budget finds a strong
combination in a bounded, predictable amount of time instead.
"""

import random

from app.analysis.backtest import run_backtest
from app.analysis.strategies import DEFAULT_PARAMS, EXHAUSTION_DEFAULT_PARAMS, LKI_DEFAULT_PARAMS
from app.models import BacktestResult

_TRIALS = 120
# Below this many trades a great profit factor is likely luck, not a real
# edge — such a candidate is disqualified rather than risk handing back
# something that looks great on 2 trades and falls apart on trade 3.
_MIN_TRADES = 8


def _random_lorenzo_params(rng: random.Random) -> dict:
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


def _random_exhaustion_params(rng: random.Random) -> dict:
    rsi_oversold = rng.randint(20, 45)
    rsi_overbought = rng.randint(55, 80)
    return {
        "swing_length": rng.randint(3, 20),
        "rsi_length": rng.randint(7, 25),
        "rsi_oversold": rsi_oversold,
        "rsi_overbought": rsi_overbought,
        "rsi_min_gap": round(rng.uniform(1.0, 10.0), 2),
        "low_tolerance_pct": round(rng.uniform(0.2, 3.0), 2),
        "divergence_lookback": rng.randint(2, 8),
        "volume_ma_length": rng.randint(10, 40),
        "volume_multiplier": round(rng.uniform(1.1, 2.5), 2),
        "trend_filter": rng.choice([True, False]),
        "trend_ema_length": rng.randint(20, 100),
        "confirmation_lookahead": rng.randint(3, 20),
        "contraction_lookback": rng.randint(5, 20),
        "contraction_prior_lookback": rng.randint(20, 60),
        "contraction_ratio": round(rng.uniform(0.3, 0.8), 2),
        "range_lookback": rng.randint(20, 80),
        "range_zone_pct": round(rng.uniform(0.1, 0.4), 2),
        # At least one entry condition must stay on, or nothing ever fires.
        "enable_divergence": True,
        "enable_contraction": rng.choice([True, False]),
        "enable_range_bounce": rng.choice([True, False]),
    }


def _random_gabriele_params(rng: random.Random) -> dict:
    return {
        "rsi_length": rng.randint(7, 25),
        "bb_length": rng.randint(10, 40),
        "bb_mult": round(rng.uniform(1.0, 3.5), 2),
        "rsi_oversold": rng.randint(15, 40),
        "rsi_overbought": rng.randint(60, 85),
    }


# One entry per strategy in app.analysis.strategies.STRATEGY_REGISTRY:
# (default params, random-candidate generator). Keyed by the exact strategy
# name returned from /api/strategies.
_STRATEGY_SPACES: dict[str, tuple[dict, "random.Random"]] = {
    "Lorenzo (trend-follower)": (DEFAULT_PARAMS, _random_lorenzo_params),
    "Accumulo / Distribuzione (long-term)": (EXHAUSTION_DEFAULT_PARAMS, _random_exhaustion_params),
    "Gabriele (RSI+BB reversal)": (LKI_DEFAULT_PARAMS, _random_gabriele_params),
}


def is_optimizable(strategy_name: str) -> bool:
    return strategy_name in _STRATEGY_SPACES


def _score(bt: BacktestResult) -> float:
    if bt.num_trades < _MIN_TRADES:
        return float("-inf")
    if bt.profit_factor is None:
        # gross_loss == 0 with trades present means every trade won —
        # better than any finite profit factor, not "undefined".
        return float("inf")
    return bt.profit_factor


def optimize_strategy(
    strategy_name: str, df, backtest_params: dict, trials: int = _TRIALS, seed: int | None = None
) -> tuple[dict, BacktestResult, int]:
    """Returns (best_params, best_backtest_result, trials_evaluated). Always
    evaluated at least once against the strategy's own defaults, so the
    result is never worse than what "no optimization" would have given."""
    if strategy_name not in _STRATEGY_SPACES:
        raise ValueError(f"Nessuno spazio di parametri definito per {strategy_name!r}")
    default_params, random_params_fn = _STRATEGY_SPACES[strategy_name]

    rng = random.Random(seed)

    best_params = dict(default_params)
    best_bt = run_backtest(df, best_params, backtest_params, strategy_name=strategy_name)
    best_score = _score(best_bt)
    evaluated = 1

    for _ in range(trials):
        candidate = random_params_fn(rng)
        bt = run_backtest(df, candidate, backtest_params, strategy_name=strategy_name)
        evaluated += 1
        score = _score(bt)
        if score > best_score:
            best_score = score
            best_params = candidate
            best_bt = bt

    return best_params, best_bt, evaluated
