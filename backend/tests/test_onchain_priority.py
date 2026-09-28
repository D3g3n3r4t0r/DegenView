"""The Strategies backtests come first: other background jobs wait."""
import asyncio
import time

import pytest

from app.trading.onchain import alert_track, backtest_lab, priority, strategy_lab


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(alert_track, "_STORE_FILE", tmp_path / "alerts.json")
    monkeypatch.setattr(alert_track, "_BARS_FILE", tmp_path / "bars.json")
    alert_track.reset_for_tests()
    priority.reset_for_tests()
    yield
    alert_track.reset_for_tests()
    priority.reset_for_tests()


def _alert(now: float) -> None:
    alert_track.record({"chain": "solana", "symbol": "TEST", "token_address": "tok", "pair_address": "pair"},
                       "meme", now)


def test_backtests_first_none_without_alerts():
    assert priority.backtests_first() is None


def test_backtests_first_dict_while_pending():
    _alert(time.time())
    st = priority.backtests_first()
    assert isinstance(st, dict)
    assert st["pending"] > 0


def test_strategy_lab_tick_waits(monkeypatch):
    _alert(time.time())
    calls = []

    async def fake_run_one(client, entry, now):
        calls.append(entry)
        return {"ok": True}

    monkeypatch.setattr(strategy_lab, "run_one", fake_run_one)
    out = asyncio.run(strategy_lab.tick([{"chain": "solana", "token_address": "tok", "symbol": "TEST"}]))
    assert out is None
    assert calls == []


def test_backtest_lab_fill_waits():
    _alert(time.time())
    assert asyncio.run(backtest_lab.fill()) == 0


def test_a_stuck_queue_does_not_block_forever():
    now = time.time()
    _alert(now)
    assert priority.backtests_first(now) is not None
    assert priority.backtests_first(now + priority.STUCK_S + 1) is None
