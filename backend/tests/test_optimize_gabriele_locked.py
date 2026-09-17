"""
Il tasto Ottimizza per le due varianti Gabriele deve toccare solo RSI
ipercomprato/ipervenduto, lasciando lunghezza RSI, lunghezza Bollinger e
moltiplicatore esattamente ai valori messi da chi cerca nei campi del Lab.

Segnalazione 72f880af (whitekobra): "lascia sempre predefiniti i parametri
LUNGHEZZA RSI (14) LUNGHEZZA BOLLINGER (20) e MOLTIPLICATORE BOLLINGER (2).
Intervieni solo sui parametri RSI IPERCOMPRATO e RSI IPERVENDUTO" — non era
un difetto da spiegare, era una richiesta: la ricerca (in tutte e tre le
modalita', random/grid/plateau) deve rispettarla davvero, non solo lasciare
quei tre parametri vicino ai default per come si comporta a caso.
"""

import random

from app.analysis.optimize import (
    _GRID_GABRIELE,
    _grid_candidates,
    _random_gabriele_params,
    grid_size,
)


def test_random_search_only_touches_overbought_oversold():
    rng = random.Random(0)
    base = {"rsi_length": 9, "bb_length": 33, "bb_mult": 1.7}
    for _ in range(50):
        p = _random_gabriele_params(rng, base)
        assert p["rsi_length"] == 9
        assert p["bb_length"] == 33
        assert p["bb_mult"] == 1.7
        assert 15 <= p["rsi_oversold"] <= 40
        assert 60 <= p["rsi_overbought"] <= 85


def test_random_search_falls_back_to_defaults_without_base():
    rng = random.Random(1)
    p = _random_gabriele_params(rng)
    assert p["rsi_length"] == 14
    assert p["bb_length"] == 20
    assert p["bb_mult"] == 2.0


def test_grid_only_enumerates_overbought_oversold():
    assert set(_GRID_GABRIELE.keys()) == {"rsi_oversold", "rsi_overbought"}
    candidates = list(_grid_candidates("Gabriele (RSI+BB reversal)"))
    assert len(candidates) == grid_size("Gabriele (RSI+BB reversal)")
    for c in candidates:
        assert set(c.keys()) == {"rsi_oversold", "rsi_overbought"}
