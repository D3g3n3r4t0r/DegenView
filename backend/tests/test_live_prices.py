import asyncio

from app.trading.onchain import live_prices as lp

SOL = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
EVM = "0xAbCdEf0123456789abcdef0123456789ABCDEF01"


def test_parse_ids_filters_and_normalizes():
    ids = lp.parse_ids(f"solana:{SOL},robinhood:{EVM},robinhood:{EVM.lower()},mars:{SOL},solana:bad,x")
    assert ids == [("solana", SOL), ("robinhood", EVM.lower())]


def test_best_price_is_the_deepest_pool():
    pairs = [
        {"chainId": "solana", "baseToken": {"address": SOL}, "priceUsd": "1.0", "liquidity": {"usd": 10}},
        {"chainId": "solana", "baseToken": {"address": SOL}, "priceUsd": "2.0", "liquidity": {"usd": 900}},
        {"chainId": "bsc", "baseToken": {"address": SOL}, "priceUsd": "9.0", "liquidity": {"usd": 9e9}},
    ]
    assert lp._best_prices(pairs, "solana") == {("solana", SOL): 2.0}


def test_fallback_then_cache_then_stale(monkeypatch):
    lp.reset_for_tests()
    now = [1000.0]
    monkeypatch.setattr(lp, "_clock", lambda: now[0])
    calls = []

    async def ds(client, chain, addrs):
        calls.append("ds")
        return {}

    async def gt(client, chain, addrs):
        calls.append("gt")
        return {(chain, addrs[0]): 0.5}

    monkeypatch.setattr(lp, "_dexscreener", ds)
    monkeypatch.setattr(lp, "_gecko", gt)
    key = [("solana", SOL)]
    out = asyncio.run(lp.prices(key))
    assert out[f"solana:{SOL}"]["p"] == 0.5 and out[f"solana:{SOL}"]["src"] == "geckoterminal"
    asyncio.run(lp.prices(key))
    assert calls == ["ds", "gt"]            # second ask within TTL: from cache
    monkeypatch.setattr(lp, "_gecko", lambda *a: asyncio.sleep(0, {}))
    now[0] += 60
    assert asyncio.run(lp.prices(key))[f"solana:{SOL}"]["age"] == 60   # nobody answers: last price, aged
    now[0] += lp.STALE_S
    assert asyncio.run(lp.prices(key)) == {}                         # too old: left out
