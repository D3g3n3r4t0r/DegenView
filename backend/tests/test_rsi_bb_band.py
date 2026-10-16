"""RSI+BB BTC band (Lorenzo, 16/10: "Si, aggiungila al sito"): with BTC above
its weekly Bull Market Support Band either RSI oversold or a close under the
lower band opens the long, below it both; out above the middle band."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import btc_regime
from app.analysis.backtest import run_backtest
from app.analysis.strategies import (
    AVAILABLE_STRATEGIES,
    RSI_BB_BTC_BAND,
    STRATEGY_REGISTRY,
    _wilder_rma,
)

N = 1500
_IDX = pd.date_range("2020-01-01", periods=N, freq="D", tz="UTC")
_C = 100 * np.exp(np.cumsum(np.random.default_rng(4).normal(0, 0.03, N)))
DF = pd.DataFrame({"open": _C, "high": _C * 1.01, "low": _C * 0.99, "close": _C, "volume": 1.0}, index=_IDX)


def _btc(rising_until: str) -> pd.Series:
    idx = pd.date_range("2018-01-01", "2024-12-31", freq="D", tz="UTC")
    v = np.where(idx < pd.Timestamp(rising_until, tz="UTC"), np.linspace(5_000, 60_000, len(idx)), np.nan)
    s = pd.Series(v, index=idx)
    last = s.last_valid_index()
    s[s.isna()] = np.linspace(s[last], s[last] * 0.2, int(s.isna().sum()))
    return s


@pytest.fixture(autouse=True)
def _clean():
    yield
    btc_regime.clear()


def _parts(df):
    close = df["close"]
    d = close.diff()
    g, lo = _wilder_rma(d.clip(lower=0), 14), _wilder_rma(-d.clip(upper=0), 14)
    rsi = 100 - 100 / (1 + g / lo)
    basis = close.rolling(20).mean()
    lower = basis - 2.0 * close.rolling(20).std(ddof=0)
    return (rsi < 28).to_numpy(), (close < lower).to_numpy(), (close > basis).to_numpy()


def test_hidden_but_registered():
    # a trial, out of the menus since 16/10 (saved alerts keep running)
    assert RSI_BB_BTC_BAND not in AVAILABLE_STRATEGIES and RSI_BB_BTC_BAND in STRATEGY_REGISTRY


def test_either_above_the_band_both_below_exit_at_the_middle():
    btc_regime.set_closes(_btc("2022-01-01"), pin=True)
    sig = STRATEGY_REGISTRY[RSI_BB_BTC_BAND](DF, {})
    up = btc_regime.band_mask(DF.index)
    assert up.any() and (~up).any()
    rsi_lo, under, above_mid = _parts(DF)
    want = (up & (rsi_lo | under)) | (~up & rsi_lo & under)
    assert np.array_equal(sig["entry_long"].to_numpy(), want)
    assert np.array_equal(sig["exit_long"].to_numpy(), above_mid)
    assert not sig["entry_short"].any() and not sig["exit_short"].any()


def test_more_trades_than_the_rsi_bb_reversal_while_btc_is_up():
    btc_regime.set_closes(_btc("2030-01-01"), pin=True)
    n = run_backtest(DF, {}, {}, strategy_name=RSI_BB_BTC_BAND).num_trades
    assert n > run_backtest(DF, {}, {}, strategy_name="Gabriele (RSI+BB reversal)").num_trades


def test_band_uses_closed_weeks_only():
    s = _btc("2030-01-01")
    btc_regime.set_closes(s, pin=True)
    full = btc_regime.band_mask(_IDX)
    btc_regime.set_closes(s[s.index < pd.Timestamp("2022-06-15", tz="UTC")], pin=True)
    cut = btc_regime.band_mask(_IDX[_IDX < pd.Timestamp("2022-06-15", tz="UTC")])
    assert np.array_equal(cut, full[: len(cut)])


def test_no_btc_data_is_an_error():
    with pytest.raises(btc_regime.BtcRegimeUnavailable):
        STRATEGY_REGISTRY[RSI_BB_BTC_BAND](DF, {})


def test_status_for_the_top_bar_badge():
    assert btc_regime.status() == {"loaded": False}
    btc_regime.set_closes(_btc("2022-01-01"), pin=True)
    st = btc_regime.status()
    assert st["loaded"] and st["ema21"]["up"] is False and st["band"]["up"] is False
    # both turned down in early 2022, on a Monday
    for k in ("ema21", "band"):
        since = pd.Timestamp(st[k]["since"])
        assert since.dayofweek == 0 and pd.Timestamp("2022-01-01") <= since < pd.Timestamp("2022-04-01")
