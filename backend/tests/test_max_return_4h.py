"""Max return on RSI+BB 4H: the multiplier 2.0-2.8 joins the search and two
kinds of result come back (Lorenzo, 14/10: "il piu' solido in rapporto al
profitto e il piu' profittevole anche con una minore solidita', ma non deve
essere una solidita' completamente azzerata")."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis import optimize
from app.analysis.backtest import run_backtest
from app.analysis.strategies import RSI_BB_4H

N = 400
_C = 100 + np.cumsum(np.random.default_rng(9).normal(0, 2, N)) + 12 * np.sin(np.arange(N) / 6)
DF = pd.DataFrame({"open": _C, "high": _C + 1.5, "low": _C - 1.5, "close": _C, "volume": 1.0},
                  index=pd.date_range("2023-01-01", periods=N, freq="4h", tz="UTC"))


def _bt(p):
    return run_backtest(DF, p, {}, strategy_name=RSI_BB_4H)


def test_the_multiplier_range_is_2_0_to_2_8_by_tenths():
    assert optimize.MAX_RETURN_MULTS == [2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8]
    assert optimize.max_return_size_3d() == 961 * 9


def test_solidity_reads_the_neighbours():
    shelf = {(o, b, m): 100.0 for o in (19, 20, 21) for b in (69, 70, 71) for m in (2.4, 2.5, 2.6)}
    assert optimize.solidity((20, 70, 2.5), shelf)[0] == 1.0
    spike = dict(shelf)
    spike[(20, 70, 2.5)] = 400.0
    assert optimize.solidity((20, 70, 2.5), spike)[0] == 0.25
    assert optimize.solidity((20, 70, 2.5), {**spike, (20, 70, 2.5): -5.0})[0] == 0.0


def test_two_kinds_and_the_profitable_one_is_never_hollow(monkeypatch):
    monkeypatch.setattr(optimize, "MAX_RETURN_MULTS", [2.4, 2.5, 2.6])
    params, bt, n, out = optimize.max_return_search_3d(RSI_BB_4H, _bt, coarse=False)
    assert n == 961 * 3
    kinds = [c["kind"] for c in out]
    assert kinds in (["solid", "profitable"], ["solid+profitable"])
    for c in out:
        assert c["params"]["bb_mult"] in (2.4, 2.5, 2.6)
        assert c["solidity"] >= (optimize.SOLIDITY_FLOOR if "profitable" in c["kind"] else 0)
    if len(out) == 2:
        solid, profit = out
        assert profit["backtest"].total_return_pct >= solid["backtest"].total_return_pct
        assert solid["score"] >= profit["score"]


def test_coarse_pass_finds_what_the_full_grid_finds(monkeypatch):
    # 15/10: first pass at step 2 / 0.2, then full resolution around the best.
    monkeypatch.setattr(optimize, "MAX_RETURN_MULTS", [2.3, 2.4, 2.5, 2.6, 2.7])
    full = optimize.max_return_search_3d(RSI_BB_4H, _bt, coarse=False)
    fast = optimize.max_return_search_3d(RSI_BB_4H, _bt, coarse=True)
    assert fast[2] < full[2]
    best_full = full[3][0]["backtest"].total_return_pct * full[3][0]["solidity"]
    best_fast = fast[3][0]["backtest"].total_return_pct * fast[3][0]["solidity"]
    assert best_fast >= 0.9 * best_full
