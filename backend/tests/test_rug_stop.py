import pandas as pd

from app.analysis import strategies
from app.trading.onchain import system


def _bars(rows):
    return [[int(ts.timestamp()), o, h, low, c, v] for ts, o, h, low, c, v in rows]


def _series(prices, volumes=None, start="2024-01-01", freq="5min"):
    idx = pd.date_range(start, periods=len(prices), freq=freq, tz="UTC")
    if volumes is None:
        volumes = [100.0 + i for i in range(len(prices))]
    opens = [prices[0], *prices[:-1]]          # each candle opens at the previous close
    return pd.DataFrame({"open": opens, "high": [max(o, c) * 1.01 for o, c in zip(opens, prices)],
                         "low": [min(o, c) * 0.99 for o, c in zip(opens, prices)], "close": prices,
                         "volume": volumes}, index=idx)


def _signals(df):
    return pd.DataFrame({"entry_long": True, "exit_long": False,
                         "entry_short": True, "exit_short": False}, index=df.index)


def _floor_frame():
    """A pump to 160, then a fall to 10% of the peak within 4 hours, then a
    slow recovery: the FLOOR-like case."""
    prices = [100.0] * 24
    prices += [100.0 + 5 * i for i in range(1, 13)]          # pump to 160
    prices += [160.0 * (0.9 ** i) for i in range(1, 49)]     # fall to ~1.0 in 4h
    prices += [4.0 + 0.5 * i for i in range(1, 25)]          # slow recovery
    return _series(prices)


def test_live_pullback_then_recovery_is_not_a_rug():
    """A live token's -50% pullback over a day, then recovery: no event."""
    prices = [100.0] * 24
    prices += [100.0 - 2.0 * i for i in range(1, 26)]        # -50% over ~2h
    prices += [50.0 + 2.0 * i for i in range(1, 26)]         # recovery
    df = _series(prices)
    assert strategies.rug_event(df) is None
    signals = _signals(df)
    assert strategies.rug_stop(df, signals).equals(signals)


def test_crash_under_30pct_of_6h_high():
    df = _floor_frame()
    ev = strategies.rug_event(df)
    assert ev is not None
    assert ev["why"].startswith("crash ")
    assert "in under 6h" in ev["why"]
    i = ev["i"]
    peak6 = df["high"].rolling(strategies.RUG_CRASH_WINDOW).max()
    assert df["close"].iloc[i] <= 0.30 * peak6.iloc[i]
    assert all(df["close"].iloc[j] > 0.30 * peak6.iloc[j] for j in range(i))


def test_one_candle_halving_is_liquidity_pulled():
    prices = [100.0] * 24 + [100.0, 40.0] + [40.0] * 12
    df = _series(prices)
    ev = strategies.rug_event(df)
    assert ev is not None
    assert ev["i"] == 25
    assert ev["why"] == "one candle -60%: liquidity pulled"


def test_slow_bleed_is_dead_token():
    """-88% over 3 days, no single candle halving and no 6h crash."""
    prices = [100.0 * (0.9975 ** i) for i in range(24 * 36)]   # 0.9975^864 = 0.115
    df = _series(prices)
    ev = strategies.rug_event(df)
    assert ev is not None
    assert ev["why"].endswith("from its top") and ev["kind"] == "fall"
    i = ev["i"]
    top = df["high"].cummax()
    assert df["close"].iloc[i] <= strategies.RUG_DEAD_RATIO * top.iloc[i]
    assert all(df["close"].iloc[j] > strategies.RUG_DEAD_RATIO * top.iloc[j] for j in range(i))


def test_volume_drying_up_is_abandoned():
    """-65% then volume falling to 2% of its peak: trading dried up."""
    prices = [100.0] * 24
    prices += [100.0 - 2.0 * i for i in range(1, 34)]        # -65% over ~3h
    prices += [35.0] * 24
    volumes = [1000.0] * 24 + [1000.0] * 33 + [20.0] * 24
    df = _series(prices, volumes)
    ev = strategies.rug_event(df)
    assert ev is not None
    assert ev["why"] == "trading dried up after the fall"


def test_known_onchain_rug_fires_at_first_bar_after():
    prices = [100.0] * 48
    df = _series(prices)
    at = int(df.index[20].timestamp())
    ev = strategies.rug_event(df, {"at": at, "why": "liquidity pulled on-chain"})
    assert ev is not None
    assert ev["i"] == 20
    assert ev["why"] == "liquidity pulled on-chain"
    ev2 = strategies.rug_event(df, {"at": at, "why": ""})
    assert ev2 is not None and ev2["why"] == "rug seen on-chain"


def test_rug_stop_blocks_entries_and_closes_long():
    df = _floor_frame()
    signals = _signals(df)
    out = strategies.rug_stop(df, signals)
    i = strategies.rug_event(df)["i"]
    assert not out["entry_long"].iloc[i:].any()
    assert not out["entry_short"].iloc[i:].any()
    assert bool(out["exit_long"].iloc[i])


def test_backtest_all_reports_rug_and_no_events_after():
    df = _floor_frame()
    bars = _bars([(ts, r.open, r.high, r.low, r.close, r.volume) for ts, r in df.iterrows()])
    out = system.backtest_all(bars)
    assert out["rug"] is not None
    assert out["rug"]["why"]
    at = out["rug"]["at"]
    best = out["best"]
    if best:
        assert all(e["t"] <= at for e in best["events"])


def test_earliest_signal_wins_not_the_first_in_the_list():
    """A crash at 10:00 and a liquidity-pull candle hours later: the rug is
    the crash, or everything in between would still count."""
    prices = [100.0] * 24 + [100.0 * 0.85 ** i for i in range(1, 13)] + [12.0] * 60 + [5.0] + [5.0] * 6
    df = _series(prices)
    ev = strategies.rug_event(df)
    assert ev["why"].startswith("crash ") and ev["i"] < 24 + 12
