"""KuCoin, every quote (Lorenzo, 15/10: "nei pair a disposizione sul sito,
quelli relativi a KuCoin non compaiono [...] avere a disposizione anche
tutti i pair presenti su KuCoin"). It was scoped to BTC pairs only: ETHUSDT
became "ETHUSDT-BTC", which does not exist."""

from __future__ import annotations

import asyncio

from app.providers import kucoin
from app.providers.kucoin import KucoinProvider, format_symbol


def test_every_quote_is_kept():
    assert format_symbol("ETHUSDT") == "ETH-USDT"
    assert format_symbol("eth/usdt") == "ETH-USDT"
    assert format_symbol("BTCUSDT") == "BTC-USDT"
    assert format_symbol("SOLUSDC") == "SOL-USDC"
    assert format_symbol("ETHBTC") == "ETH-BTC"
    assert format_symbol("KCS-BTC") == "KCS-BTC"


def test_a_bare_base_still_means_the_btc_pair():
    # symbols saved before (drawings, alerts) keep their chart
    assert format_symbol("ETH") == "ETH-BTC"


def test_search_lists_usdt_pairs_first(monkeypatch):
    rows = [{"symbol": s, "baseCurrency": s.split("-")[0], "quoteCurrency": s.split("-")[1], "enableTrading": True}
            for s in ("ETH-BTC", "ETH-USDC", "ETH-USDT", "ETHFI-USDT", "SOL-USDT")]
    kucoin._symbols_cache["all"] = rows
    try:
        out = asyncio.run(KucoinProvider().search_symbols("ETH"))
        assert [o["symbol"] for o in out][:3] == ["ETH-USDT", "ETH-BTC", "ETH-USDC"]
        assert "ETHFI-USDT" in [o["symbol"] for o in out] and "SOL-USDT" not in [o["symbol"] for o in out]
        assert out[0]["exchange"] == "KuCoin (USDT)"
        assert [o["symbol"] for o in asyncio.run(KucoinProvider().search_symbols("ETHUSDT"))] == ["ETH-USDT"]
    finally:
        kucoin._symbols_cache.clear()
