import asyncio

from app.trading.onchain import live_prices as lp
from app.trading.onchain import pool_prices as pp

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

    async def jup(client, addrs):
        calls.append("jup")
        return {}

    monkeypatch.setattr(lp, "_dexscreener", ds)
    monkeypatch.setattr(lp, "_gecko", gt)
    monkeypatch.setattr(lp, "_jupiter", jup)
    key = [("solana", SOL)]
    out = asyncio.run(lp.prices(key))
    assert out[f"solana:{SOL}"]["p"] == 0.5 and out[f"solana:{SOL}"]["src"] == "geckoterminal"
    asyncio.run(lp.prices(key))
    assert calls == ["jup", "ds", "gt"]     # second ask within TTL: from cache
    monkeypatch.setattr(lp, "_gecko", lambda *a: asyncio.sleep(0, {}))
    now[0] += 60
    assert asyncio.run(lp.prices(key))[f"solana:{SOL}"]["age"] == 60   # nobody answers: last price, aged
    now[0] += lp.STALE_S
    assert asyncio.run(lp.prices(key)) == {}                         # too old: left out


TOKEN = "0x" + "b" * 40     # > QUOTE: the token is token1
QUOTE = "0x" + "a" * 40
POOL = "0x" + "c" * 40


def _pair(labels, native=2.0, usd=4000.0):
    return {"chainId": "base", "pairAddress": POOL, "labels": labels, "priceNative": str(native), "priceUsd": str(usd),
            "baseToken": {"address": TOKEN}, "quoteToken": {"address": QUOTE}, "liquidity": {"usd": 1}}


def _words(*vals):
    return "0x" + "".join(f"{v:064x}" for v in vals)


def test_pool_price_v2_and_v3_orientation_and_decimals():
    pp.reset_for_tests()
    key = ("base", TOKEN)
    pp.note_pair(key, _pair(None))
    p = pp._pools[key]
    assert p["quote_usd"] == 2000.0 and not p["base_is_0"] and p["kind"] == "v2"
    p["dec"] = (18, 6)                         # token 18 decimals, quote 6
    # token1 = TOKEN: reserves (quote r0, token r1); 2 quote per token
    state = _words(2 * 10 ** 6 * 100, 10 ** 18 * 100, 0)
    assert abs(pp.native_price(p, state) - 2.0) < 1e-9
    pp.note_pair(key, _pair(["v3"]))
    p = pp._pools[key]
    assert p["kind"] == "v3" and p["dec"] == (18, 6)     # same pool: decimals kept
    # price token1 per token0 = 0.5 human -> raw 0.5 * 10**(18-6)
    sqrt = int((0.5 * 10 ** 12) ** 0.5 * 2 ** 96)
    assert abs(pp.native_price(p, _words(sqrt, 0)) / 2.0 - 1) < 1e-9


def test_pool_read_checks_against_dexscreener(monkeypatch):
    pp.reset_for_tests()
    key = ("base", TOKEN)
    pp.note_pair(key, _pair(None))
    state = {"v": _words(2 * 10 ** 18, 10 ** 18, 0)}   # same decimals: 2 quote per token

    class R:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Client:
        async def post(self, url, json):
            out = []
            for c in json:
                data = c["params"][0]["data"]
                out.append({"id": c["id"], "result": _words(18) if data == pp.DECIMALS else state["v"]})
            return R(out)

    assert asyncio.run(pp.read(Client(), "base", [key])) == {key: 4000.0}
    state["v"] = _words(3 * 10 ** 18, 10 ** 18, 0)   # checked once: later blocks follow the pool
    assert asyncio.run(pp.read(Client(), "base", [key])) == {key: 6000.0}
    pp.reset_for_tests()
    pp.note_pair(key, _pair(None))
    assert asyncio.run(pp.read(Client(), "base", [key])) == {}       # 50% off DexScreener: not trusted
    assert not pp.usable(key)
    pp.note_pair(key, _pair(["v4"]))
    assert not pp.usable(key)


def test_onchain_price_wins_and_dexscreener_only_refreshes_the_pool(monkeypatch):
    lp.reset_for_tests()
    now = [1000.0]
    monkeypatch.setattr(lp, "_clock", lambda: now[0])
    monkeypatch.setattr(pp, "_clock", lambda: now[0])
    key = ("base", TOKEN)
    pp.note_pair(key, _pair(None))
    calls = []

    async def onchain(client, chain, keys):
        calls.append("chain")
        return {key: 4100.0}

    async def ds(client, chain, addrs):
        calls.append("ds")
        return {key: 4000.0}

    monkeypatch.setattr(lp, "_onchain", onchain)
    monkeypatch.setattr(lp, "_dexscreener", ds)
    out = asyncio.run(lp.prices([key]))
    assert out[f"base:{TOKEN}"] == {"p": 4100.0, "age": 0.0, "src": "onchain"} and calls == ["chain"]
    now[0] += pp.META_S
    out = asyncio.run(lp.prices([key]))
    assert out[f"base:{TOKEN}"]["p"] == 4100.0 and calls == ["chain", "chain", "ds"]
