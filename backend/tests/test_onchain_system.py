"""The system joining a trend that was already running at the alert."""
from __future__ import annotations

import numpy as np

from app.trading.onchain import system


def _bars(n_flat: int = 120, n_pump: int = 180, *, drift: float = 0.012, seed: int = 1) -> list[list]:
    rng = np.random.default_rng(seed)
    bars: list[list] = []
    price = 1.0
    t = 1_700_000_000
    for _ in range(n_flat):
        price *= 1 + rng.normal(0, 0.004)
        bars.append([t, price, price, price, price, 1.0])
        t += system.BAR_S
    for _ in range(n_pump):
        price *= 1 + drift
        bars.append([t, price, price, price, price, 1.0])
        t += system.BAR_S
    return bars


def _start(bars: list[list], i: int) -> float:
    return float(bars[i][0])


def _real_bars():
    rng = np.random.default_rng(1)
    out, p, t = [], 1.0, 1_700_000_000
    for i in range(300):
        p *= np.exp((0 if i < 120 else 0.012) + rng.normal(0, 0.004))
        out.append([t + i * 300, p, p * 1.003, p * 0.997, p, 1000 + int(rng.integers(0, 500))])
    return out


def test_backtest_all_rows_in_order_with_keys():
    out = system.backtest_all(_real_bars())
    assert out["bars"] == 300
    assert [r["label"] for r in out["rows"]] == [lab for _n, lab in system.BACKTESTS]
    for r in out["rows"]:
        assert set(r) == {"label", "return_pct", "trades", "win_rate", "max_dd", "profit_factor", "in_position"}


def test_backtest_all_trend_and_hold():
    out = system.backtest_all(_real_bars())
    by = {r["label"]: r for r in out["rows"]}
    assert by["Trend EMA"]["trades"] >= 1
    assert by["Trend EMA"]["return_pct"] > 100
    assert by["Trend HF"]["trades"] >= 1
    assert out["hold_pct"] > 100


def test_backtest_all_too_few_bars():
    out = system.backtest_all(_real_bars()[:10])
    assert out["rows"] == []


def test_alert_after_the_trend_started_joins_it():
    bars = _bars()
    now = float(bars[-1][0])
    out = system.follow(bars, system.CANDIDATES[0], _start(bars, 160), now=now)
    assert out["trades"] >= 1 or out["state"] == "in"
    assert out["ret"] > 0.5


def test_alert_before_the_trend_still_buys_after_it():
    bars = _bars()
    now = float(bars[-1][0])
    start = _start(bars, 100)
    out = system.follow(bars, system.CANDIDATES[0], start, now=now)
    buys = [e for e in out["events"] if e["side"] == "buy"]
    assert buys and buys[0]["t"] > start


def test_flat_series_does_not_buy():
    bars = _bars(n_flat=300, n_pump=0)
    now = float(bars[-1][0])
    out = system.follow(bars, system.CANDIDATES[0], _start(bars, 150), now=now)
    assert out["trades"] == 0
    assert out["state"] == "waiting"
