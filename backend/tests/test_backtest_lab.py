"""Il laboratorio di backtest: prende i token maturi del diario, li analizza
nei momenti morti e li conserva."""
import asyncio
import time

from app.providers import dexscreener
from app.trading.onchain import alert_track, backtest_lab, outcomes


def _bars(start: float, n: int = 300) -> list:
    """Barre 5m con un pump e poi una caduta, volume variabile."""
    out = []
    price = 1.0
    for i in range(n):
        ts = start + i * 300
        if i < 60:
            price *= 1.03
        else:
            price *= 0.985
        o = price * 0.995
        h = price * 1.01
        low = price * 0.99
        c = price
        vol = 1000 + (i % 7) * 250
        out.append([ts, o, h, low, c, vol])
    return out


def _journal(now: float) -> dict:
    return {
        "solana:mature": {
            "chain": "solana", "symbol": "PUMP", "token_address": "tok1",
            "pair_address": "pair1", "decision": "proposed", "source": "alert",
            "at": now - 3 * 86400,
        },
        "solana:fresh": {
            "chain": "solana", "symbol": "NEW", "token_address": "tok2",
            "pair_address": "pair2", "decision": "proposed", "source": "alert",
            "at": now - 3600,
        },
    }


def _setup(monkeypatch, tmp_path, now: float):
    monkeypatch.setattr(backtest_lab, "_DB_FILE", tmp_path / "lab.sqlite")
    monkeypatch.setattr(backtest_lab, "_conn", None)
    monkeypatch.setattr(backtest_lab, "_conn_path", None)
    monkeypatch.setattr(outcomes, "_journal", _journal(now))
    monkeypatch.setattr(dexscreener, "gecko_load", lambda: 0)


def test_fill_stores_mature_token(monkeypatch, tmp_path):
    now = time.time()
    _setup(monkeypatch, tmp_path, now)
    entry = outcomes._journal["solana:mature"]

    async def fake_candles(client, net, pool, tf, aggregate, before, limit, token=""):
        return _bars(entry["at"])

    monkeypatch.setattr(alert_track, "_candles", fake_candles)

    stored = asyncio.run(backtest_lab.fill(now))
    assert stored == 1

    row = backtest_lab.get("solana:mature")
    assert row is not None
    assert row["result"]["backtests"]["rows"]
    assert len(row["result"]["backtests"]["rows"]) == 4
    assert row["result"]["path"]["max_mult"] > 1

    assert asyncio.run(backtest_lab.fill(now)) == 0


def test_fill_skips_when_gecko_busy(monkeypatch, tmp_path):
    now = time.time()
    _setup(monkeypatch, tmp_path, now)
    monkeypatch.setattr(dexscreener, "gecko_load", lambda: 99)
    assert asyncio.run(backtest_lab.fill(now)) == 0


def test_fill_marks_gone_pool(monkeypatch, tmp_path):
    now = time.time()
    _setup(monkeypatch, tmp_path, now)

    async def fake_candles(client, net, pool, tf, aggregate, before, limit, token=""):
        return []

    monkeypatch.setattr(alert_track, "_candles", fake_candles)
    assert asyncio.run(backtest_lab.fill(now)) == 1
    row = backtest_lab.get("solana:mature")
    assert row["result"] == {"gone": True}


def test_summary_counts_rows(monkeypatch, tmp_path):
    now = time.time()
    _setup(monkeypatch, tmp_path, now)
    entry = outcomes._journal["solana:mature"]

    async def fake_candles(client, net, pool, tf, aggregate, before, limit, token=""):
        return _bars(entry["at"])

    monkeypatch.setattr(alert_track, "_candles", fake_candles)
    asyncio.run(backtest_lab.fill(now))
    s = backtest_lab.summary()
    assert s["rows"] == 1
    assert "proposed" in s["by_decision"]

def test_done_count_empty_and_after_write(monkeypatch, tmp_path):
    now = time.time()
    _setup(monkeypatch, tmp_path, now)
    assert backtest_lab.done_count() == 0

    entry = outcomes._journal["solana:mature"]

    async def fake_candles(client, net, pool, tf, aggregate, before, limit, token=""):
        return _bars(entry["at"])

    monkeypatch.setattr(alert_track, "_candles", fake_candles)
    asyncio.run(backtest_lab.fill(now))
    assert backtest_lab.done_count() == 1
