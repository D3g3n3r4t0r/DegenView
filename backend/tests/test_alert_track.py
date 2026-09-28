"""for_token: the token page's own view of the alerts on one token."""
import time

from app.trading.onchain import alert_track


def _alert(chain, token, kind="meme", at=None, symbol="TKN"):
    return {"kind": kind, "chain": chain, "token_address": token, "pair_address": f"pair-{token}",
            "pair_url": f"https://dexscreener.com/{chain}/{token}", "symbol": symbol, "name": symbol,
            "image": None, "at": at or time.time(), "cap0": 1000.0, "returns": {"1": 0.1},
            "max_ret": 0.2, "gone": False, "entry": {"price": 1.0}, "last": {"ret": 0.05}}


def test_for_token_only_matching_token():
    alert_track.reset_for_tests()
    now = time.time()
    alert_track._alerts["a"] = _alert("solana", "AAA", at=now - 100)
    alert_track._alerts["b"] = _alert("solana", "BBB", at=now - 50)
    alert_track._alerts["c"] = _alert("base", "AAA", at=now - 10)
    rows = alert_track.for_token("solana", "AAA", now=now)
    assert [r["token_address"] for r in rows] == ["AAA"]
    assert all(r["chain"] == "solana" for r in rows)


def test_for_token_newest_first_and_same_shape_as_board():
    alert_track.reset_for_tests()
    now = time.time()
    alert_track._alerts["a"] = _alert("solana", "AAA", at=now - 100)
    alert_track._alerts["b"] = _alert("solana", "AAA", at=now - 10)
    rows = alert_track.for_token("solana", "AAA", now=now)
    assert [r["at"] for r in rows] == [now - 10, now - 100]
    board = alert_track.board("meme", now=now)
    assert set(rows[0]) == set(board["items"][0])


def test_board_items_have_systems_list():
    alert_track.reset_for_tests()
    now = time.time()
    alert_track._alerts["a"] = _alert("solana", "AAA", at=now - 100)
    board = alert_track.board("meme", now=now)
    assert isinstance(board["items"][0]["systems"], list)


def test_board_items_have_backtests_key():
    alert_track.reset_for_tests()
    now = time.time()
    alert_track._alerts["a"] = _alert("solana", "AAA", at=now - 100)
    board = alert_track.board("meme", now=now)
    assert "backtests" in board["items"][0]


def test_backtest_status_counts():
    alert_track.reset_for_tests()
    now = time.time()
    a = _alert("solana", "AAA", at=now - 100)
    a["backtests"] = {"x": 1}
    a["system_v"] = alert_track.SYSTEM_VERSION
    alert_track._alerts["a"] = a
    b = _alert("solana", "BBB", at=now - 50)
    b["nodata"] = True
    alert_track._alerts["b"] = b
    alert_track._alerts["c"] = _alert("solana", "CCC", at=now - 10)
    st = alert_track.backtest_status("meme", now=now)
    assert st["total"] == 3
    assert st["ready"] == 1
    assert st["pending"] == 1
    assert st["no_data"] == 1
    assert st["oldest_pending_h"] == round(10 / 3600, 1)
    assert alert_track.system_board("meme")["backtests"] == st
def test_refresh_system_freezes_finished_alert(monkeypatch):
    """A finished alert with a result keeps it: no fetch, no recompute."""
    import asyncio

    from app.trading.onchain import system

    alert_track.reset_for_tests()
    now = time.time()
    a = _alert("solana", "AAA", at=now - system.WINDOW_S - 3600)
    a["backtests"] = {"rows": [{"ret": 1.32}], "bars": 500}
    a["system_v"] = alert_track.SYSTEM_VERSION - 1
    a["system_done"] = True
    a["bars_fetched"] = True
    alert_track._alerts["a"] = a

    async def _boom(*args, **kwargs):
        raise AssertionError("_candles must not be called for a frozen alert")

    monkeypatch.setattr(alert_track, "_candles", _boom)
    asyncio.run(alert_track.refresh_system(None, now=now))

    assert a["backtests"] == {"rows": [{"ret": 1.32}], "bars": 500}
    assert a["system_v"] == alert_track.SYSTEM_VERSION
    assert alert_track.backtest_status("meme", now=now)["ready"] == 1


def test_refresh_system_keeps_old_backtest_when_new_has_no_rows(monkeypatch):
    """A live alert's empty result does not overwrite the saved one."""
    import asyncio

    from app.trading.onchain import system

    alert_track.reset_for_tests()
    now = time.time()
    a = _alert("solana", "AAA", at=now - 600)
    a["backtests"] = {"rows": [{"ret": 0.5}], "bars": 100}
    a["system_v"] = alert_track.SYSTEM_VERSION
    a["system_done"] = True
    a["bars_fetched"] = True
    alert_track._alerts["a"] = a
    alert_track._bars["solana:AAA"] = [(now - 600 + i * 60, 1.0, 1.1, 0.9, 1.05, 100.0)
                                       for i in range(10)]

    async def _empty(*args, **kwargs):
        return []

    async def _evaluate(bars, at, gone=False, now=None):
        return {"rows": [], "bars": 0}

    monkeypatch.setattr(alert_track, "_candles", _empty)
    monkeypatch.setattr(system, "evaluate", _evaluate)
    asyncio.run(alert_track.refresh_system(None, now=now))

    assert a["backtests"] == {"rows": [{"ret": 0.5}], "bars": 100}
