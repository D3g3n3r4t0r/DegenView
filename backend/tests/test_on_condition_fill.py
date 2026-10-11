"""fill_at "on_condition" fills inside the signal candle (board issue 316219de).

Before, "As soon as the condition is met" and "At candle close" gave the
same backtest: both filled at the close.
"""
import pandas as pd

from app.analysis.backtest import intrabar_path, run_backtest

BARS = [  # open, high, low, close
    (100, 101, 99, 100),
    (100, 102, 90, 94),    # red: entry when the low goes under 92
    (94, 96, 93, 95),
    (95, 112, 94, 108),    # green: exit when the price goes over 105
    (108, 109, 107, 108),  # still forming
]


def _df() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(BARS), freq="1D", tz="UTC")
    return pd.DataFrame(BARS, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def _signals(df: pd.DataFrame, _params=None) -> pd.DataFrame:
    return pd.DataFrame({
        "entry_long": df["low"] < 92,
        "exit_long": df["close"] > 105,
        "entry_short": False,
        "exit_short": False,
    }, index=df.index)


BP = {"initial_capital": 1000, "qty_pct_of_equity": 100, "commission_pct": 0, "slippage_pct": 0}


def _trade(fill_at: str, with_replay: bool = True):
    df = _df()
    bt = run_backtest(df, None, {**BP, "fill_at": fill_at}, signals=_signals(df),
                      intrabar_fn=_signals if with_replay else None)
    assert bt.num_trades == 1
    return bt, bt.trades[0]


def test_path_follows_tradingview_order():
    red = intrabar_path(100, 102, 90, 94, steps=2)
    assert [p for p, _, _ in red] == [101, 102, 96, 90, 92, 94]
    green = intrabar_path(95, 112, 94, 108, steps=1)
    assert [p for p, _, _ in green] == [94, 112, 108]
    assert red[-1] == (94, 102, 90)  # last point is the real candle


def test_close_and_on_condition_now_differ():
    _, close_trade = _trade("signal_close")
    bt, cond_trade = _trade("on_condition")
    assert (close_trade.entry_price, close_trade.exit_price) == (94, 108)
    # entry: the low reaches 90 on the way down from the high (102 -> 90)
    assert cond_trade.entry_price == 90
    # exit: first point over 105 on the way up from the low (94 -> 112, 4 steps)
    assert cond_trade.exit_price == 107.5
    assert bt.intrabar_fills == 2
    assert bt.total_return_pct > _trade("signal_close")[0].total_return_pct


def test_without_replay_on_condition_keeps_the_close():
    bt, trade = _trade("on_condition", with_replay=False)
    assert (trade.entry_price, trade.exit_price) == (94, 108)
    assert bt.intrabar_fills is None
