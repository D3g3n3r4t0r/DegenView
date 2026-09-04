"""Fermare una ricerca a metà.

Segnalato: una ricerca stabile può durare dieci minuti, e se l'hai lanciata
sulla coppia sbagliata devi aspettare che finisca — con la macchina occupata
nel frattempo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app import jobs
from app.analysis.cancel import SearchCancelled, stop_if_asked
from app.analysis.optimize import optimize_strategy
from app.analysis.plateau import plateau_search
from app.analysis.priors import build_spaces, estimate_series_stats

LORENZO = "Lorenzo (trend-follower)"


def _series(n=400, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": rng.uniform(1e6, 5e6, n)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


def _after(n: int):
    """Si ferma dopo n chiamate: è il modo di provare l'interruzione senza
    dipendere da quanto è veloce la macchina che esegue i test."""
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > n

    return should_stop


# --- il segnale ------------------------------------------------------------


def test_no_callback_never_stops():
    stop_if_asked(None)


def test_a_false_callback_never_stops():
    stop_if_asked(lambda: False)


def test_a_true_callback_raises():
    with pytest.raises(SearchCancelled):
        stop_if_asked(lambda: True)


# --- dentro le ricerche ----------------------------------------------------


def test_the_quick_search_stops_mid_way():
    with pytest.raises(SearchCancelled):
        optimize_strategy(LORENZO, _series(), {}, trials=200, seed=1,
                          should_stop=_after(5))


def test_the_stable_search_stops_during_the_boundary_scan():
    """Il punto più lungo è la mappatura: fermarsi solo dopo sarebbe inutile."""
    st = estimate_series_stats(_series())
    cs = build_spaces(LORENZO, st)[0]
    with pytest.raises(SearchCancelled):
        plateau_search(LORENZO, _series(), {}, base_points=1, coarse=6,
                       max_grid_evals=500, space=cs.as_param_space(),
                       should_stop=_after(3))


def test_the_stable_search_stops_while_trying_cells():
    st = estimate_series_stats(_series())
    cs = build_spaces(LORENZO, st)[0]
    with pytest.raises(SearchCancelled):
        plateau_search(LORENZO, _series(), {}, base_points=1, coarse=4,
                       max_grid_evals=500, space=cs.as_param_space(),
                       should_stop=_after(200))


def test_a_search_that_is_never_stopped_completes():
    res = optimize_strategy(LORENZO, _series(), {}, trials=25, seed=1,
                            should_stop=lambda: False)
    assert res[2] > 0


# --- il lavoro -------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate():
    jobs._jobs.clear()


def test_asking_to_stop_is_visible_to_the_worker():
    jid = jobs.create("u1", "optimize", "x")
    assert jobs.cancel_requested(jid) is False
    assert jobs.request_cancel(jid, "u1") is True
    assert jobs.cancel_requested(jid) is True


def test_someone_else_cannot_stop_your_search():
    jid = jobs.create("u1", "optimize", "x")
    assert jobs.request_cancel(jid, "u2") is False
    assert jobs.cancel_requested(jid) is False


def test_a_stopped_job_is_not_reported_as_failed():
    """Un lavoro fermato apposta che compare come 'fallito' fa cercare un
    guasto che non c'è."""
    jid = jobs.create("u1", "optimize", "x")
    jobs.cancelled(jid)
    j = jobs.get(jid, "u1")
    assert j["state"] == "annullato"
    assert j["error"] == ""


def test_stopping_an_unknown_job_says_so():
    assert jobs.request_cancel("non-esiste", "u1") is False
    assert jobs.cancelled("non-esiste") is None
