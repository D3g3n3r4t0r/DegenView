"""
Come vengono disegnate le imbalance (FVG).

La segnalazione seed-0004 chiede lo stile TradingView, e le differenze
rimaste erano due, entrambe misurabili senza discutere di gusti:

  * i vuoti consecutivi venivano fusi in un box solo, alto quanto due o tre
    imbalance messe insieme — un intervallo di prezzo che come vuoto non e'
    mai esistito;
  * il grafico teneva le sei piu' recenti, riempite comprese, quindi un vuoto
    ancora aperto — l'unico tipo che serve guardare — spariva appena se ne
    formavano e richiudevano altri sei piu' recenti.
"""

from __future__ import annotations

import pandas as pd

from app.analysis import smc_engine as se


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    return pd.DataFrame(rows, index=idx,
                        columns=["open", "high", "low", "close", "volume"])


def _two_consecutive_gaps() -> pd.DataFrame:
    rows = [[100.0, 101.0, 99.0, 100.0, 10.0] for _ in range(3)]
    rows.append([110.0, 115.0, 109.0, 114.0, 10.0])   # primo salto
    rows.append([120.0, 126.0, 119.0, 125.0, 10.0])   # secondo salto, attaccato
    rows.extend([[125.0, 126.0, 124.0, 125.0, 10.0] for _ in range(6)])
    return _frame(rows)


def test_consecutive_gaps_stay_separate():
    levels = se._fvg_levels(_two_consecutive_gaps())
    assert len(levels) == 2, "due vuoti attaccati sono due zone, non una alta il doppio"
    spans = sorted((round(x.price_low), round(x.price_high)) for x in levels)
    assert spans == [(101, 119), (115, 124)]
    # Fusi darebbero un unico box 101-124, che nessuna singola candela ha lasciato.
    assert not any(low <= 101 and high >= 124 for low, high in spans)


def test_the_box_starts_at_the_first_of_the_three_candles():
    """Il vuoto sta fra la PRIMA e la TERZA candela: la libreria segna quella
    di mezzo, e partire da li' comincia una barra dopo rispetto a TradingView."""
    df = _two_consecutive_gaps()
    first = min(se._fvg_levels(df), key=lambda x: x.start_time)
    assert first.start_time == int(df.index[2].timestamp())


def test_open_gaps_survive_the_cap_before_filled_ones():
    """Sei zone riempite recenti non devono nascondere una ancora aperta."""
    open_old = [
        se.LiquidityLevel(type="fvg", direction="bullish", price_high=2.0, price_low=1.0,
                          start_time=1000, end_time=None, mitigated=False, label="aperta")
    ]
    filled_recent = [
        se.LiquidityLevel(type="fvg", direction="bullish", price_high=2.0, price_low=1.0,
                          start_time=2000 + i, end_time=3000, mitigated=True, label=f"chiusa {i}")
        for i in range(8)
    ]
    kept = se._cap_recent_per_type(filled_recent + open_old)
    assert any(x.label == "aperta" for x in kept)
    assert len(kept) == se._LEVEL_LIMIT_PER_TYPE["fvg"]


def test_other_level_types_are_still_capped_by_recency_alone():
    obs = [
        se.LiquidityLevel(type="order_block", direction="bullish", price_high=2.0, price_low=1.0,
                          start_time=t, end_time=None, mitigated=(t < 5), label=str(t))
        for t in range(10)
    ]
    kept = se._cap_recent_per_type(obs)
    assert [x.label for x in kept] == [str(t) for t in range(9, 9 - len(kept), -1)]
