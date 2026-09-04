"""Gabriele 2: la variante che sull'ipercomprato apre uno short.

Serve per i futures, dove si puo' stare corti davvero. Due cose vanno tenute
ferme: che gli short esistano, e che l'originale non sia cambiata — perche' e'
quella che gira sugli alert attivi, e cambiarne il comportamento riscriverebbe
i risultati storici di chi la usa gia'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest
from app.analysis.strategies import (
    AVAILABLE_STRATEGIES,
    compute_lki2_signals,
    compute_lki_signals,
)

ORIG = "Gabriele (RSI+BB reversal)"
NEW = "Gabriele 2 (RSI+BB long/short)"


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    n = 900
    close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.025, n)))
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.002, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.012, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.012, n))),
            "close": close,
            "volume": rng.uniform(1e6, 5e6, n),
        },
        index=pd.date_range("2021-01-01", periods=n, freq="D"),
    )


def test_it_is_registered_and_optimisable():
    from app.analysis.optimize import is_optimizable

    assert NEW in AVAILABLE_STRATEGIES
    assert is_optimizable(NEW)


def test_the_overbought_reaction_now_opens_a_short(df):
    a = compute_lki_signals(df)
    b = compute_lki2_signals(df)
    assert not a["entry_short"].any(), "l'originale non deve avere short"
    assert b["entry_short"].any(), "la variante deve averne"
    assert b["entry_short"].equals(a["exit_long"])


def test_the_long_side_is_untouched(df):
    a = compute_lki_signals(df)
    b = compute_lki2_signals(df)
    assert b["entry_long"].equals(a["entry_long"])


def test_the_position_flips_instead_of_going_flat(df):
    b = compute_lki2_signals(df)
    assert b["exit_short"].equals(b["entry_long"])
    assert b["exit_long"].equals(b["entry_short"])


def test_the_original_is_not_modified_by_importing_the_variant(df):
    """La variante e' costruita chiamando l'originale: se un giorno lo facesse
    in place, questo test lo direbbe."""
    before = compute_lki_signals(df).copy()
    compute_lki2_signals(df)
    assert compute_lki_signals(df).equals(before)


def test_the_backtest_actually_takes_short_trades(df):
    bt = run_backtest(df, None, {}, strategy_name=NEW)
    directions = {t.direction for t in bt.trades}
    assert "short" in directions, f"nessuno short fra {bt.num_trades} trade"


def test_the_two_strategies_do_not_produce_the_same_backtest(df):
    a = run_backtest(df, None, {}, strategy_name=ORIG)
    b = run_backtest(df, None, {}, strategy_name=NEW)
    assert (a.num_trades, a.total_return_pct) != (b.num_trades, b.total_return_pct)


def test_the_regime_gate_files_it_as_mean_reversion():
    from app.analysis.regime import STRATEGY_FAMILY, FAMILY_REVERSION

    assert STRATEGY_FAMILY[NEW] == FAMILY_REVERSION


def test_the_parameters_are_the_same_as_the_original():
    """Cosi' una configurazione trovata per l'una si porta sull'altra."""
    from app.analysis.strategies import LKI2_DEFAULT_PARAMS, LKI_DEFAULT_PARAMS

    assert LKI2_DEFAULT_PARAMS == LKI_DEFAULT_PARAMS
    assert LKI2_DEFAULT_PARAMS is not LKI_DEFAULT_PARAMS


# ── Confronto con il Pine originale, riga per riga ─────────────────────────
#
# Richiesta eb43d341: "modifica Gabriele 2 usando questo Pine Script". La
# strategia gia' e' quel Pine — ma "gia' lo fa" senza una verifica e' esatta
# quanto "non lo fa". Qui il Pine e' trascritto alla lettera, con le sue
# funzioni (rma di Wilder, stdev di popolazione, il ternario dell'rsi), e i
# segnali devono coincidere barra per barra.


def _pine_lki(df: pd.DataFrame, len_=14, length_bb=20, mult=2.0,
              oversold=28, overbought=72):
    src = df["close"]

    # up = rma(max(change(src), 0), len) · down = rma(-min(change(src), 0), len)
    change = src.diff()
    up = change.clip(lower=0).ewm(alpha=1 / len_, adjust=False).mean()
    down = (-change.clip(upper=0)).ewm(alpha=1 / len_, adjust=False).mean()

    # rsi = down == 0 ? 100 : up == 0 ? 0 : 100 - (100 / (1 + up / down))
    rsi = np.where(down == 0, 100.0,
                   np.where(up == 0, 0.0, 100 - (100 / (1 + up / down.replace(0, np.nan)))))
    rsi = pd.Series(rsi, index=df.index)

    # basis = sma(src, length_bb) · dev = mult * stdev(src, length_bb)
    basis = src.rolling(length_bb).mean()
    dev = mult * src.rolling(length_bb).std(ddof=0)   # Pine: deviazione di popolazione

    return (
        ((rsi < oversold) & (src < basis - dev)).fillna(False),    # entry_long
        ((rsi > overbought) & (src > basis + dev)).fillna(False),  # entry_short
    )


def test_gabriele2_is_bar_for_bar_the_pine_script(df):
    pine_long, pine_short = _pine_lki(df)
    ours = compute_lki2_signals(df)
    assert ours["entry_long"].equals(pine_long)
    assert ours["entry_short"].equals(pine_short)
    assert pine_long.sum() > 0 and pine_short.sum() > 0, "serie senza segnali: il test non proverebbe niente"


def test_the_pine_inputs_are_our_defaults():
    """len=14, BB Length=20, BB StdDev=2.0, e le soglie 28/72 scritte nelle
    condizioni del Pine."""
    from app.analysis.strategies import LKI2_DEFAULT_PARAMS as d
    assert (d["rsi_length"], d["bb_length"], d["bb_mult"]) == (14, 20, 2.0)
    assert (d["rsi_oversold"], d["rsi_overbought"]) == (28, 72)


def test_the_population_stdev_is_not_a_detail(df):
    """Con ddof=1 (deviazione campionaria) le bande sono piu' larghe e i
    segnali cambiano: e' il modo silenzioso di non essere piu' quel Pine."""
    src = df["close"]
    pop = src.rolling(20).std(ddof=0)
    sample = src.rolling(20).std(ddof=1)
    assert not np.allclose(pop.dropna(), sample.dropna())
