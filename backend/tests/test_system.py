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


def test_a_rebuild_on_fewer_bars_keeps_the_saved_backtest(monkeypatch, tmp_path):
    """Lorenzo, 28/09: FLOOR +132% "dopo qualche secondo e' sparito [...] non
    deve cambiare ogni volta risultato e perdere i precedenti"."""
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    saved = {"bars": 600, "rows": [{"label": "Trend EMA", "trades": 1, "return_pct": 132.0}]}
    a.update(backtests=saved, system_v=at.SYSTEM_VERSION - 1, system_done=True, bars_fetched=True)

    async def dead_pool(*args, **kw):
        return []                        # the pool is gone: no candles any more
    monkeypatch.setattr(at, "_candles", dead_pool)
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    now = T0 + system.WINDOW_S + 7200
    asyncio.run(at.refresh_system(None, now=now, gap_s=0))
    assert a["system_v"] == at.SYSTEM_VERSION
    assert a["backtests"]["rows"][0]["return_pct"] == 132.0 and a["backtests"]["bars"] == 600
    assert at.keep_richer(saved, {"bars": 700, "rows": []})["bars"] == 700
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


def test_save_and_load_round_trip_leaves_no_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    k = at.key_of(a)
    at.merge_bars(k, _bars([1.0] * 50))
    at.save()
    at.save_bars(now=T0, force=True)
    at.reset_for_tests()
    at._load()
    assert k in at._alerts and at._alerts[k]["symbol"] == "X"
    assert len(at._bars[k]) == 50
    assert not (tmp_path / "a.json.tmp").exists()
    assert not (tmp_path / "b.json.tmp").exists()
    at.reset_for_tests()


def test_missing_bars_are_fetched_again(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    a.update(bars_fetched=True, system_done=False)
    calls = []

    async def fake_candles(*args, **kw):
        calls.append(args)
        return _bars([1.0] * 50)
    monkeypatch.setattr(at, "_candles", fake_candles)
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    asyncio.run(at.refresh_system(None, now=T0 + 2 * B, gap_s=0))
    assert calls and a["bars_fetched"] and at._bars.get(at.key_of(a))
    at.reset_for_tests()


def test_a_dead_pool_is_refetched_only_once(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    a.update(bars_fetched=True, system_done=False)
    calls = []

    async def dead_pool(*args, **kw):
        calls.append(args)
        return []
    monkeypatch.setattr(at, "_candles", dead_pool)
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    for i in range(3):
        asyncio.run(at.refresh_system(None, now=T0 + (2 + i) * B, gap_s=0))
    assert len(calls) == 1
    at.reset_for_tests()


def test_a_real_backtest_survives_a_save_and_a_restart(monkeypatch, tmp_path):
    """28/09: system.follow counted wins as numpy int64, json.dumps raised and
    nothing reached the disk: every restart lost the backtests (FLOOR, CERT)."""
    import json
    import math
    import random
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    rnd = random.Random(1)
    p, prices = 1.0, []
    for i in range(600):
        p *= math.exp(rnd.gauss(0.002 if i < 300 else -0.002, 0.03))
        prices.append(p)
    bars = _bars(prices, t0=T0 - 100 * B)
    res = system.evaluate(bars, T0, gone=False, now=T0 + 500 * B)
    assert any(r["trades"] for r in res.values())
    json.dumps(res)                      # plain Python numbers only
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)
    a.update(system=res, backtests=system.backtest_all(bars, None), system_v=at.SYSTEM_VERSION)
    a["system"]["Trend EMA"]["odd"] = __import__("numpy").int64(3)   # any other stray numpy value
    at.save()
    at.reset_for_tests()
    at._load()
    b = at._alerts[at.key_of(a)]
    assert b["backtests"]["rows"] and b["system"]["Trend EMA"]["odd"] == 3
    at.reset_for_tests()


def test_on_alert_the_alert_is_the_entry(monkeypatch):
    """Lorenzo, 28/09: every alerted token shows a backtest, never "no entry":
    with no entry signal at all, the trend follower still buys at the alert
    and sells on its own exit."""
    prices = [1.0] * 40 + [1.0, 1.2, 1.5, 1.4, 1.3, 1.3]
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), {43}))
    plain = system.follow(_bars(prices), system.CANDIDATES[0], T0, now=T0 + 6 * B)
    assert plain["trades"] == 0 and plain["state"] == "waiting"
    r = system.follow(_bars(prices), system.CANDIDATES[0], T0, now=T0 + 6 * B, on_alert=True)
    assert r["events"][0]["why"] == "alert" and r["events"][0]["t"] == T0
    assert r["trades"] == 1 and r["wins"] == 1 and r["state"] == "out"
    # exit signal on bar 43, filled at the open of bar 44 (1.3)
    assert abs(r["ret"] - (1.3 * (1 - system.COST) ** 2 - 1)) < 1e-4
    # after the close, no re-entry: one trade per alert
    monkeypatch.setattr(system.radar, "spot_signals", _signals({44}, {43}))
    again = system.follow(_bars(prices), system.CANDIDATES[0], T0, now=T0 + 6 * B, on_alert=True)
    assert again["trades"] == 1 and again["state"] == "out"


def test_every_alert_gets_an_on_alert_result(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    at.reset_for_tests()
    a = at.record({"chain": "robinhood", "pair_address": "P", "token_address": "T", "symbol": "X"}, "meme", T0)

    async def fake_candles(*args, **kw):
        return _bars([1.0] * 40 + [1.0, 1.1, 1.2, 1.3])
    monkeypatch.setattr(at, "_candles", fake_candles)
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    asyncio.run(at.refresh_system(None, now=T0 + 4 * B, gap_s=0))
    item = at.board("meme", now=T0 + 4 * B)["items"][0] if a["entry"] is not None else at._item(a, T0 + 4 * B, "Trend EMA")
    assert item["on_alert"] and item["on_alert"]["state"] == "in" and item["on_alert"]["ret"] > 0
    assert [e["side"] for e in item["on_alert"]["events"]] == ["buy"]      # one entry, at the alert
    at.reset_for_tests()


def test_on_alert_exits_when_the_trend_is_already_down(monkeypatch):
    """Lorenzo, 28/09 (MESUB -95%): bought on the alert with the trend already
    down, the strategy's cross had already fired and no exit ever came.
    Now the trade closes on the first bar with the trend down."""
    prices = [2.0 - 0.02 * i for i in range(40)] + [1.2 * 0.9 ** i for i in range(20)]
    monkeypatch.setattr(system.radar, "spot_signals", _signals(set(), set()))
    for c in system.CANDIDATES:
        r = system.follow(_bars(prices), c, T0, now=T0 + 20 * B, on_alert=True)
        assert r["trades"] == 1 and r["state"] == "out"
        sell = r["events"][-1]
        assert sell["side"] == "sell" and sell["t"] == T0 + B      # one bar after the alert
        assert r["ret"] > -0.15
