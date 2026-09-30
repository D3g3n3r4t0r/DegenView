"""Strategy arrows on the candle where the trade fills."""
from __future__ import annotations

import numpy as np

from app.trading.onchain import system


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
