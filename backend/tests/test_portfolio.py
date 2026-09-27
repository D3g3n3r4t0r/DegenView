"""Every token on every chain (portfolio.py), on fake sources."""
import asyncio

import pytest

from app.trading.onchain import portfolio as pf

EVM = "0x" + "a" * 40
SOL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    pf.reset_for_tests()

    async def solana(addr, c):
        return 2.0, [{"token": "PUMPmint", "amount": 1000.0, "decimals": 6},
                     {"token": "SPAMmint", "amount": 5.0, "decimals": 6}]

    async def base(addr, c):
        return 0.1, [{"token": "0xUSDCbase", "amount": 50.0, "decimals": 6, "symbol": "USDC", "name": "USD Coin", "price": None}]

    async def eth(addr, c):
        return 0.0, []

    async def robinhood(addr, c):
        return 0.02, [{"token": "0xMEME", "amount": 3.0, "decimals": 18}]

    async def bsc(addr, c):
        raise RuntimeError("rpc down")

    async def prices(chain, tokens, c):
        table = {"PUMPmint": {"price": 0.002, "symbol": "PUMP", "name": "Pump"}, "0xmeme": {"price": 4.0, "symbol": "MEME", "name": "Meme"}}
        return {k: v for k, v in table.items() if k in tokens or k in [t.lower() for t in tokens]}

    async def native(chain, c):
        return {"solana": 150.0, "base": 3000.0, "robinhood": 3000.0}.get(chain)
    monkeypatch.setattr(pf, "READERS", {"solana": solana, "base": base, "ethereum": eth, "robinhood": robinhood, "bsc": bsc})
    monkeypatch.setattr(pf, "dex_prices", prices)
    monkeypatch.setattr(pf, "native_price", native)
    yield
    pf.reset_for_tests()


def test_everything_sums_every_chain_and_names_what_it_could_not_read():
    res = asyncio.run(pf.everything([("evm", EVM, "site"), ("solana", SOL, "connected")]))
    # SOL 2*150 + PUMP 2 + base ETH 300 + USDC 50 + RH ETH 60 + MEME 12
    assert res["total"] == pytest.approx(300 + 2 + 300 + 50 + 60 + 12)
    assert res["cash"] == pytest.approx(50.0)
    assert res["by_chain"]["solana"] == pytest.approx(302) and res["by_chain"]["base"] == pytest.approx(350)
    assert res["missing"] == [{"chain": "bsc", "address": EVM}]
    spam = next(h for h in res["holdings"] if h["token"] == "SPAMmint")
    assert spam["hidden"] and spam["value_usd"] is None
    assert {h["chain"] for h in res["holdings"]} == {"solana", "base", "robinhood"}


def test_wallet_is_cached_for_a_minute():
    calls = []

    async def counting(addr, c):
        calls.append(addr)
        return 1.0, []
    pf.READERS["solana"] = counting
    asyncio.run(pf.wallet("solana", SOL))
    asyncio.run(pf.wallet("solana", SOL))
    assert len(calls) == 1


def test_a_failed_read_falls_back_to_the_last_one_not_to_zero():
    asyncio.run(pf.wallet("solana", SOL))

    async def down(addr, c):
        raise RuntimeError("429")
    pf.READERS["solana"] = down
    key = ("solana", SOL)
    pf._cache[key] = (pf._cache[key][0] - pf.TTL_S - 1, pf._cache[key][1])
    held = asyncio.run(pf.wallet("solana", SOL))
    assert held[0]["symbol"] == "SOL" and held[0]["value_usd"] == pytest.approx(300)
    pf._cache[key] = (pf._cache[key][0] - pf.STALE_S, pf._cache[key][1])
    with pytest.raises(RuntimeError):
        asyncio.run(pf.wallet("solana", SOL))


def test_an_unpriced_native_coin_is_not_read_as_zero(monkeypatch):
    async def no_price(chain, c):
        return None
    monkeypatch.setattr(pf, "native_price", no_price)
    res = asyncio.run(pf.everything([("solana", SOL, "site")]))
    assert res["missing_chains"] == ["solana"] and res["read"] == {}


class _Resp:
    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


class _Client:
    """A node that answers batches with an error object, singles fine."""
    def __init__(self):
        self.singles = 0

    async def post(self, url, json):
        if isinstance(json, list):
            return _Resp({"jsonrpc": "2.0", "error": {"code": -32600, "message": "batch not supported"}})
        self.singles += 1
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": "0x" + format(10 ** 18, "x")})


def test_a_node_without_batches_is_asked_one_call_at_a_time():
    c = _Client()
    res = asyncio.run(pf._evm_rpc_batch("u", [("eth_getBalance", ["0x", "latest"]), ("eth_call", [{}, "latest"])], c))
    assert c.singles == 2 and int(res[0], 16) == 10 ** 18


def test_solana_tries_the_next_node_on_a_rate_limit():
    class Sol(_Client):
        async def post(self, url, json):
            if url == pf.SOL_RPCS[0]:
                return _Resp({"jsonrpc": "2.0", "id": 1, "error": {"code": 429, "message": "Too many requests"}})
            if json["method"] == "getBalance":
                return _Resp({"result": {"value": 3 * 10 ** 9}})
            return _Resp({"result": {"value": []}})
    native, rows = asyncio.run(pf._solana(SOL, Sol()))
    assert native == 3.0 and rows == []
