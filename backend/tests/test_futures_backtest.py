"""Validazione del motore futures — Fase 2 del piano "Operazioni futures".

Fino a quando questi test non sono verdi, nessuna esecuzione reale futures
va costruita (vedi il piano): qui si prova che il modello di leva, margine
isolated, liquidazione e funding sia corretto contro casi noti, non solo
che il codice giri senza eccezioni.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest
from app.analysis.futures_backtest import (
    DEFAULT_FUTURES_PARAMS,
    InvalidLeverageError,
    run_futures_backtest,
)
from app.models import MAX_FUTURES_LEVERAGE


def _trending_series(n=300, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.015, n)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": rng.uniform(1e6, 5e6, n)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


def test_leverage_1_matches_spot_exactly():
    """Il primo test di correttezza del piano: a leva 1, senza funding, il
    motore futures deve produrre lo stesso equity finale dello spot per lo
    stesso segnale — leva 1 e' economicamente equivalente allo spot."""
    df = _trending_series()
    bp = {"initial_capital": 10000.0, "qty_pct_of_equity": 30.0,
          "commission_pct": 0.06, "slippage_pct": 0.02}

    spot = run_backtest(df, None, bp, strategy_name="Lorenzo (trend-follower)")
    futures = run_futures_backtest(df, None, {**bp, "leverage": 1}, strategy_name="Lorenzo (trend-follower)")

    assert spot.num_trades > 0, "serve almeno un trade per un confronto significativo"
    assert futures.num_trades == spot.num_trades
    assert futures.final_equity == pytest.approx(spot.final_equity, rel=1e-9)
    assert futures.liquidated_count == 0


def test_leverage_1_never_liquidates_on_realistic_moves():
    df = _trending_series(seed=11)
    res = run_futures_backtest(df, None, {"leverage": 1}, strategy_name="Lorenzo (trend-follower)")
    assert res.liquidated_count == 0
    assert all(not t.liquidated for t in res.trades)


def test_forced_liquidation_closes_at_the_liquidation_price_not_the_strategy_stop():
    """Serie sintetica con un crollo che supera la distanza di liquidazione
    a leva alta: la posizione deve chiudersi al prezzo di liquidazione, non
    al prezzo del bar successivo ne' a uno stop della strategia."""
    n = 60
    close = np.full(n, 100.0)
    high = close * 1.001
    low = close * 0.999
    # Entra long presto, poi un crollo del 30% in una barra molto oltre la
    # distanza di liquidazione a 10x (~10% + margine di manutenzione).
    close[20] = 70.0
    low[20] = 68.0
    high[20] = 100.5
    df = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close,
         "volume": np.full(n, 2e6)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )
    # Nessun segnale via strategia — apriamo/chiudiamo a mano passando un
    # frame 'signals' pre-costruito (stesso formato booleano che
    # confirmed_events() si aspetta) per isolare il comportamento del
    # motore dalla logica di una strategia specifica.
    signals = pd.DataFrame(
        {"entry_long": False, "entry_short": False, "exit_long": False, "exit_short": False},
        index=df.index,
    )
    signals.loc[df.index[5], "entry_long"] = True
    signals.loc[df.index[50], "exit_long"] = True

    res = run_futures_backtest(
        df, None, {"leverage": 10, "commission_pct": 0, "slippage_pct": 0},
        signals=signals,
    )
    assert res.liquidated_count == 1
    liquidated_trades = [t for t in res.trades if t.liquidated]
    assert len(liquidated_trades) == 1
    lt = liquidated_trades[0]
    assert lt.exit_price == pytest.approx(lt.liquidation_price, rel=1e-9)
    # Il margine impegnato e' perso per intero.
    assert lt.pnl_abs == pytest.approx(-lt.margin_used, rel=1e-6)


def test_funding_accrues_on_an_open_position_across_funding_hours():
    n = 7
    close = np.full(n, 100.0)
    df = pd.DataFrame(
        {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close,
         "volume": np.full(n, 1e6)},
        index=pd.date_range("2022-01-01 00:00", periods=n, freq="8h"),
    )
    signals = pd.DataFrame(
        {"entry_long": False, "entry_short": False, "exit_long": False, "exit_short": False},
        index=df.index,
    )
    signals.loc[df.index[0], "entry_long"] = True
    signals.loc[df.index[4], "exit_long"] = True
    res = run_futures_backtest(
        df, None,
        {"leverage": 2, "commission_pct": 0, "slippage_pct": 0,
         "qty_pct_of_equity": 50.0, "funding_rate_8h": 0.0004},
        signals=signals,
    )
    assert res.num_trades == 1
    trade = res.trades[0]
    # Ogni barra alle 00/08/16 UTC mentre la posizione e' aperta attraversa
    # un orario di funding, barra di chiusura inclusa (si e' rimasti dentro
    # fino a quell'istante): barre a index 1,2,3,4 — 4 attraversamenti.
    margin_used = 10000.0 * 0.5
    notional = margin_used * 2
    expected_funding = notional * 0.0004 * 4
    assert trade.funding_paid == pytest.approx(expected_funding, rel=1e-6)


def test_default_leverage_is_one():
    assert DEFAULT_FUTURES_PARAMS["leverage"] == 1


def test_leverage_above_the_cap_is_rejected_before_running():
    df = _trending_series()
    with pytest.raises(InvalidLeverageError):
        run_futures_backtest(df, None, {"leverage": MAX_FUTURES_LEVERAGE + 1},
                              strategy_name="Lorenzo (trend-follower)")


def test_leverage_below_one_is_rejected():
    df = _trending_series()
    with pytest.raises(InvalidLeverageError):
        run_futures_backtest(df, None, {"leverage": 0}, strategy_name="Lorenzo (trend-follower)")
