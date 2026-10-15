"""BTC filter (Lorenzo, 15/10: "Il filtro Btc può essere utile da
attivare/disattivare su tutte le strategie del sito?" — "Ok, implementiamo
così"): no long entry while BTC's previous daily close is under its EMA 200,
one switch per strategy, honoured by Run, alerts, archive and optimizations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import btc_regime
from app.analysis.optimize import optimize_strategy
from app.analysis.strategies import STRATEGY_REGISTRY

GAB = "Gabriele (RSI+BB reversal)"
N = 900
_IDX = pd.date_range("2022-01-01", periods=N, freq="D", tz="UTC")
_R = np.random.default_rng(7)
_C = 100 + np.cumsum(_R.normal(0, 2, N)) + 12 * np.sin(np.arange(N) / 6)
DF = pd.DataFrame({"open": _C, "high": _C + 1.5, "low": _C - 1.5, "close": _C,
                   "volume": np.full(N, 1000.0)}, index=_IDX)


def _btc(up_until: str, start="2020-01-01", end="2025-12-31"):
    """BTC rising until `up_until`, then falling hard."""
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    turn = idx.searchsorted(pd.Timestamp(up_until, tz="UTC"))
    path = np.r_[np.linspace(10_000, 60_000, turn), np.linspace(60_000, 5_000, len(idx) - turn)]
    return pd.Series(path, index=idx)


@pytest.fixture(autouse=True)
def _clean():
    btc_regime.clear()
    yield
    btc_regime.clear()


def test_regime_is_the_previous_day_and_open_before_the_history():
    btc_regime.set_closes(_btc("2023-06-01"), pin=True)
    idx = pd.date_range("2019-06-01", "2025-06-01", freq="4h", tz="UTC")
    up = pd.Series(btc_regime.up_mask(idx), index=idx)
    assert up[: "2019-12-31"].all()                  # no BTC history yet: no filter
    assert up["2020-01-01":"2020-07-01"].all()        # under 200 days of it: no filter
    assert up["2022-06-01":"2023-06-01"].all()        # rising: longs allowed
    assert not up["2024-01-01":"2025-06-01"].any()    # falling: blocked
    # one value per day, from the day before
    day = up["2023-09-10"]
    assert day.nunique() == 1


def test_switch_off_changes_nothing_and_on_only_blocks_long_entries():
    btc_regime.set_closes(_btc("2023-01-01"), pin=True)
    fn = STRATEGY_REGISTRY[GAB]
    raw = fn.__wrapped__(DF, {})
    assert fn(DF, {"btc_filter": False}).equals(raw)
    on = fn(DF, {"btc_filter": True})
    blocked = ~btc_regime.up_mask(DF.index)
    assert not on["entry_long"][blocked].any() and raw["entry_long"][blocked].any()
    assert on["entry_long"][~blocked].equals(raw["entry_long"][~blocked])
    for col in ("exit_long", "entry_short", "exit_short"):
        assert on[col].equals(raw[col])


def test_every_site_strategy_honours_it():
    btc_regime.set_closes(_btc("2022-03-01"), pin=True)      # down for almost all of DF
    for name, fn in STRATEGY_REGISTRY.items():
        sig = fn(DF, {"btc_filter": True})
        assert not sig["entry_long"][~btc_regime.up_mask(DF.index)].any(), name


def test_no_btc_data_is_an_error_not_a_silent_pass():
    with pytest.raises(btc_regime.BtcRegimeUnavailable):
        STRATEGY_REGISTRY[GAB](DF, {"btc_filter": True})
    STRATEGY_REGISTRY[GAB](DF, {"btc_filter": False})       # off: no BTC needed


def test_searches_keep_the_switch_on_every_candidate():
    btc_regime.set_closes(_btc("2023-01-01"), pin=True)
    seen = []
    import app.analysis.optimize as opt
    real = opt.run_backtest

    def spy(df, params, *a, **k):
        seen.append(params.get("btc_filter"))
        return real(df, params, *a, **k)
    opt.run_backtest = spy
    try:
        params, _, _, _, _, top = optimize_strategy(GAB, DF, {}, trials=12, seed=1, mode="random",
                                                    base_params={"btc_filter": True})
    finally:
        opt.run_backtest = real
    assert seen and all(v is True for v in seen)
    assert params["btc_filter"] is True and all(c["params"]["btc_filter"] is True for c in top)


def test_years_mostly_blocked_are_measured():
    btc_regime.set_closes(_btc("2023-01-01"), pin=True)
    assert btc_regime.down_share(2022) == 0.0
    assert btc_regime.down_share(2024) > 0.9
