"""On a DEX token the main-site chart shows only long entries and exits.

Lorenzo, 28/09: "Il grafico nel sito principale e' fatto apposta per fare
ingressi e uscite sia long che short. Tu di quello devi solo prendere
l'apertura del long e la chiusura del long." A short signal there is the
sale of what you hold (strategies.spot_only), as in the alert watcher.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.models import User
from app.trading.onchain import system


def _bars():
    rng = np.random.default_rng(3)
    p, t, out = 1.0, 1_700_000_000, []
    for i in range(300):
        p *= np.exp((0.012 if 80 < i < 180 else -0.004) + rng.normal(0, 0.006))
        out.append([t + i * 300, p, p * 1.01, p * 0.99, p * (1 + rng.normal(0, 0.003)), 1000])
    return system.frame(out)


@pytest.fixture
def client(monkeypatch):
    async def fake(provider, symbol, interval, outputsize, since_ms=None):
        return _bars()
    monkeypatch.setattr(main, "fetch_ohlcv_canonical", fake)
    main.app.dependency_overrides[auth.get_current_user] = lambda: User(id="t", email="t@example.com", password_hash="x")
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def _get(client, asset_type):
    resp = client.get("/api/analyze", params={"symbol": "X@solana:POOL1" if asset_type == "dex" else "XUSDT",
                                              "asset_type": asset_type, "interval": "5m",
                                              "strategy_name": "Lorenzo (trend-follower)"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_dex_chart_has_no_shorts(client):
    d = _get(client, "dex")
    types = {s["type"] for s in d["strategies"]["ltf"][0]["signals"]}
    assert types and not any("short" in t for t in types)
    assert {t["direction"] for t in d["backtests"]["ltf"]["trades"]} <= {"long"}


def test_other_markets_keep_their_shorts(client):
    d = _get(client, "crypto")
    assert any("short" in s["type"] for s in d["strategies"]["ltf"][0]["signals"])
