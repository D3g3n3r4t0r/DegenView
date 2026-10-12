"""
The optimized result is the same backtest Run computes (5571a9f1).

whitekobra: "changing the two RSI values by hand on SUI-USDT I got better
results than the automatic optimization in every mode, even the recommended
stable one". The search picks on the first 70% (60% for Stable) and the
backtest it returned was that slice's, while Run backtests the whole series:
the two numbers were never the same measure. And the Gabriele grid stepped by
5, so 32/68 by hand was outside it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.analysis.optimize import _GRID_GABRIELE, grid_size
from app.models import User

N = 400
_DATES = pd.date_range("2023-01-01", periods=N, freq="D", tz="UTC")
_RNG = np.random.default_rng(11)
_CLOSE = 100 + np.cumsum(_RNG.normal(0, 2, N)) + 10 * np.sin(np.arange(N) / 7)
_CANDLES = pd.DataFrame(
    {"open": _CLOSE, "high": _CLOSE + 1.5, "low": _CLOSE - 1.5,
     "close": _CLOSE, "volume": np.full(N, 1000.0)},
    index=_DATES,
)
GAB = "Gabriele (RSI+BB reversal)"


class _Provider:
    async def fetch_ohlcv(self, symbol, interval, outputsize, since_ms=None):
        return _CANDLES


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_provider", lambda *a, **k: _Provider())
    user = User(id="u1", email="l@example.com", password_hash="x")
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


_BASE = {"symbol": "SUIUSDT", "asset_type": "crypto", "exchange": "mexc",
         "ltf_interval": "1d", "strategy_name": GAB}


def test_the_optimized_backtest_is_the_one_run_shows(client):
    opt = client.get("/api/optimize", params={**_BASE, "mode": "random"})
    assert opt.status_code == 200, opt.text
    body = opt.json()
    run = client.get("/api/backtest/deep", params={**_BASE, **body["params"]})
    assert run.status_code == 200, run.text
    assert body["backtest"]["total_return_pct"] == pytest.approx(run.json()["total_return_pct"])
    assert body["backtest"]["num_trades"] == run.json()["num_trades"]
    assert body["in_sample_return_pct"] is not None


def test_shortlist_figures_are_whole_history_too(client):
    body = client.get("/api/optimize", params={**_BASE, "mode": "random"}).json()
    for cand in body["top_candidates"][:3]:
        run = client.get("/api/backtest/deep", params={**_BASE, **cand["params"]}).json()
        assert cand["total_return_pct"] == pytest.approx(run["total_return_pct"])
        assert "in_sample_return_pct" in cand


def test_gabriele_grid_covers_every_whole_value():
    assert _GRID_GABRIELE["rsi_oversold"] == list(range(15, 51))
    assert _GRID_GABRIELE["rsi_overbought"] == list(range(50, 86))
    assert grid_size(GAB) == 36 * 36


def test_max_return_mode_matches_run_and_has_no_oos(client):
    body = client.get("/api/optimize", params={**_BASE, "mode": "max_return"}).json()
    assert body["mode"] == "max_return" and body["trials_evaluated"] == 31 * 31
    assert 10 <= body["params"]["rsi_oversold"] <= 40
    assert 60 <= body["params"]["rsi_overbought"] <= 90
    assert body["out_of_sample_return_pct"] is None
    assert abs(body["backtest"]["max_drawdown_pct"]) <= 60
    run = client.get("/api/backtest/deep", params={**_BASE, **body["params"]}).json()
    assert body["backtest"]["total_return_pct"] == pytest.approx(run["total_return_pct"])


def test_max_return_is_refused_for_other_strategies(client):
    resp = client.get("/api/optimize", params={**_BASE, "mode": "max_return",
                                                "strategy_name": "Lorenzo (trend-follower)"})
    assert resp.status_code == 400
