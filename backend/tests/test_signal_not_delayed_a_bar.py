"""
Un segnale su una candela GIA' CHIUSA non deve aspettare la candela dopo.

Il difetto, misurato prima di correggerlo con tools/simulate_alerts.py su 10
ticker reali: **ogni** alert partiva con +24,0 ore esatte su timeframe
giornaliero. Non un caso isolato, non la finestra di freschezza: una doppia
protezione contro la candela in formazione.

- il watcher, per le voci con "alla chiusura della candela", toglie gia' la
  barra in formazione (`drop_unclosed_candle`);
- `confirmed_events` scartava POI un'altra barra (`df.index[-2]`), come se
  l'ultima fosse sempre ancora in formazione.

Risultato: l'ultima riga rimasta — una candela chiusa e definitiva — veniva
trattata come non confermata, e il suo segnale emergeva solo al giro
successivo. Su un daily, un giorno intero. E' il caso INJUSDT: incrocio alla
chiusura del 14 settembre, notifica il 16, prezzo sceso del 13,5% nel mezzo.

Lorenzo: "deve arrivare l'alert alla chiusura della candela del timeframe
considerato, non tre giorni dopo... e' importante che questa cosa non accada
con nessun alert".
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.analysis.strategies import confirmed_events, last_bar_is_closed

DAY = 86400


def _frame(n: int, end_open: int) -> pd.DataFrame:
    """Serie giornaliera che termina con la candela aperta a `end_open`."""
    idx = pd.to_datetime(
        [(end_open - (n - 1 - i) * DAY) * 1000 for i in range(n)], unit="ms", utc=True,
    )
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close,
         "volume": np.full(n, 1000.0)},
        index=idx,
    )


def _signals_with_entry_on_last_bar(df: pd.DataFrame) -> pd.DataFrame:
    """Un ingresso esattamente sull'ultima riga, e nient'altro."""
    false_col = pd.Series(False, index=df.index)
    entry = false_col.copy()
    entry.iloc[-1] = True
    return pd.DataFrame(
        {"entry_long": entry, "entry_short": false_col,
         "exit_long": false_col, "exit_short": false_col},
        index=df.index,
    )


def test_a_closed_last_bar_is_recognised_as_closed():
    now = int(time.time())
    closed = _frame(60, end_open=now - 2 * DAY)      # chiusa da un giorno
    forming = _frame(60, end_open=now - DAY // 2)    # aperta mezza giornata fa
    assert last_bar_is_closed(closed) is True
    assert last_bar_is_closed(forming) is False


def test_a_signal_on_a_closed_bar_fires_without_waiting_for_the_next_one():
    """Il caso INJUSDT, ridotto all'osso."""
    now = int(time.time())
    df = _frame(60, end_open=now - 2 * DAY)          # l'ultima candela e' chiusa
    signals = _signals_with_entry_on_last_bar(df)

    events, _ = confirmed_events(df, signals=signals, last_bar_closed=True)

    assert events, "un segnale su una candela chiusa non puo' restare invisibile"
    assert events[-1].time == int(df.index[-1].timestamp())


def test_a_signal_on_a_still_forming_bar_is_still_withheld():
    """L'altra meta' della regola resta: una candela in formazione ripaint.

    Senza questo, il segnale comparirebbe e sparirebbe ad ogni fetch mentre il
    prezzo si muove, spedendo la stessa notifica piu' volte.
    """
    now = int(time.time())
    df = _frame(60, end_open=now - DAY // 2)         # ultima candela ancora aperta
    signals = _signals_with_entry_on_last_bar(df)

    events, _ = confirmed_events(df, signals=signals, last_bar_closed=last_bar_is_closed(df))

    assert not events, "una candela ancora in formazione non e' un segnale confermato"


def test_backtests_keep_the_old_conservative_rule_by_default():
    """`last_bar_closed` e' False di default apposta.

    confirmed_events() alimenta anche run_backtest(): se il default cambiasse,
    cambierebbero i numeri di ogni risultato storico gia' archiviato — una
    cosa che in questo progetto si chiede, non si subisce.
    """
    now = int(time.time())
    df = _frame(60, end_open=now - 2 * DAY)
    signals = _signals_with_entry_on_last_bar(df)

    events, _ = confirmed_events(df, signals=signals)

    assert not events
