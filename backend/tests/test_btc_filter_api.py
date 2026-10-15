"""BTC filter through the endpoints: Run and Max return (15/10)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.analysis import btc_regime
from app.models import User

N = 1100
_IDX = pd.date_range("2022-01-01", periods=N, freq="D", tz="UTC")
_R = np.random.default_rng(21)
_C = 100 + np.cumsum(_R.normal(0, 2, N)) + 12 * np.sin(np.arange(N) / 6)
DF = pd.DataFrame({"open": _C, "high": _C + 1.5, "low": _C - 1.5, "close": _C,
                   "volume": np.full(N, 1000.0)}, index=_IDX)
_BASE = {"symbol": "XUSDT", "asset_type": "crypto", "exchange": "mexc", "ltf_interval": "1d",
         "strategy_name": "Gabriele (RSI+BB reversal)"}


def _btc_down_in(year: int) -> pd.Series:
    """BTC rising, except a crash covering the whole of `year`."""
    idx = pd.date_range("2019-01-01", "2026-12-31", freq="D", tz="UTC")
    v = np.linspace(5_000, 50_000, len(idx))
    crash = (idx >= pd.Timestamp(f"{year - 1}-12-01", tz="UTC")) & (idx < pd.Timestamp(f"{year + 1}-01-01", tz="UTC"))
    v[crash] = np.linspace(v[crash][0] * 0.7, v[crash][0] * 0.2, crash.sum())   # falling all year
    return pd.Series(v, index=idx)


class _Provider:
    async def fetch_ohlcv(self, symbol, interval, outputsize, since_ms=None):
        return DF


@pytest.fixture
def client(monkeypatch):
    btc_regime.set_closes(_btc_down_in(2023), pin=True)
    monkeypatch.setattr(main, "get_provider", lambda *a, **k: _Provider())
    user = User(id="u1", email="l@example.com", password_hash="x")
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()
    btc_regime.clear()


def test_run_opens_no_long_while_btc_is_down(client):
    off = client.get("/api/backtest/deep", params=_BASE).json()
    on = client.get("/api/backtest/deep", params={**_BASE, "btc_filter": True}).json()
    in_2023 = [t for t in on["trades"] if pd.Timestamp(t["entry_time"], unit="s").year == 2023]
    assert not in_2023
    assert on["num_trades"] <= off["num_trades"]


def test_max_return_keeps_the_switch_and_does_not_judge_the_blocked_year(client):
    body = client.get("/api/optimize", params={**_BASE, "mode": "max_return", "btc_filter": True})
    assert body.status_code == 200, body.text
    body = body.json()
    assert body["params"]["btc_filter"] is True
    assert all(c["params"]["btc_filter"] is True for c in body["top_candidates"])
    run = client.get("/api/backtest/deep", params={**_BASE, **body["params"]}).json()
    assert body["backtest"]["total_return_pct"] == pytest.approx(run["total_return_pct"])
