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
