import pandas as pd

from app.analysis import strategies
from app.trading.onchain import system


def _bars(rows):
    return [[int(ts.timestamp()), o, h, low, c, v] for ts, o, h, low, c, v in rows]


def _series(prices, start="2024-01-01", freq="5min"):
    idx = pd.date_range(start, periods=len(prices), freq=freq, tz="UTC")
    return pd.DataFrame({"open": prices, "high": [p * 1.01 for p in prices],
                         "low": [p * 0.99 for p in prices], "close": prices,
                         "volume": [100.0 + i for i in range(len(prices))]}, index=idx)


def _rug_frame():
    """Steady, a pump, then a fall to 10% of the peak within 3 hours, then a
    slow recovery."""
    prices = [100.0] * 24
    prices += [100.0 + 5 * i for i in range(1, 13)]          # pump to 160
    prices += [160.0 * (0.9 ** i) for i in range(1, 37)]     # fall to ~3.6 in 3h
    prices += [4.0 + 0.5 * i for i in range(1, 25)]          # slow recovery
    return _series(prices)


def test_rug_bar_is_first_bar_below_35pct_of_peak():
    df = _rug_frame()
    i = strategies.rug_bar(df)
    assert i is not None
    peak = df["high"].rolling(strategies.RUG_WINDOW).max()
    assert df["low"].iloc[i] <= (1 - strategies.RUG_DROP) * peak.iloc[i]
    assert all(df["low"].iloc[j] > (1 - strategies.RUG_DROP) * peak.iloc[j] for j in range(i))


def test_rug_stop_blocks_entries_and_closes_long():
    df = _rug_frame()
    signals = pd.DataFrame({"entry_long": True, "exit_long": False,
                            "entry_short": True, "exit_short": False}, index=df.index)
    out = strategies.rug_stop(df, signals)
    i = strategies.rug_bar(df)
    assert not out["entry_long"].iloc[i:].any()
    assert not out["entry_short"].iloc[i:].any()
    assert bool(out["exit_long"].iloc[i])


def test_small_dip_is_not_a_rug():
    prices = [100.0] * 24 + [100.0 - 0.5 * i for i in range(1, 25)]   # -12%, well under 65%
    df = _series(prices)
    assert strategies.rug_bar(df) is None
    signals = pd.DataFrame({"entry_long": True, "exit_long": False,
                            "entry_short": False, "exit_short": False}, index=df.index)
    out = strategies.rug_stop(df, signals)
    assert out.equals(signals)


def test_backtest_all_reports_rug_and_no_events_after():
    df = _rug_frame()
    bars = _bars([(ts, r.open, r.high, r.low, r.close, r.volume) for ts, r in df.iterrows()])
    out = system.backtest_all(bars)
    assert out["rug"] is not None
    assert out["rug"]["drop"] == strategies.RUG_DROP
    at = out["rug"]["at"]
    best = out["best"]
    if best:
        assert all(e["t"] <= at for e in best["events"])
