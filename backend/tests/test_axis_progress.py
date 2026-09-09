"""
Segnalato dal vivo, con uno screenshot: la ricerca stabile restava ferma su
"asse 0/5" per una quindicina di secondi senza che succedesse niente in
schermo, ne' nel log sotto.

Non era ferma — era al lavoro. "asse X: N confini -> M intervalli" arriva
solo a fine ricerca su QUELL'asse, e un asse pesante (piu' punti base, piu'
bisezioni) puo' metterci decine di secondi per il primo. Nel frattempo il
log non riceveva nessuna riga nuova: sembrava un blocco, non lo era.

Questi test tengono ferma la riga intermedia che risolve il sintomo, senza
toccare la mappatura vera e propria (ne' i confini trovati, ne' quanti
backtest sono costati).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.plateau import partition_axes
from app.analysis.sensitivity import ParamSpace


def _series(n=400, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": rng.uniform(1e6, 5e6, n)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


def _busy_len_axis() -> ParamSpace:
    """Un solo asse, 'len' su un intervallo ampio: abbastanza bisezioni da
    superare di sicuro le 12 valutazioni per far scattare la riga."""
    def to_params(u: np.ndarray) -> dict:
        length = int(round(2 + u[0] * 250))
        return {
            "average": "EMA", "len": max(length, 2), "slopeFlen": 7, "slopeSlen": 27,
            "trendfilter": False, "trendfilterperiod": 200, "trendfiltertype": "EMA",
            "volatilityfilter": False, "volatilitystdevlength": 20,
            "volatilitystdevmalength": 40, "slope_threshold_sigma": 0.0,
            "slope_sigma_length": 100,
        }
    return ParamSpace(("len",), to_params)


def test_a_slow_axis_reports_progress_before_it_finishes():
    df = _series()
    log: list[str] = []
    counter: dict = {"n": 0, "boundary": 0}
    partition_axes(
        df, "Lorenzo (trend-follower)", _busy_len_axis(), {},
        np.array([[0.5]]), coarse=12, progress=log.append, counter=counter,
    )
    mid = [m for m in log if "ancora al lavoro" in m]
    final = [m for m in log if m.startswith("asse len:")]
    assert final, "la riga finale dell'asse deve comunque arrivare"
    if counter["n"] > 12:
        assert mid, "un asse che costa piu' di 12 backtest deve dire qualcosa nel frattempo"
    for m in mid:
        assert "len" in m


def test_the_progress_line_does_not_pretend_to_be_the_final_mapping():
    """Non deve avere ne' 'confini' ne' 'intervalli': un parser che legge il
    log (com'e' l'animazione della ricerca) non la deve confondere con la
    riga vera che chiude l'asse."""
    df = _series()
    log: list[str] = []
    partition_axes(
        df, "Lorenzo (trend-follower)", _busy_len_axis(), {},
        np.array([[0.5]]), coarse=12, progress=log.append, counter={"n": 0, "boundary": 0},
    )
    for m in log:
        if "ancora al lavoro" in m:
            assert "confin" not in m
            assert "intervall" not in m


def test_progress_lines_are_evenly_spaced_by_backtest_count():
    df = _series()
    log: list[str] = []
    partition_axes(
        df, "Lorenzo (trend-follower)", _busy_len_axis(), {},
        np.array([[0.5]]), coarse=12, progress=log.append, counter={"n": 0, "boundary": 0},
    )
    counts = [int(m.split("—")[1].split("backtest")[0].strip())
              for m in log if "ancora al lavoro" in m]
    assert all(c % 12 == 0 for c in counts)
    assert counts == sorted(counts)


def test_a_cheap_axis_still_only_says_the_final_line():
    """Pochi punti, poche bisezioni: sotto 12 backtest non deve comparire
    nessuna riga intermedia — sarebbe rumore per un asse che finisce subito."""
    df = _series()
    log: list[str] = []
    counter: dict = {"n": 0, "boundary": 0}

    def to_params(u: np.ndarray) -> dict:
        return {
            "average": "EMA", "len": 130, "slopeFlen": 7, "slopeSlen": 27,
            "trendfilter": bool(u[0] > 0.5), "trendfilterperiod": 200, "trendfiltertype": "EMA",
            "volatilityfilter": False, "volatilitystdevlength": 20,
            "volatilitystdevmalength": 40, "slope_threshold_sigma": 0.0,
            "slope_sigma_length": 100,
        }
    space = ParamSpace(("trendfilter",), to_params)
    partition_axes(df, "Lorenzo (trend-follower)", space, {},
                    np.array([[0.5]]), coarse=4, progress=log.append, counter=counter)
    if counter["n"] <= 12:
        assert not any("ancora al lavoro" in m for m in log)
