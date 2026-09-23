"""Lorenzo HF: la logica di Lorenzo sulle candele da un minuto dei token on-chain.

Cose da tenere ferme: solo long (on-chain spot non va short), nessuna
informazione futura, mai ingresso e uscita sulla stessa barra (confirmed_events
rientrerebbe subito), e il trailing stop che chiude prima dell'incrocio.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest
from app.analysis.regime import FAMILY_TREND, STRATEGY_FAMILY
from app.analysis.strategies import (
    AVAILABLE_STRATEGIES,
    compute_lorenzo_hf_signals,
    confirmed_events,
)
from app.trading.onchain import radar

NAME = "Lorenzo HF (minuti on-chain)"


def _frame(close: np.ndarray, volume: np.ndarray, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(close)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n))),
            "low": np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n))),
            "close": close,
            "volume": volume,
        },
        index=pd.date_range("2026-09-01", periods=n, freq="min", tz="UTC"),
    )


@pytest.fixture(scope="module")
def noise() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 800
    close = 0.001 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return _frame(close, rng.uniform(1e3, 5e3, n), seed=7)


@pytest.fixture(scope="module")
def pump() -> pd.DataFrame:
    """Flat, then a steady climb on rising volume, then a rug."""
    rng = np.random.default_rng(3)
    steps = np.r_[rng.normal(0, 0.004, 200), rng.normal(0.012, 0.004, 120), [-0.6], rng.normal(0, 0.004, 80)]
    close = 0.001 * np.exp(np.cumsum(steps))
    volume = np.r_[rng.uniform(1e3, 2e3, 200), rng.uniform(6e3, 9e3, 120), [5e4], rng.uniform(1e3, 2e3, 80)]
    return _frame(close, volume, seed=3)


def test_registered_as_trend_following():
    assert NAME in AVAILABLE_STRATEGIES
    assert STRATEGY_FAMILY[NAME] == FAMILY_TREND
    assert NAME in [c["strategy_name"] for c in radar.strategy_configs()]


def test_long_only(noise, pump):
    for df in (noise, pump):
        sig = compute_lorenzo_hf_signals(df)
        assert not sig["entry_short"].any()
        assert not sig["exit_short"].any()


def test_edges_alternate_and_never_share_a_bar(noise):
    sig = compute_lorenzo_hf_signals(
        noise, {"volume_mult": 0, "er_min": 0, "slope_threshold_sigma": 0, "vwap_filter": False})
    assert not (sig["entry_long"] & sig["exit_long"]).any()
    marks = [("in" if e else "out") for e, x in zip(sig["entry_long"], sig["exit_long"]) if e or x]
    assert marks, "senza filtri il rumore deve pur generare qualche ingresso"
    assert all(a != b for a, b in zip(marks, marks[1:]))
    assert marks[0] == "in"


def test_no_lookahead(noise):
    params = {"volume_mult": 1.2, "er_min": 0.2, "vr_min": 0.8}
    full = compute_lorenzo_hf_signals(noise, params)
    for cut in (150, 400, 650):
        part = compute_lorenzo_hf_signals(noise.iloc[:cut], params)
        pd.testing.assert_frame_equal(part, full.iloc[:cut])


def test_rides_the_pump_and_is_out_by_the_rug(pump):
    sig = compute_lorenzo_hf_signals(pump)
    entries = np.flatnonzero(sig["entry_long"])
    exits = np.flatnonzero(sig["exit_long"])
    assert len(entries) >= 1
    early = [i for i in entries if 200 <= i < 230]
    assert early, "deve entrare all'inizio della salita, non a meta'"
    held = min(x for x in exits if x > early[0]) - early[0]
    assert held >= 30, "e restarci dentro per buona parte della salita"
    rug = 320
    last_in = max(i for i in entries if i <= rug)
    assert any(last_in < x <= rug for x in exits), "nessuna posizione aperta dopo la candela del crollo"


def test_trailing_stop_exits_before_the_crossunder(pump):
    rug = 320
    with_trail = np.flatnonzero(compute_lorenzo_hf_signals(pump)["exit_long"])
    without = np.flatnonzero(compute_lorenzo_hf_signals(pump, {"trail_atr": 0})["exit_long"])
    first = lambda xs: min(x for x in xs if x >= 200)  # noqa: E731
    assert first(with_trail) <= rug
    assert first(with_trail) <= first(without)


def test_filters_cut_trading_on_noise(noise):
    bare = compute_lorenzo_hf_signals(
        noise, {"volume_mult": 0, "er_min": 0, "slope_threshold_sigma": 0, "vwap_filter": False})
    default = compute_lorenzo_hf_signals(noise)
    assert default["entry_long"].sum() < bare["entry_long"].sum()


def test_backtest_matches_signal_edges(pump):
    events, _ = confirmed_events(pump, None, strategy_name=NAME)
    sig = compute_lorenzo_hf_signals(pump)
    confirmed = sig.iloc[:-1]
    assert sum(e.type == "entry_long" for e in events) == int(confirmed["entry_long"].sum())
    result = run_backtest(pump, None, radar.BACKTEST_PARAMS, strategy_name=NAME)
    assert all(t.direction == "long" for t in result.trades)
