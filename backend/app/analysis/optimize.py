"""
Parameter search for every strategy in the registry.

Scoring: Calmar × profit_factor_bonus × sharpe_bonus × trade_confidence,
with drawdown cap and min-trade floor scaled to the ticker's own volatility
(ATR-based) so the same thresholds are not applied blindly to BTC and a
meme-coin with 10× the daily range.

Search modes:
  random — 200-trial random search over the strategy's continuous space
  grid   — exhaustive search over a discrete grid (Gabriele, Exhaustion only)

Walk-forward: optimises on the first N-60 candles (guaranteeing at least 60
out-of-sample candles regardless of dataset length), validates on the rest.
"""

import itertools
import math
import random
from typing import Iterator

from app.analysis.backtest import run_backtest
from app.analysis.strategies import DEFAULT_PARAMS, EXHAUSTION_DEFAULT_PARAMS, LKI_DEFAULT_PARAMS
from app.models import BacktestResult

_TRIALS = 200
_MIN_OOS_CANDLES = 60


def _volatility_thresholds(volatility_pct: float) -> tuple[float, int]:
    """Return (max_drawdown_cap, min_trades) scaled to ticker volatility."""
    # Low-vol (BTC, large cap): tight DD cap, more trades needed for confidence.
    # High-vol (altcoins, meme): wider DD cap acceptable, fewer trades suffice.
    max_dd = 25.0 + min(volatility_pct * 4.0, 20.0)   # [25, 45]
    min_trades = max(6, 12 - int(volatility_pct))       # [6, 12]
    return max_dd, min_trades


def _score(bt: BacktestResult, volatility_pct: float = 2.0) -> float:
    """Composite score: Calmar × PF bonus × Sharpe bonus × trade confidence.

    All thresholds scale with ticker volatility so BTC and a micro-cap are
    not judged by the same ruler.
    """
    max_dd_cap, min_trades = _volatility_thresholds(volatility_pct)

    if bt.num_trades < min_trades:
        return float("-inf")
    if bt.total_return_pct <= 0:
        return float("-inf")
    if abs(bt.max_drawdown_pct) > max_dd_cap:
        return float("-inf")

    drawdown = max(abs(bt.max_drawdown_pct), 0.5)
    calmar = bt.total_return_pct / drawdown

    pf = bt.profit_factor if bt.profit_factor is not None else 1.0
    pf_bonus = min(pf, 5.0) / 5.0  # [0, 1]

    sharpe = bt.sharpe_ratio if bt.sharpe_ratio is not None else 0.0
    sharpe_bonus = min(max(sharpe / 3.0, 0.0), 1.0)  # [0, 1]

    trade_conf = math.log(bt.num_trades + 1) / math.log(min_trades + 1)

    return calmar * (0.55 + 0.20 * pf_bonus + 0.15 * sharpe_bonus + 0.10 * trade_conf)


def _random_lorenzo_params(rng: random.Random) -> dict:
    slope_fast = rng.randint(2, 30)
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


_STRATEGY_SPACES: dict[str, tuple[dict, callable]] = {
    "Lorenzo (trend-follower)": (DEFAULT_PARAMS, _random_lorenzo_params),
    "Accumulo / Distribuzione (long-term)": (EXHAUSTION_DEFAULT_PARAMS, _random_exhaustion_params),
    "Gabriele (RSI+BB reversal)": (LKI_DEFAULT_PARAMS, _random_gabriele_params),
}

_GRID_GABRIELE = {
    "rsi_length":     [7, 10, 14, 18, 21],
    "bb_length":      [10, 15, 20, 25, 30],
    "bb_mult":        [1.0, 1.5, 2.0, 2.5, 3.0],
    "rsi_oversold":   [18, 22, 26, 30, 35],
    "rsi_overbought": [65, 70, 75, 80, 85],
}  # 5^5 = 3 125 combinations

_GRID_EXHAUSTION = {
    "swing_length":        [4, 8, 12],
    "rsi_length":          [10, 14, 20],
    "rsi_oversold":        [25, 35, 45],
    "rsi_overbought":      [55, 65, 75],
    "rsi_min_gap":         [2.0, 5.0, 8.0],
    "trend_filter":        [True, False],
    "enable_contraction":  [True, False],
    "enable_range_bounce": [True, False],
}  # 3^5 × 2^3 = 1 944 combinations

_GRID_SPACES: dict[str, dict] = {
    "Gabriele (RSI+BB reversal)": _GRID_GABRIELE,
    "Accumulo / Distribuzione (long-term)": _GRID_EXHAUSTION,
}


def _grid_candidates(strategy_name: str) -> Iterator[dict]:
    grid = _GRID_SPACES.get(strategy_name)
    if grid is None:
        return
    keys = list(grid.keys())
    for values in itertools.product(*[grid[k] for k in keys]):
        yield dict(zip(keys, values))


def grid_size(strategy_name: str) -> int:
    grid = _GRID_SPACES.get(strategy_name)
    if grid is None:
        return 0
    total = 1
    for vals in grid.values():
        total *= len(vals)
    return total


def is_optimizable(strategy_name: str) -> bool:
    return strategy_name in _STRATEGY_SPACES


def _calc_volatility(df) -> float:
    """ATR(14) / avg_close × 100 as a percentage."""
    try:
        atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
        avg_close = df["close"].mean()
        if avg_close > 0:
            return float((atr / avg_close) * 100)
    except Exception:
        pass
    return 2.0  # fallback: assume medium-volatility asset


def optimize_strategy(
    strategy_name: str,
    df,
    backtest_params: dict,
    trials: int = _TRIALS,
    seed: int | None = None,
    mode: str = "random",
) -> tuple[dict, BacktestResult, int, float | None, bool]:
    """Returns (best_params, best_backtest_result, trials_evaluated,
    out_of_sample_return_pct, overfitted).

    best_backtest_result.oos_trades contains the out-of-sample trades so the
    caller can display them separately in the UI.

    Walk-forward: optimises on df[:-oos_candles] (in-sample), validates on
    df[-oos_candles:]. oos_candles = max(30% of df, _MIN_OOS_CANDLES).
    """
    if strategy_name not in _STRATEGY_SPACES:
        raise ValueError(f"Nessuno spazio di parametri definito per {strategy_name!r}")
    default_params, random_params_fn = _STRATEGY_SPACES[strategy_name]

    rng = random.Random(seed)

    # Volatility-aware thresholds
    ticker_volatility = _calc_volatility(df)

    # Adaptive walk-forward split: guarantee at least _MIN_OOS_CANDLES OOS
    oos_candles = max(int(len(df) * 0.30), _MIN_OOS_CANDLES)
    split = len(df) - oos_candles
    df_in = df.iloc[:split]
    df_out = df.iloc[split:]

    best_params = dict(default_params)
    best_bt = run_backtest(df_in, best_params, backtest_params, strategy_name=strategy_name)
    best_score = _score(best_bt, ticker_volatility)
    evaluated = 1

    use_grid = mode == "grid" and strategy_name in _GRID_SPACES
    if use_grid:
        for candidate_delta in _grid_candidates(strategy_name):
            candidate = {**default_params, **candidate_delta}
            bt = run_backtest(df_in, candidate, backtest_params, strategy_name=strategy_name)
            evaluated += 1
            score = _score(bt, ticker_volatility)
            if score > best_score:
                best_score = score
                best_params = candidate
                best_bt = bt
    else:
        for _ in range(trials):
            candidate = random_params_fn(rng)
            bt = run_backtest(df_in, candidate, backtest_params, strategy_name=strategy_name)
            evaluated += 1
            score = _score(bt, ticker_volatility)
            if score > best_score:
                best_score = score
                best_params = candidate
                best_bt = bt

    # Out-of-sample validation — run best params on held-out period
    out_of_sample_return_pct: float | None = None
    overfitted = False
    oos_trades = []
    if len(df_out) > 0:
        oos_bt = run_backtest(df_out, best_params, backtest_params, strategy_name=strategy_name)
        out_of_sample_return_pct = oos_bt.total_return_pct
        oos_trades = oos_bt.trades
        in_sample_return = best_bt.total_return_pct
        if in_sample_return > 0:
            degradation = (in_sample_return - out_of_sample_return_pct) / abs(in_sample_return)
            if degradation > 0.50:
                overfitted = True
        elif in_sample_return <= 0 and out_of_sample_return_pct < in_sample_return:
            overfitted = True

    # Attach metadata to the result
    best_bt = best_bt.model_copy(update={
        "ticker_volatility_pct": round(ticker_volatility, 2),
        "oos_trades": oos_trades,
    })

    return best_params, best_bt, evaluated, out_of_sample_return_pct, overfitted
