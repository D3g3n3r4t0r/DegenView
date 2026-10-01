"""Prova giornaliera della scala dei time frame (ladder_watch.py)."""
from __future__ import annotations

import asyncio

import pytest

from app.trading.onchain import candle_archive, ladder_watch as lw, strategy_lab

MID = 1_799_971_200                      # 00:00 UTC
NOW = MID + 7 * 3600


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "_FILE", tmp_path / "ladder.json")
    monkeypatch.setattr(candle_archive, "_DB_FILE", tmp_path / "candles.sqlite")
    strategy_lab.reset_for_tests()
    yield
    strategy_lab.reset_for_tests()


def test_two_outliers_do_not_make_the_ladder_better():
    pairs = [(0, 2428), (0, 1740), (0, 169)] + [(0, -20)] * 10 + [(0, 0)] * 30
    v = lw.verdict(pairs)
    assert v["book_new"] > v["book_old"] and not v["better"]


def test_a_broad_improvement_is_better():
    v = lw.verdict([(-10, 5)] * 8 + [(0, 0)] * 10 + [(5, 3)] * 2)
    assert v["better"] and v["up"] == 8 and v["down"] == 2


def _seed(now):
    strategy_lab._results["solana:T"] = {"at": 1, "pair": "P", "symbol": "TOK",
                                         "backtests": {"rows": [{"label": "RSI+BB", "return_pct": 1.0, "trades": 1}]},
                                         "daily": {"interval": "1d", "rows": [{"label": "Trend EMA"}]}}
    k = candle_archive.key("solana", "P", "day", 1, "T")
    candle_archive.put(k, [[now - (200 - i) * 86400, 1, 1, 1, 1, 1] for i in range(200)], now)


def test_once_a_day_from_the_archive_only_and_telegram_only_when_better(monkeypatch):
    _seed(NOW)

    async def no_network(*a, **k):
        raise AssertionError("GeckoTerminal called")
    monkeypatch.setattr(candle_archive.alert_track, "_candles", no_network)

    def fake(bars, name="Lorenzo (trend-follower)", label="Trend EMA", known=None):
        hit = bars[1][0] - bars[0][0] == 43200       # only the 12h chart enters
        return {"bars": len(bars), "rows": [{"label": label, "trades": int(hit), "return_pct": 30.0 if hit else 0.0}]}
    monkeypatch.setattr(strategy_lab.system, "backtest_one", fake)
    sent = []

    async def send(text):
        sent.append(text)
        return True
    from app.notify import telegram
    monkeypatch.setattr(telegram, "send_message", send)

    res = asyncio.run(lw.tick(now=NOW))
    assert res["trend"]["tokens"] == 1 and not res["trend"]["better"]     # no 12h candles archived
    assert sent == [] and asyncio.run(lw.tick(now=NOW + 3600)) is None

    k12 = candle_archive.key("solana", "P", "hour", 12, "T")
    candle_archive.put(k12, [[NOW - (100 - i) * 43200, 1, 1, 1, 1, 1] for i in range(100)], NOW)
    res = asyncio.run(lw.tick(now=NOW + 86400))
    assert res["trend"]["better"] and len(sent) == 1 and "trend follower" in sent[0]


def test_not_before_eight_in_italy():
    assert not lw.due(MID + 5 * 3600, [])
    assert lw.due(MID + 6 * 3600, [])
