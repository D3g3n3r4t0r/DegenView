"""The Top 50 gems' trend follower trades replayed on one wallet."""
from __future__ import annotations

import numpy as np

from app.trading.onchain import portfolio_replay as pr
from app.trading.onchain import system


def _gem(tok, events, last=None):
    return {"chain": "solana", "token": tok, "symbol": tok.upper(), "interval": "1d", "events": events, "last": last}


def test_every_gem_trade_runs_on_one_wallet_in_time_order():
    a = _gem("a", [{"t": 100, "side": "buy", "price": 1.0}, {"t": 300, "side": "sell", "price": 1.5, "ret": 0.5}])
    b = _gem("b", [{"t": 200, "side": "buy", "price": 2.0}, {"t": 400, "side": "sell", "price": 1.0, "ret": -0.5}])
    out = pr.replay([a, b], cash=10_000, pct=10)
    # a takes 10% of 10 000; b 10% of the value at cost (still 10 000)
    assert [(r["symbol"], r["stake"], r["pnl"]) for r in out["trades"]] == [("B", 1000.0, -500.0), ("A", 1000.0, 500.0)]
    assert out["final"] == 10_000 and out["closed"] == 2 and out["wins"] == 1 and out["traded"] == 2
    assert out["curve"][0] == [100, 10_000.0]


def test_an_open_trade_is_marked_at_the_last_close_and_no_cash_means_skipped():
    a = _gem("a", [{"t": 100, "side": "buy", "price": 1.0}], last=2.0)
    b = _gem("b", [{"t": 200, "side": "buy", "price": 1.0}])
    out = pr.replay([a, b], cash=1000, pct=100)
    assert out["skipped"] == 1 and len(out["open"]) == 1
    assert abs(out["open"][0]["ret"] - (1 - pr.FEE)) < 1e-9
    assert abs(out["final"] - 1000 * (2 - pr.FEE)) < 0.01


def test_a_sell_frees_cash_before_a_buy_at_the_same_time():
    a = _gem("a", [{"t": 100, "side": "buy", "price": 1.0}, {"t": 200, "side": "sell", "price": 1.0, "ret": 0.0}])
    b = _gem("b", [{"t": 200, "side": "buy", "price": 1.0}, {"t": 300, "side": "sell", "price": 1.0, "ret": 0.0}])
    out = pr.replay([a, b], cash=100, pct=100)
    assert out["skipped"] == 0 and out["closed"] == 2


def test_the_chart_arrows_sit_on_the_fill_candle_not_the_signal_one():
    """Lorenzo, 30/09: the entries were not drawn where they happened. The
    backtest fills at the next candle's open: the arrow goes there."""
    rng = np.random.default_rng(3)
    n = 400
    closes = np.cumprod(1 + np.concatenate([rng.normal(0.01, 0.02, n // 2), rng.normal(-0.01, 0.02, n // 2)]))
    t0 = 1_700_000_000
    bars = [[t0 + i * 86400, closes[i - 1] if i else closes[0], max(closes[i], closes[i - 1] if i else closes[0]) * 1.01,
             min(closes[i], closes[i - 1] if i else closes[0]) * 0.99, closes[i], 1000.0] for i in range(n)]
    bt = system.backtest_one(bars)
    ev = (bt.get("best") or {}).get("events") or []
    assert ev and bt["best"]["fills"] == "next_open" and bt["last"] == closes[-1]
    opens = {b[0]: b[1] for b in bars}
    for v in ev:
        assert v["t"] in opens or v["t"] == bars[-1][0] + 86400
        if v["side"] == "buy" and v["t"] in opens:
            # the entry price is that candle's open plus slippage, never an earlier close
            assert abs(v["price"] / opens[v["t"]] - 1) < 0.01
