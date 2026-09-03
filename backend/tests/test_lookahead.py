"""La conferma non deve appoggiarsi a uno swing non ancora identificabile.

`smc.swing_highs_lows` usa una finestra centrata: uno swing in posizione P si
riconosce solo quando esistono `swing_length` barre successive. Confermare a
P+1 significa quindi decidere in base a qualcosa che a quel momento nessuno
poteva sapere — il backtest apre il trade, il bot dal vivo no.

È un guasto silenzioso: non solleva errori, non lascia tracce nei log, e si
manifesta solo come un backtest più bello del reale. Questi test lo bloccano.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from smartmoneyconcepts import smc

from app.analysis.strategies import EXHAUSTION_DEFAULT_PARAMS, _find_confirmation


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 900
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.03, n)))
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.003, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.02, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.02, n))),
            "close": close,
            "volume": rng.uniform(1e6, 5e6, n),
        },
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


def _swings(df: pd.DataFrame, swing_length: int):
    s = smc.swing_highs_lows(df, swing_length=swing_length)
    return ([(int(i), "long") for i in s[s["HighLow"] == -1].index]
            + [(int(i), "short") for i in s[s["HighLow"] == 1].index])


# --- la proprietà che conta ----------------------------------------------


@pytest.mark.parametrize("swing_length", [4, 8, 12])
def test_confirmation_never_precedes_the_detection_delay(df, swing_length):
    """Il test che deve fallire se qualcuno rimette `swing_pos + 1`."""
    checked = 0
    for pos, direction in _swings(df, swing_length):
        c = _find_confirmation(df, pos, direction, 10, swing_length)
        if c is None:
            continue
        checked += 1
        assert c - pos >= swing_length, (
            f"conferma a +{c - pos} barre da uno swing identificabile solo a "
            f"+{swing_length}: usa informazione futura"
        )
    assert checked > 0, "nessuna conferma trovata: il test non sta verificando nulla"


def test_the_old_behaviour_would_fail_this_test(df):
    """Ancora la proprietà, misurata sul comportamento precedente, così il test
    dimostra di poter fallire invece di passare per costruzione.

    Sui dati reali di KASUSDT il rapporto era 84 su 87, il 97%.
    """
    sl = 8
    early = total = 0
    for pos, direction in _swings(df, sl):
        c = _find_confirmation(df, pos, direction, 10, 0)   # swing_length=0 = vecchio
        if c is None:
            continue
        total += 1
        if c - pos < sl:
            early += 1
    assert total > 0
    assert early > 0, "il comportamento vecchio dovrebbe violare la causalità"


# --- il ritardo di rilevamento è davvero swing_length ---------------------


@pytest.mark.parametrize("swing_length", [4, 8])
def test_a_swing_is_not_identifiable_before_swing_length_bars(df, swing_length):
    """La premessa su cui poggia tutto il resto, verificata invece che assunta.

    Misurata cercando il primo istante in cui lo swing compare E non sparisce
    più: troncare la serie esattamente a P rende P l'ultima barra, quindi
    banalmente l'estremo, ed è un artefatto — non rilevamento.
    """
    swings = [p for p, _ in _swings(df, swing_length)]
    sample = swings[10:16]
    assert sample, "servono swing da campionare"

    for P in sample:
        if P + swing_length + 6 >= len(df):
            continue
        visible_early = False
        for k in range(1, swing_length):
            v = smc.swing_highs_lows(df.iloc[: P + k + 1], swing_length=swing_length)["HighLow"].to_numpy()
            here = P < len(v) and v[P] == v[P] and v[P] != 0
            stays = True
            for kk in range(k + 1, k + 5):
                v2 = smc.swing_highs_lows(df.iloc[: P + kk + 1], swing_length=swing_length)["HighLow"].to_numpy()
                if not (P < len(v2) and v2[P] == v2[P] and v2[P] != 0):
                    stays = False
                    break
            if here and stays:
                visible_early = True
                break
        assert not visible_early, (
            f"swing {P} risulta stabilmente rilevato prima di +{swing_length} barre: "
            "se cambia la libreria, l'offset della conferma va rivisto"
        )


# --- comportamento generale ----------------------------------------------


def test_confirmation_stays_within_the_lookahead_budget(df):
    sl, look = 8, 10
    for pos, direction in _swings(df, sl):
        c = _find_confirmation(df, pos, direction, look, sl)
        if c is not None:
            assert c < pos + sl + look


def test_no_confirmation_past_the_end_of_the_series(df):
    sl = 8
    last = len(df) - 1
    for pos in (last, last - 1, last - sl):
        c = _find_confirmation(df, pos, "long", 10, sl)
        assert c is None or c < len(df)


def test_default_swing_length_is_passed_through():
    """Il default non deve poter tornare a zero senza che qualcuno se ne accorga."""
    assert EXHAUSTION_DEFAULT_PARAMS["swing_length"] >= 1
