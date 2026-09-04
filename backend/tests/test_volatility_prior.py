"""La volatilità della coppia entra nella strategia e nella ricerca.

Fino a ieri non c'era: gli intervalli dei parametri si ancoravano
all'autocorrelazione, alla mezza vita e al ciclo dominante, e la volatilità
compariva solo in un tetto di drawdown laterale. Su una coppia poco liquida che
si muove molto senza andare da nessuna parte, Lorenzo — che è un incrocio puro,
senza nessuna soglia — entra sul rumore per costruzione.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest
from app.analysis.priors import build_spaces, estimate_series_stats

LORENZO = "Lorenzo (trend-follower)"


def _series(drift: float, vol: float, n: int = 700, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + abs(rng.normal(0, vol / 2, n))),
            "low": close * (1 - abs(rng.normal(0, vol / 2, n))),
            "close": close,
            "volume": rng.uniform(1e6, 5e6, n),
        },
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


# --- le misure ------------------------------------------------------------


def test_efficiency_separates_a_trend_from_agitation():
    """È la misura che mancava: non 'quanto si muove' ma 'quanta strada
    percorre di quella che fa'."""
    trend = estimate_series_stats(_series(0.004, 0.01))
    chop = estimate_series_stats(_series(0.0, 0.01))
    assert trend.efficiency_ratio > 0.3
    assert chop.efficiency_ratio < 0.2


def test_volatility_and_direction_are_measured_separately():
    """Una altcoin agitata si muove molto E non va da nessuna parte: le due
    cose vanno lette separate, altrimenti sembra viva."""
    calm = estimate_series_stats(_series(0.0, 0.01))
    wild = estimate_series_stats(_series(0.0, 0.09))
    assert wild.sigma_bar > 5 * calm.sigma_bar
    assert wild.efficiency_ratio < 0.3, "molto movimento non è direzione"


def test_efficiency_stays_in_its_bounds():
    for d, v in ((0.02, 0.001), (0.0, 0.2), (-0.01, 0.05)):
        er = estimate_series_stats(_series(d, v)).efficiency_ratio
        assert 0.0 <= er <= 1.0


def test_illiquidity_is_none_rather_than_invented_when_volume_is_missing():
    df = _series(0.001, 0.02).drop(columns=["volume"])
    assert estimate_series_stats(df).illiquidity is None


def test_a_short_series_does_not_crash_the_estimator():
    st = estimate_series_stats(_series(0.001, 0.02, n=20))
    assert st.sigma_bar == 0.0 and st.efficiency_ratio == 0.0


# --- la soglia nella strategia --------------------------------------------


def test_zero_leaves_the_historical_behaviour_byte_identical():
    df = _series(0.0, 0.05)
    a = run_backtest(df, {}, {}, strategy_name=LORENZO)
    b = run_backtest(df, {"slope_threshold_sigma": 0.0}, {}, strategy_name=LORENZO)
    assert (a.total_return_pct, a.num_trades) == (b.total_return_pct, b.num_trades)


def test_the_threshold_removes_trades_on_a_noisy_pair():
    df = _series(0.0, 0.09)
    loose = run_backtest(df, {"slope_threshold_sigma": 0.0}, {}, strategy_name=LORENZO)
    strict = run_backtest(df, {"slope_threshold_sigma": 0.5}, {}, strategy_name=LORENZO)
    assert strict.num_trades < loose.num_trades
    assert abs(strict.max_drawdown_pct) < abs(loose.max_drawdown_pct)


def test_the_threshold_barely_touches_a_real_trend():
    """Se togliesse trade anche dove la direzione c'è, sarebbe un freno e basta."""
    df = _series(0.004, 0.01)
    loose = run_backtest(df, {"slope_threshold_sigma": 0.0}, {}, strategy_name=LORENZO)
    strict = run_backtest(df, {"slope_threshold_sigma": 0.5}, {}, strategy_name=LORENZO)
    assert strict.num_trades >= loose.num_trades - 2


def test_the_threshold_is_in_sigma_units_so_it_transfers_between_pairs():
    """Una soglia in valore assoluto sarebbe enorme su una coppia calma e
    invisibile su una agitata: la stessa k deve mordere in modo confrontabile."""
    calm, wild = _series(0.0, 0.01), _series(0.0, 0.09)
    def cut(df):
        a = run_backtest(df, {"slope_threshold_sigma": 0.0}, {}, strategy_name=LORENZO).num_trades
        b = run_backtest(df, {"slope_threshold_sigma": 0.8}, {}, strategy_name=LORENZO).num_trades
        return (a - b) / max(a, 1)
    assert abs(cut(calm) - cut(wild)) < 0.5


# --- la ricerca -----------------------------------------------------------


def test_the_threshold_is_searched_not_assumed():
    st = estimate_series_stats(_series(0.0, 0.06))
    for cs in build_spaces(LORENZO, st, 40):
        assert "slope_threshold_sigma" in cs.dims


def test_zero_stays_reachable_by_the_search():
    """Il comportamento storico deve restare dentro lo spazio, non fuori."""
    st = estimate_series_stats(_series(0.0, 0.06))
    cs = build_spaces(LORENZO, st, 40)[0]
    u = np.zeros(cs.d)
    assert cs.to_params(u)["slope_threshold_sigma"] == 0.0


def test_a_directionless_series_lifts_the_lookback_floor():
    """Su una serie che fa molta strada senza percorrere distanza, una finestra
    da 20 barre misura oscillazioni: non va cercata."""
    st = estimate_series_stats(_series(0.0, 0.05, n=900, seed=11))
    if st.efficiency_ratio >= 0.02:
        pytest.skip(f"serie troppo direzionale per il caso (ER={st.efficiency_ratio:.3f})")
    cs = build_spaces(LORENZO, st, 40)[0]
    shortest = cs.to_params(np.zeros(cs.d))["len"]
    assert shortest >= 60
