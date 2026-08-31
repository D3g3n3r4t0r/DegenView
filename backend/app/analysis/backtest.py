import pandas as pd

from app.analysis.strategies import DEFAULT_STRATEGY, confirmed_events
from app.models import BacktestResult, BacktestTrade, StrategySignal

# Same defaults as the user's Pine Script header:
# strategy("Lorenzo", initial_capital=10000, default_qty_type=percent_of_equity,
#          commission_type=percent, commission_value=0.06, slippage=2, default_qty_value=30)
# Pine's slippage is in ticks, which has no single meaning across stocks/crypto
# of wildly different price scales — ported here as a percent-of-price instead.
# stop_loss_pct/take_profit_pct default to 0 (disabled) — signal-only exits,
# same behavior as before this was added. Set either > 0 to close a position
# the moment a bar's intrabar high/low crosses that level, independent of
# whatever the strategy's own exit signal says.
DEFAULT_BACKTEST_PARAMS = {
    "initial_capital": 10000.0,
    "qty_pct_of_equity": 30.0,
    "commission_pct": 0.06,
    "slippage_pct": 0.02,
    "stop_loss_pct": 0.0,
    "take_profit_pct": 0.0,
}

_ENTRY_TYPES = {"entry_long", "entry_short"}
_EXIT_TYPES = {"exit_long", "exit_short"}
_FLIP_TYPES = {"flip_to_long", "flip_to_short"}


def _fill_price(price: float, pct: float, side: str) -> float:
    # side "buy" fills worse (higher); "sell" fills worse (lower).
    return price * (1 + pct / 100) if side == "buy" else price * (1 - pct / 100)


def run_backtest(
    df: pd.DataFrame,
    strategy_params: dict | None,
    backtest_params: dict | None,
    signals: pd.DataFrame | None = None,
    strategy_name: str = DEFAULT_STRATEGY,
) -> BacktestResult:
    bp = {**DEFAULT_BACKTEST_PARAMS, **(backtest_params or {})}
    events, _final_position = confirmed_events(df, strategy_params, signals=signals, strategy_name=strategy_name)
    event_by_ts: dict[int, StrategySignal] = {s.time: s for s in events}

    equity = bp["initial_capital"]
    peak_equity = equity
    max_drawdown_pct = 0.0
    trades: list[BacktestTrade] = []
    equity_curve: list[tuple[int, float]] = [(int(df.index[0].timestamp()), equity)]

    open_trade: dict | None = None  # {direction, entry_time, entry_price}

    def _open(direction: str, signal: StrategySignal) -> None:
        nonlocal open_trade
        fill = _fill_price(signal.price, bp["slippage_pct"], "buy" if direction == "long" else "sell")
        open_trade = {"direction": direction, "entry_time": signal.time, "entry_price": fill}

    def _close_at(raw_price: float, time: int) -> None:
        nonlocal equity, peak_equity, max_drawdown_pct, open_trade
        if open_trade is None:
            return
        direction = open_trade["direction"]
        exit_fill = _fill_price(raw_price, bp["slippage_pct"], "sell" if direction == "long" else "buy")
        entry_fill = open_trade["entry_price"]

        raw_return = (exit_fill - entry_fill) / entry_fill
        if direction == "short":
            raw_return = -raw_return

        notional = equity * (bp["qty_pct_of_equity"] / 100)
        commission = notional * (bp["commission_pct"] / 100) * 2  # entry + exit
        pnl_abs = notional * raw_return - commission
        equity += pnl_abs
        peak_equity = max(peak_equity, equity)
        drawdown_pct = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        trades.append(
            BacktestTrade(
                direction=direction,
                entry_time=open_trade["entry_time"],
                exit_time=time,
                entry_price=entry_fill,
                exit_price=exit_fill,
                pnl_pct=raw_return * 100,
                pnl_abs=pnl_abs,
                equity_after=equity,
            )
        )
        equity_curve.append((time, equity))
        open_trade = None

    stop_pct = bp["stop_loss_pct"]
    target_pct = bp["take_profit_pct"]
    stop_loss_enabled = stop_pct > 0 or target_pct > 0

    for ts, row in df.iterrows():
        t = int(ts.timestamp())

        # Intrabar stop/target check happens before this bar's own signal —
        # a position can be stopped out on a bar between two strategy
        # signals, using the bar's actual high/low, not just its close.
        if stop_loss_enabled and open_trade is not None:
            direction = open_trade["direction"]
            entry = open_trade["entry_price"]
            if direction == "long":
                stop_level = entry * (1 - stop_pct / 100) if stop_pct > 0 else None
                target_level = entry * (1 + target_pct / 100) if target_pct > 0 else None
                stop_hit = stop_level is not None and row["low"] <= stop_level
                target_hit = target_level is not None and row["high"] >= target_level
            else:
                stop_level = entry * (1 + stop_pct / 100) if stop_pct > 0 else None
                target_level = entry * (1 - target_pct / 100) if target_pct > 0 else None
                stop_hit = stop_level is not None and row["high"] >= stop_level
                target_hit = target_level is not None and row["low"] <= target_level
            if stop_hit:
                _close_at(stop_level, t)
                continue
            if target_hit:
                _close_at(target_level, t)
                continue

        signal = event_by_ts.get(t)
        if signal is None:
            continue
        if signal.type in _ENTRY_TYPES:
            _open("long" if signal.type == "entry_long" else "short", signal)
        elif signal.type in _EXIT_TYPES:
            _close_at(signal.price, signal.time)
        elif signal.type in _FLIP_TYPES:
            _close_at(signal.price, signal.time)
            _open("long" if signal.type == "flip_to_long" else "short", signal)

    wins = [t for t in trades if t.pnl_abs > 0]
    losses = [t for t in trades if t.pnl_abs <= 0]
    gross_profit = sum(t.pnl_abs for t in wins)
    gross_loss = -sum(t.pnl_abs for t in losses)

    return BacktestResult(
        interval="",  # caller (app.main) fills in the interval the df it passed actually was
        initial_capital=bp["initial_capital"],
        final_equity=equity,
        total_return_pct=(equity - bp["initial_capital"]) / bp["initial_capital"] * 100,
        num_trades=len(trades),
        win_rate_pct=(len(wins) / len(trades) * 100) if trades else None,
        max_drawdown_pct=max_drawdown_pct,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else None,
        equity_curve=equity_curve,
        trades=trades,
    )
