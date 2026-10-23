import asyncio
import time

import pytest

from app.trading.onchain import copytrade as ct
from app.trading.onchain import wallet_pnl as wp

NOW = 1_800_000_000
A, B, C = "mintA", "mintB", "mintC"


def sw(t_ago_h, side, mint, units, usd):
    return {"t": NOW - t_ago_h * 3600, "side": side, "mint": mint, "units": units, "usd": usd, "decimals": 6}


def test_a_trade_ends_only_when_all_is_sold():
    swaps = [sw(100, "buy", A, 100, 100), sw(90, "buy", A, 100, 300),     # put in 400
             sw(10, "sell", A, 50, 150),                                    # partial: still open
             sw(5, "sell", A, 149.5, 150),                                  # 0.5 left = dust: closed
             sw(3, "sell", B, 10, 40)]                                      # never bought: no cost
    trades, still, orphan = wp.round_trips(swaps)
    assert len(trades) == 1 and trades[0]["pnl"] == -100 and trades[0]["buys"] == 2 and trades[0]["sells"] == 2
    assert still == [] and len(orphan) == 1 and orphan[0]["mint"] == B


def test_open_positions_and_partial_sells_stay_out():
    swaps = [sw(20, "buy", A, 100, 100), sw(10, "sell", A, 60, 300),      # sold 60%, still open
             sw(8, "buy", B, 10, 50), sw(2, "sell", B, 10, 80)]            # closed +30
    trades, still, orphan = wp.round_trips(swaps)
    day = wp.window(trades, still, orphan, NOW - wp.DAY)
    assert day["trades"] == 1 and day["pnl_usd"] == 30 and day["roi_pct"] == 60
    assert day["excluded_open"] == 1 and still[0]["mint"] == A and still[0]["share_left"] == pytest.approx(0.4)


def test_sell_more_than_known_closes_and_splits_the_orphan_part():
    trades, still, orphan = wp.round_trips([sw(5, "buy", A, 10, 10), sw(2, "sell", A, 30, 60)])
    assert trades[0]["returned"] == pytest.approx(20) and trades[0]["pnl"] == pytest.approx(10)
    assert orphan[0]["units"] == pytest.approx(20) and orphan[0]["usd"] == pytest.approx(40)


def test_windows_count_trades_opened_and_closed_inside():
    swaps = [sw(24 * 20, "buy", A, 100, 100), sw(24 * 3, "sell", A, 100, 300),   # +200, opened 20 days ago
             sw(10, "buy", B, 10, 50), sw(2, "sell", B, 10, 25),                 # -25, today
             sw(30, "buy", C, 5, 20), sw(20, "sell", C, 5, 60),                  # +40, yesterday
             sw(1, "buy", A, 5, 20)]                                             # still open
    trades, still, orphan = wp.round_trips(swaps)
    day = wp.window(trades, still, orphan, NOW - wp.DAY)
    week = wp.window(trades, still, orphan, NOW - 7 * wp.DAY)
    month = wp.window(trades, still, orphan, NOW - 30 * wp.DAY)
    assert day["trades"] == 1 and day["pnl_usd"] == -25 and day["win_rate_pct"] == 0
    assert week["trades"] == 2 and week["pnl_usd"] == 15 and week["excluded_opened_before"] == 1
    assert month["trades"] == 3 and month["pnl_usd"] == 215 and month["roi_pct"] == pytest.approx(126.5)
    assert month["best"]["mint"] == A and month["worst"]["mint"] == B
    assert month["avg_win_usd"] == 120 and month["avg_loss_usd"] == -25
    assert day["excluded_open"] == 1 and month["median_hold_s"] == 10 * 3600


def test_price_at_uses_the_trade_hour():
    hours, closes = [0, 3600, 7200], [100.0, 110.0, 120.0]
    assert wp.price_at(hours, closes, 3700, 999) == 110.0
    assert wp.price_at(hours, closes, 10, 999) == 100.0
    assert wp.price_at([], [], 10, 999) == 999


def test_analyze_end_to_end(monkeypatch):
    leader = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    now = int(time.time())

    def tx(sol, pre, post, t):
        return {"blockTime": t, "transaction": {"message": {"accountKeys": [{"pubkey": leader}]}},
                "meta": {"err": None, "fee": 0, "preBalances": [10**12], "postBalances": [10**12 + int(sol * 1e9)],
                         "preTokenBalances": [{"mint": A, "owner": leader, "uiTokenAmount": {"amount": str(pre), "decimals": 6}}],
                         "postTokenBalances": [{"mint": A, "owner": leader, "uiTokenAmount": {"amount": str(post), "decimals": 6}}]}}
    txs = {"s1": tx(-1.0, 0, 10_000_000, now - 7200), "s2": tx(2.0, 10_000_000, 0, now - 3600)}

    async def rpc(method, params):
        if "before" in params[1]:
            return []
        return [{"signature": "s2", "blockTime": now - 3600, "err": None},
                {"signature": "s1", "blockTime": now - 7200, "err": None}]

    async def batch(sigs):
        return [txs[s] for s in sigs]

    async def hist(since):
        return [now - 7300, now - 3700], [100.0, 150.0]

    async def price():
        return 150.0
    monkeypatch.setattr(ct, "rpc", rpc)
    monkeypatch.setattr(wp, "_batch", batch)
    monkeypatch.setattr(wp, "_sol_history", hist)
    monkeypatch.setattr(ct, "sol_price", price)
    wp._cache.clear()
    r = asyncio.run(wp.analyze(leader))
    d = r["windows"]["24h"]
    assert d["trades"] == 1 and d["pnl_usd"] == 200 and d["roi_pct"] == 200   # bought 1 SOL at $100, sold 2 SOL at $150
    assert r["coverage"]["swaps"] == 2 and not r["coverage"]["partial"]
    assert wp.cached(leader) is r


def test_a_refused_batch_is_unread_not_fatal(monkeypatch):
    calls = {"n": 0}

    async def refuse(sigs):
        calls["n"] += 1
        raise RuntimeError("RPC 429")

    async def no_wait(_):
        return None
    monkeypatch.setattr(wp, "_batch_once", refuse)
    monkeypatch.setattr(wp.asyncio, "sleep", no_wait)
    assert asyncio.run(wp._batch(["a", "b"])) == [None, None]
    assert calls["n"] == 3
