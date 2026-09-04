"""Espansione guidata al posto del sorteggio.

Quando la griglia supera il budget, le celle venivano estratte a caso: era
l'unico punto in cui la ricerca tirava i dadi, e il pezzo che rendeva "non
riproducibile" una parte del risultato. Ora si apre sempre la cella più
promettente e si valutano le sue vicine — come un navigatore che non percorre
tutte le strade.

Misurato su KASUSDT daily, ramo a 7 parametri, 93 312 celle, budget 700:
guidata 57.44 contro 50.39 / 26.93 / 37.35 di tre sorteggi diversi.
"""

from __future__ import annotations

import numpy as np

from app.analysis.plateau import _guided_cells, _lattice_starts, plateau_search
from app.analysis.priors import build_spaces, estimate_series_stats

LORENZO = "Lorenzo (trend-follower)"


def _series(n=500, seed=7):
    import pandas as pd
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": rng.uniform(1e6, 5e6, n)},
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


# --- le partenze ----------------------------------------------------------


def test_starts_are_spread_and_distinct():
    starts = _lattice_starts([6, 6, 6, 4], 8)
    assert len(starts) == len(set(starts)) == 8


def test_starts_stay_inside_the_lattice():
    sizes = [3, 5, 2]
    for node in _lattice_starts(sizes, 6):
        assert all(0 <= node[i] < sizes[i] for i in range(len(sizes)))


def test_a_tiny_lattice_does_not_loop_forever():
    assert len(_lattice_starts([1, 1], 8)) == 1


def test_the_starts_are_the_same_every_time():
    """La ricerca guidata esiste anche per togliere la variabilità fra corse:
    ripescarla nel punto di partenza sarebbe autolesionista."""
    assert _lattice_starts([7, 5, 3], 8) == _lattice_starts([7, 5, 3], 8)


# --- l'espansione ---------------------------------------------------------


def _lattice(sizes):
    """Celle uguali su ogni asse: qui interessa il cammino, non la partizione."""
    from app.analysis.plateau import AxisPartition

    return [
        AxisPartition(dim=d, name=f"a{d}",
                      boundaries=tuple((i + 1) / s for i in range(s - 1)))
        for d, s in enumerate(sizes)
    ]


def test_the_budget_is_respected():
    sizes = [8, 8, 8]
    centers = [np.linspace(0.1, 0.9, s) for s in sizes]
    parts = _lattice(sizes)
    seen = []
    used = _guided_cells(sizes, centers, parts, 20, lambda u: (seen.append(u), 1.0)[1])
    assert used == len(seen) == 20


def test_it_walks_towards_the_good_region():
    """La prova che non è un sorteggio travestito: con un ottimo in un angolo,
    le celle valutate devono addensarsi lì."""
    sizes = [12, 12]
    centers = [np.linspace(0.0, 1.0, s) for s in sizes]
    parts = _lattice(sizes)
    visited = []

    def score(u):
        visited.append(u)
        return -float(np.sum((u - np.array([1.0, 1.0])) ** 2))  # ottimo in alto a destra

    _guided_cells(sizes, centers, parts, 60, score)
    near = sum(1 for u in visited if u[0] > 0.6 and u[1] > 0.6)
    assert near > len(visited) * 0.35, f"solo {near} su {len(visited)} vicino all'ottimo"


def test_the_same_lattice_gives_the_same_walk():
    sizes = [10, 10]
    centers = [np.linspace(0.0, 1.0, s) for s in sizes]
    parts = _lattice(sizes)

    def run():
        seen = []
        _guided_cells(sizes, centers, parts, 40,
                      lambda u: (seen.append(tuple(u)), -float(np.sum(u ** 2)))[1])
        return seen

    assert run() == run()


def test_a_flat_surface_does_not_stall_the_expansion():
    """Su un terreno piatto ogni cella vale uguale: deve comunque consumare il
    budget invece di fermarsi alla prima."""
    sizes = [6, 6]
    centers = [np.linspace(0.0, 1.0, s) for s in sizes]
    parts = _lattice(sizes)
    n = _guided_cells(sizes, centers, parts, 25, lambda _u: 1.0)
    assert n == 25


def test_infinite_scores_are_not_expanded_from():
    sizes = [6, 6]
    centers = [np.linspace(0.0, 1.0, s) for s in sizes]
    parts = _lattice(sizes)
    n = _guided_cells(sizes, centers, parts, 30, lambda _u: float("-inf"))
    assert n <= 8, "senza punteggi finiti restano solo le partenze"


# --- dentro la ricerca vera -----------------------------------------------


def test_a_sampled_branch_is_now_seed_independent():
    """Era l'unico punto che cambiava col seme, e la nota lo dichiarava."""
    df = _series(400, seed=3)
    st = estimate_series_stats(df)
    cs = build_spaces(LORENZO, st)[-1]      # il ramo più largo
    found = []
    for seed in (0, 1, 2):
        res = plateau_search(LORENZO, df, {}, base_points=1, coarse=4, max_grid_evals=60,
                             finalists=3, probe_samples=3,
                             space=cs.as_param_space(), seed=seed)
        assert res.best is not None
        found.append(res.best.params)
    assert found[0] == found[1] == found[2], "il risultato cambia ancora col seme"


def test_the_note_no_longer_claims_the_result_is_sampled():
    df = _series(400, seed=3)
    st = estimate_series_stats(df)
    cs = build_spaces(LORENZO, st)[-1]
    res = plateau_search(LORENZO, df, {}, base_points=1, coarse=4, max_grid_evals=60,
                         finalists=3, probe_samples=3, space=cs.as_param_space())
    if not res.enumerated:
        assert any("best-first" in n for n in res.notes)
        assert not any("sampling cell-centre" in n for n in res.notes)
