import asyncio
import time

import pytest

from app.trading.onchain import copytrade as ct
from app.trading.onchain import wallet_pnl as wp

NOW = 1_800_000_000
A, B, C = "mintA", "mintB", "mintC"


def sw(t_ago_h, side, mint, units, usd):
    return {"t": NOW - t_ago_h * 3600, "side": side, "mint": mint, "units": units, "usd": usd, "decimals": 6}


def test_average_cost_partial_sells_and_orphans():
    swaps = [sw(100, "buy", A, 100, 100), sw(90, "buy", A, 100, 300),     # avg cost 2 $/token
             sw(10, "sell", A, 50, 150),                                    # cost 100 -> +50
             sw(5, "sell", A, 150, 150),                                    # cost 300 -> -150
             sw(3, "sell", B, 10, 40)]                                      # never bought: no cost
    closes, open_, orphan = wp.realize(swaps)
    assert [round(c["pnl"], 6) for c in closes] == [50, -150]
    assert open_ == {} and len(orphan) == 1 and orphan[0]["mint"] == B


def test_sell_more_than_known_splits_the_orphan_part():
    closes, open_, orphan = wp.realize([sw(5, "buy", A, 10, 10), sw(2, "sell", A, 30, 60)])
    assert closes[0]["cost"] == 10 and closes[0]["proceeds"] == pytest.approx(20)
    assert orphan[0]["units"] == pytest.approx(20) and orphan[0]["usd"] == pytest.approx(40)


def test_windows_count_only_their_sells():
    swaps = [sw(24 * 20, "buy", A, 100, 100), sw(24 * 3, "sell", A, 100, 300),   # +200, 3 days ago
             sw(10, "buy", B, 10, 50), sw(2, "sell", B, 10, 25),                 # -25, opened and closed today
             sw(1, "buy", C, 5, 20)]                                             # still open
    closes, open_, orphan = wp.realize(swaps)
    day = wp.window(swaps, closes, orphan, NOW - wp.DAY)
    week = wp.window(swaps, closes, orphan, NOW - 7 * wp.DAY)
    month = wp.window(swaps, closes, orphan, NOW - 30 * wp.DAY)
    assert day["realized_usd"] == -25 and day["win_rate_pct"] == 0 and day["opened_and_closed_usd"] == -25
    assert week["realized_usd"] == 175 and week["wins"] == 1 and week["losses"] == 1
    assert week["opened_and_closed_usd"] == -25                    # A was opened 20 days ago
    assert month["opened_and_closed_usd"] == 175 and month["roi_pct"] == pytest.approx(116.7)
    assert month["best"]["mint"] == A and month["worst"]["mint"] == B
    assert day["buys"] == 2 and day["bought_usd"] == 70
    assert list(open_) == [C]


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
    assert d["realized_usd"] == 200 and d["roi_pct"] == 200       # bought 1 SOL at $100, sold 2 SOL at $150
    assert r["coverage"]["swaps"] == 2 and not r["coverage"]["partial"]
    assert wp.cached(leader) is r
