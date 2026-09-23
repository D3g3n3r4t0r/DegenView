"""Il radar: token giovani su Solana e Robinhood provati su tutte le
strategie. Lorenzo: "c'e' questo ticker su Solana o su rete Robinhood che
performerebbe bene con questo tipo di strategia"."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import archive, auth, main, watchlist as watchlist_store
from app.analysis.strategies import STRATEGY_REGISTRY
from app.models import StrategySignal
from app.trading.onchain import radar


def _pool(symbol="NEW", *, liq=100_000, mcap=500_000, age_days=5, token="Tok", pair="Pair"):
    return radar.Pool(
        chain="solana", symbol=symbol, name=f"{symbol} / SOL", token_address=token, pair_address=pair,
        dex="raydium", liquidity_usd=liq, market_cap=mcap,
        created_ms=int((time.time() - age_days * 86400) * 1000),
    )


def test_filter_keeps_young_liquid_low_cap_tokens_only():
    picked, passing = radar.pick_candidates([
        _pool("OK"),
        _pool("OLD", age_days=30, token="t2"),
        _pool("THIN", liq=5_000, token="t3"),
        _pool("BIG", mcap=90_000_000, token="t4"),
        _pool("SHALLOW", liq=35_000, mcap=5_000_000, token="t5"),  # 0.7% della cap
        _pool("SOL", token="t6"),
        _pool("NOCAP", mcap=None, token="t7"),
    ])
    assert [p.symbol for p in picked] == ["OK"]
    assert passing == 1


def test_one_pool_per_ticker_the_most_liquid():
    picked, _ = radar.pick_candidates([
        _pool("CAT", liq=40_000, token="copy", pair="p1"),
        _pool("cat", liq=150_000, token="real", pair="p2"),
    ])
    assert len(picked) == 1 and picked[0].token_address == "real"


def test_gecko_pool_keeps_address_case():
    pool = radar.parse_pool("solana", {
        "attributes": {"address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", "name": "WIF / SOL",
                       "pool_created_at": "2026-09-20T10:00:00Z", "reserve_in_usd": "120000",
                       "market_cap_usd": None, "fdv_usd": "900000"},
        "relationships": {"base_token": {"data": {"id": "solana_EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"}},
                          "dex": {"data": {"id": "raydium"}}},
    })
    assert pool.pair_address == "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
    assert pool.token_address == "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
    assert pool.symbol == "WIF" and pool.market_cap == 900_000


def test_interval_needs_finer_candles_for_newborns():
    assert radar.interval_for(30) == "5m"
    assert radar.interval_for(10 * 24) == "15m"


def test_every_registry_strategy_plus_each_ready_archive_config():
    entries = [
        {"strategy_name": "Lorenzo (trend-follower)", "params": {"len": 50}, "symbol": "BTCUSDT", "interval": "1d"},
        {"strategy_name": "Lorenzo (trend-follower)", "params": {"len": 50}, "symbol": "ETHUSDT", "interval": "1d"},
        {"strategy_name": "Sconosciuta", "params": {"x": 1}},
        {"strategy_name": "Gabriele (RSI+BB reversal)", "params": {}},
    ]
    configs = radar.strategy_configs(entries)
    assert [c["strategy_name"] for c in configs[: len(STRATEGY_REGISTRY)]] == list(STRATEGY_REGISTRY)
    archived = configs[len(STRATEGY_REGISTRY):]
    assert len(archived) == 1 and archived[0]["params"] == {"len": 50} and archived[0]["source"] == "archivio"


def test_ready_entries_skips_unfinished_snapshots(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(archive, "_entries", [{"state": "pronto"}, {"state": "in corso"}])
    assert archive.ready_entries() == [{"state": "pronto"}]


def _sig(t, kind):
    return StrategySignal(time=t, type=kind, price=1.0, label="")


def test_chart_draws_long_side_only():
    events = [_sig(1, "entry_short"), _sig(2, "flip_to_long"), _sig(3, "entry_long"),
              _sig(4, "flip_to_short"), _sig(5, "exit_short"), _sig(6, "entry_long"), _sig(7, "exit_long")]
    assert [(e["time"], e["kind"]) for e in radar.long_events(events)] == [
        (2, "in"), (4, "out"), (6, "in"), (7, "out")]


def _series(n=600):
    rng = np.random.default_rng(3)
    close = 1 + 0.4 * np.sin(np.linspace(0, 18, n)) + np.cumsum(rng.normal(0, 0.004, n)) + np.linspace(0, 1, n)
    close = np.maximum(close, 0.05)
    idx = pd.date_range("2026-09-10", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": 1000.0}, index=idx)


def test_evaluate_tries_all_and_never_proposes_the_lookahead_strategy():
    df = _series()
    out = radar.evaluate(df, radar.strategy_configs([]))
    assert {r["strategy_name"] for r in out["tried"]} <= set(STRATEGY_REGISTRY)
    assert out["hold_pct"] == pytest.approx((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100)
    if out["best"]:
        assert out["best"]["strategy_name"] not in radar.UNRELIABLE
        assert out["best"]["trades"] >= radar.MIN_TRADES and out["best"]["return_pct"] > 0


class _T:
    def __init__(self, direction, pnl_pct):
        self.direction, self.pnl_pct = direction, pnl_pct


def test_long_only_metrics_ignore_shorts_and_pay_dex_costs():
    m = radar._long_only([_T("long", 10.0), _T("short", 50.0), _T("long", -5.0)], commission_pct=0.3)
    assert m["trades"] == 2
    assert m["return_pct"] == pytest.approx(((1.094) * (1 - 0.056) - 1) * 100)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(watchlist_store, "_STORE_FILE", tmp_path / "watchlist.json")
    monkeypatch.setattr(radar, "_STORE_FILE", tmp_path / "radar.json")
    auth._users.clear()
    watchlist_store._entries.clear()
    radar.reset_for_tests()
    user = auth.create_user("trader@example.com", "correct-horse-battery-9")
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.get_user(user.id)
    with TestClient(main.app) as c:
        c.owner_id = user.id
        yield c
    main.app.dependency_overrides.clear()
    watchlist_store._entries.clear()


def test_radar_endpoint_before_first_scan(client):
    body = client.get("/api/onchain/radar").json()
    assert body["proposals"] == [] and body["last_scan"] == 0
    assert body["filters"]["age_max_days"] == radar.AGE_MAX_DAYS


def test_chart_returns_candles_and_long_events_per_strategy(client, monkeypatch):
    async def fake_ohlcv(self, symbol, interval, outputsize, since_ms=None):
        assert symbol == "NEW@solana:PoolAddr" and interval == "15m"
        return _series()
    monkeypatch.setattr(radar.DexScreenerProvider, "fetch_ohlcv", fake_ohlcv)
    radar._chart_cache.clear()
    body = client.get("/api/onchain/radar/chart",
                      params={"chain": "solana", "pool": "PoolAddr", "symbol": "NEW", "interval": "15m"}).json()
    assert len(body["candles"]) == 600 and body["active"] == []
    assert {s["strategy_name"] for s in body["strategies"]} == set(STRATEGY_REGISTRY)
    for s in body["strategies"]:
        assert all(e["kind"] in ("in", "out") for e in s["events"])


def test_follow_turns_on_an_alert_never_auto_trade(client):
    req = {"chain": "solana", "pool": "PoolAddr", "symbol": "NEW", "token_address": "TokAddr",
           "interval": "15m", "strategy_name": "Gabriele (RSI+BB reversal)", "params": {"rsi_length": 10},
           "enabled": True}
    assert client.post("/api/onchain/radar/follow", json=req).json()["active"] == ["Gabriele (RSI+BB reversal)"]
    entry = watchlist_store.list_entries(client.owner_id)[0]
    assert entry.symbol == "NEW@solana:PoolAddr" and entry.interval == "15m"
    assert entry.base_token_address == "TokAddr"
    assert entry.strategy_params["Gabriele (RSI+BB reversal)"] == {"rsi_length": 10}
    assert not any(entry.auto_trade.values())
    off = client.post("/api/onchain/radar/follow", json={**req, "enabled": False}).json()
    assert off["active"] == []


def test_follow_rejects_unknown_strategy(client):
    r = client.post("/api/onchain/radar/follow", json={
        "chain": "solana", "pool": "P", "symbol": "X", "token_address": "T", "interval": "5m",
        "strategy_name": "Inventata", "enabled": True})
    assert r.status_code == 400
