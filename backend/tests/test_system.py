"""The trend-following system followed on every alert (system.py)."""
import asyncio

from app.trading.onchain import alert_track as at
from app.trading.onchain import system

T0 = 1_790_000_000
B = system.BAR_S


def _bars(prices, t0=T0 - 40 * B):
    return [[t0 + i * B, p, p * 1.01, p * 0.99, p, 1000.0] for i, p in enumerate(prices)]


def _signals(entries, exits):
    import pandas as pd

    def fake(df, cfg):
        n = len(df)
        return pd.DataFrame({"entry_long": [i in entries for i in range(n)], "exit_long": [i in exits for i in range(n)],
                             "entry_short": False, "exit_short": False}, index=df.index)
    return fake


def test_follow_trades_only_after_the_alert_with_costs(monkeypatch):
    prices = [1.0] * 40 + [1.0, 1.0, 2.0, 2.0, 3.0, 3.0]
    # a trade opened and closed before the alert (bars 10-20) does not count;
    # then entry at bar 41, exit at bar 43
    monkeypatch.setattr(system.radar, "spot_signals", _signals({10, 41}, {20, 43}))
    r = system.follow(_bars(prices), system.CANDIDATES[0], T0, now=T0 + 6 * B)
    assert r["trades"] == 1 and r["state"] == "out"
    # entry at open of bar 42 (2.0), exit at open of bar 44 (3.0), costs both ways
    assert abs(r["ret"] - (1.5 * (1 - system.COST) ** 2 - 1)) < 1e-4
    assert r["events"][0]["t"] == T0 + 2 * B


def test_rug_while_in_position_is_minus_100(monkeypatch):
    monkeypatch.setattr(system.radar, "spot_signals", _signals({41}, set()))
    r = system.follow(_bars([1.0] * 45), system.CANDIDATES[0], T0, gone=True, now=T0 + 5 * B)
    assert r["ret"] == -1.0 and r["done"]


def test_open_position_is_closed_at_the_end_of_the_window(monkeypatch):
    prices = [1.0] * 40 + [1.0] * 600
    prices[-1] = 1.2
    monkeypatch.setattr(system.radar, "spot_signals", _signals({40}, set()))
    bars = _bars(prices)
    r = system.follow(bars, system.CANDIDATES[0], T0, now=T0 + system.WINDOW_S + 3600)
    assert r["done"] and r["state"] == "out" and r["events"][-1].get("why") == "48h"


def test_scoreboard_picks_the_best_median_only_with_enough_alerts():
    def res(a, b):
        return {"Trend HF": {"ret": a, "done": True, "trades": 1}, "Trend EMA": {"ret": b, "done": True, "trades": 1}}
    few = system.scoreboard([res(-0.1, 0.5)] * 3)
    assert few["chosen"] == system.DEFAULT
    many = system.scoreboard([res(-0.1, 0.5)] * system.MIN_DECIDED)
    assert many["chosen"] == "Trend EMA"
    assert {c["label"] for c in many["candidates"]} == {"Trend EMA", "Trend HF"}


def test_bars_from_readings_and_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    k = at.key_of(a)
    at.add_bar(k, T0 + 10, 1.0, 5)
    at.add_bar(k, T0 + 70, 1.4, 7)
    at.add_bar(k, T0 + B + 5, 1.2)
    assert at._bars[k][0][1:5] == [1.0, 1.4, 1.0, 1.4] and at._bars[k][0][5] == 7 and len(at._bars[k]) == 2

    async def fake_candles(*args, **kw):
        return [[T0 - B, 1, 1, 1, 1, 1]]
    monkeypatch.setattr(at, "_candles", fake_candles)
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    assert asyncio.run(at.refresh_system(None, now=T0 + 2 * B, gap_s=0)) == 1
    assert a["bars_fetched"] and "Trend HF" in a["system"]
    b = at.board("meme", now=T0 + 2 * B)
    assert b["system"]["chosen"] == system.DEFAULT and "live" in b["system"]
    at.reset_for_tests()


def test_an_old_version_result_is_rebuilt_even_when_the_bars_do_not_move(monkeypatch, tmp_path):
    """Lorenzo, 28/09: "Backtests ready: 5/13 [...] io voglio vedere tutti i
    risultati". A closed alert inside its 48h gets no new bars: its result from
    an older SYSTEM_VERSION must still be rebuilt, not wait out the window."""
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    k = at.key_of(a)
    at.merge_bars(k, _bars([1.0] * 50))
    bars = at._bars[k]
    a.update(closed=True, bars_fetched=True, backtests={"rows": []}, system_v=at.SYSTEM_VERSION - 1,
             system_sig=f"{len(bars)}:{bars[-1][0]}:{a['gone']}")
    assert at.backtest_status("meme", now=T0 + 3600)["pending"] == 1
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    assert asyncio.run(at.refresh_system(None, now=T0 + 3600, gap_s=0)) == 1
    assert a["system_v"] == at.SYSTEM_VERSION
    assert at.backtest_status("meme", now=T0 + 3600)["pending"] == 0
    at.reset_for_tests()


def test_a_sell_after_a_one_candle_crash_says_so(monkeypatch):
    # entry at bar 41, the price crashes 80% inside bar 44, the exit fills at bar 45's open
    prices = [1.0] * 44 + [0.2, 0.2, 0.2]
    monkeypatch.setattr(system.radar, "spot_signals", _signals({40}, {44}))
    r = system.follow(_bars(prices), system.CANDIDATES[0], T0, now=T0 + 8 * B)
    sell = [e for e in r["events"] if e["side"] == "sell"][0]
    assert sell["why"] == "crash" and sell["drop"] <= system.CRASH and r["ret"] < -0.75


def test_a_sell_on_a_normal_turn_is_a_signal(monkeypatch):
    prices = [1.0] * 44 + [0.95, 0.94, 0.93]
    monkeypatch.setattr(system.radar, "spot_signals", _signals({40}, {44}))
    r = system.follow(_bars(prices), system.CANDIDATES[0], T0, now=T0 + 8 * B)
    assert [e for e in r["events"] if e["side"] == "sell"][0]["why"] == "signal"
