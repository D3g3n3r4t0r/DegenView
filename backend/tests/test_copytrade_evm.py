"""EVM copy trading (copytrade_evm.py): one 0x wallet, six networks, simulated.

The receipts below are shaped like real ones: ERC-20 Transfer logs with the
wallet in topic 1 or 2, the native balance change across the block, a router
in the middle. No network: rpc and quotes are replaced per test."""
import asyncio
import time

import pytest

from app.trading.onchain import copytrade as ct
from app.trading.onchain import copytrade_evm as evm

LEADER = "0x" + "ab" * 20
ROUTER = "0x" + "cd" * 20
POOL = "0x" + "ef" * 20
TOKEN = "0x" + "12" * 20
OTHER = "0x" + "34" * 20
WETH = evm.CHAINS["base"]["wrapped"]
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
OWNER = "u1"


@pytest.fixture(autouse=True)
def _store(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "STORE_FILE", tmp_path / "copytrade.json")
    monkeypatch.setattr(ct, "_store", None)
    evm._handled.clear()
    evm._last_block.clear()
    yield


def _t(a: str) -> str:
    return "0x" + "0" * 24 + a[2:]


def transfer(token, src, dst, amount, nft=False):
    topics = [evm.TRANSFER, _t(src), _t(dst)] + ([_t(OTHER)] if nft else [])
    return {"address": token, "topics": topics, "data": hex(amount)}


ETH = 10 ** 18


# ── parsing ──────────────────────────────────────────────────────────────

def test_buy_paid_in_native_through_a_router():
    logs = [transfer(WETH, ROUTER, POOL, ETH // 2), transfer(TOKEN, POOL, LEADER, 1_000 * 10 ** 9)]
    s = evm.parse_evm_swap("base", LEADER, logs, -ETH // 2, {TOKEN: 9})
    assert s["side"] == "buy" and s["token"] == TOKEN and s["units"] == 1_000
    assert s["native"] == pytest.approx(0.5) and s["stable_usd"] == 0


def test_buy_paid_in_weth_counts_as_native_and_usdc_as_dollars():
    s = evm.parse_evm_swap("base", LEADER, [transfer(WETH, LEADER, POOL, ETH), transfer(TOKEN, POOL, LEADER, 5)], 0, {})
    assert s["side"] == "buy" and s["native"] == pytest.approx(1.0)
    s = evm.parse_evm_swap("base", LEADER, [transfer(USDC, LEADER, POOL, 250 * 10 ** 6), transfer(TOKEN, POOL, LEADER, 5)], 0, {})
    assert s["stable_usd"] == pytest.approx(250.0) and s["native"] == 0


def test_sell_for_native():
    logs = [transfer(TOKEN, LEADER, POOL, 400), transfer(WETH, POOL, ROUTER, ETH)]
    s = evm.parse_evm_swap("base", LEADER, logs, ETH, {TOKEN: 0})
    assert s["side"] == "sell" and s["raw"] == 400 and s["native"] == pytest.approx(1.0)


def test_transfers_nfts_and_token_to_token_are_not_trades():
    assert evm.parse_evm_swap("base", LEADER, [transfer(TOKEN, OTHER, LEADER, 5)], 0, {}) is None          # airdrop
    assert evm.parse_evm_swap("base", LEADER, [transfer(TOKEN, LEADER, OTHER, 5)], 0, {}) is None          # sent away
    assert evm.parse_evm_swap("base", LEADER, [transfer(TOKEN, POOL, LEADER, 5, nft=True)], -ETH, {}) is None
    two = [transfer(TOKEN, LEADER, POOL, 5), transfer(OTHER, POOL, LEADER, 7)]
    assert evm.parse_evm_swap("base", LEADER, two, 0, {}) is None


def test_bsc_usdt_has_18_decimals():
    usdt = "0x55d398326f99059ff775485246999027b3197955"
    s = evm.parse_evm_swap("bsc", LEADER, [transfer(usdt, LEADER, POOL, 100 * ETH), transfer(TOKEN, POOL, LEADER, 9)], 0, {})
    assert s["stable_usd"] == pytest.approx(100.0)


def test_sell_fraction_from_what_he_still_holds():
    assert evm.sell_fraction(400, 600) == pytest.approx(0.4)
    assert evm.sell_fraction(400, 0) == 1.0


def test_addresses():
    assert evm.is_evm("0x" + "aB" * 20) and not evm.is_evm("9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")
    assert not evm.is_evm("0x123")


# ── following ────────────────────────────────────────────────────────────

def test_follow_an_evm_wallet_on_picked_chains_simulated_only():
    f = ct.set_follow(OWNER, "0x" + "AB" * 20, {"chains": ["bsc", "base", "nope"]})
    assert f["address"] == LEADER and f["chains"] == ["base", "bsc"]          # lower-cased, ordered, unknown dropped
    assert ct.set_follow(OWNER, LEADER, {"label": "x"})["chains"] == ["base", "bsc"]   # kept when not sent
    with pytest.raises(ValueError, match="at least one"):
        ct.set_follow(OWNER, LEADER, {"chains": []})
    ct.set_real_ok(OWNER, True)
    with pytest.raises(ValueError, match="Simulated"):
        ct.set_follow(OWNER, LEADER, {"mode": "real"})


def test_default_chains_are_all_and_watchers_are_split():
    ct.set_follow(OWNER, LEADER, {})
    ct.set_follow(OWNER, "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM", {})
    assert ct.account(OWNER)["follows"][LEADER]["chains"] == list(evm.CHAINS)
    assert list(ct.watched("solana")) == ["9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"]
    assert list(ct.watched("evm")) == [LEADER]
    ct.set_follow(OWNER, LEADER, {"chains": ["base"]})
    assert evm.watched("base") == {LEADER: [OWNER]} and evm.watched("bsc") == {}
    ct.remove_follow(OWNER, "0x" + "AB" * 20)
    assert LEADER not in ct.account(OWNER)["follows"]


# ── copying, end to end with a fake chain ────────────────────────────────

class FakeChain:
    def __init__(self, logs, native_delta, left=0):
        self.logs, self.native_delta, self.left = logs, native_delta, left
        self.calls = []

    async def rpc(self, chain, method, params):
        self.calls.append(method)
        if method == "eth_getTransactionReceipt":
            return {"status": "0x1", "logs": self.logs, "gasUsed": "0x0", "effectiveGasPrice": "0x0"}
        if method == "eth_getTransactionByHash":
            return {"from": LEADER}
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(int(time.time()) - 3)}
        if method == "eth_getBalance":
            return hex(10 * ETH + (self.native_delta if params[1] == hex(100) else 0))
        if method == "eth_call":
            data = params[0]["data"]
            return hex(9) if data == "0x313ce567" else hex(self.left)
        if method == "eth_blockNumber":
            return hex(100)
        if method == "eth_getLogs":
            return self.logs
        raise AssertionError(method)


def _quotes(monkeypatch, per_eth_units=1_000 * 10 ** 9, sellable=True):
    async def quote(chain, token_in, token_out, amount_in):
        if token_in == evm.NATIVE:
            return {"amount_out": amount_in * per_eth_units // ETH, "in_usd": None, "out_usd": None}
        if not sellable:
            raise evm.NoRoute("KyberSwap: route not found")
        return {"amount_out": amount_in * ETH // per_eth_units * 99 // 100, "in_usd": None, "out_usd": None}

    async def price(chain, probe=None):
        return 3000.0
    monkeypatch.setattr(evm, "quote", quote)
    monkeypatch.setattr(evm, "native_usd", price)


def test_a_buy_then_a_sell_are_copied_in_simulation(monkeypatch):
    ct.set_follow(OWNER, LEADER, {"chains": ["base"], "sizing": "fixed", "fixed_usd": 40})
    _quotes(monkeypatch)
    buy = FakeChain([transfer(WETH, ROUTER, POOL, ETH // 10), transfer(TOKEN, POOL, LEADER, 100 * 10 ** 9)], -ETH // 10)
    monkeypatch.setattr(evm, "rpc", buy.rpc)
    asyncio.run(evm.handle_tx("base", LEADER, "0xbuy", 100))
    acc = ct.account(OWNER)
    row = acc["trades"][0]
    assert row["status"] == "sim" and row["chain"] == "base" and row["usd"] == 40.0
    assert row["leader_usd"] == pytest.approx(300.0)                      # 0.1 ETH at $3,000
    pos = acc["positions"][LEADER][evm.position_key("base", TOKEN)]
    assert pos["chain"] == "base" and pos["qty"] == pytest.approx(40 / 3000 * 1000)
    assert ct.spent_today(acc) == 40.0

    sell = FakeChain([transfer(TOKEN, LEADER, POOL, 100 * 10 ** 9), transfer(WETH, POOL, ROUTER, ETH // 5)], ETH // 5, left=0)
    monkeypatch.setattr(evm, "rpc", sell.rpc)
    asyncio.run(evm.handle_tx("base", LEADER, "0xsell", 100))
    row = acc["trades"][0]
    assert row["status"] == "sim" and row["side"] == "sell" and row["frac"] == 1.0
    assert row["pnl_usd"] == pytest.approx(-0.4, abs=0.05)                # the 1% the fake quote keeps
    assert LEADER not in acc["positions"]


def test_honeypot_is_skipped(monkeypatch):
    ct.set_follow(OWNER, LEADER, {"chains": ["base"], "sizing": "fixed", "fixed_usd": 40})
    _quotes(monkeypatch, sellable=False)
    chain = FakeChain([transfer(WETH, ROUTER, POOL, ETH // 10), transfer(TOKEN, POOL, LEADER, 10 ** 9)], -ETH // 10)
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    asyncio.run(evm.handle_tx("base", LEADER, "0xhp", 100))
    row = ct.account(OWNER)["trades"][0]
    assert row["status"] == "skipped" and "sell it back" in row["reason"]
    assert ct.spent_today(ct.account(OWNER)) == 0


def test_arc_trades_are_seen_and_logged_not_copied(monkeypatch):
    ct.set_follow(OWNER, LEADER, {"chains": ["arc"]})
    _quotes(monkeypatch)
    chain = FakeChain([transfer(TOKEN, POOL, LEADER, 10 ** 9)], -5 * ETH)
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    asyncio.run(evm.handle_tx("arc", LEADER, "0xarc", 100))
    row = ct.account(OWNER)["trades"][0]
    assert row["status"] == "skipped" and "no trusted quote source on Arc" in row["reason"]


def test_a_chain_not_picked_is_ignored(monkeypatch):
    ct.set_follow(OWNER, LEADER, {"chains": ["bsc"]})
    _quotes(monkeypatch)
    chain = FakeChain([transfer(WETH, ROUTER, POOL, ETH), transfer(TOKEN, POOL, LEADER, 10 ** 9)], -ETH)
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    asyncio.run(evm.handle_tx("base", LEADER, "0xx", 100))
    assert ct.account(OWNER)["trades"] == [] and chain.calls == []


def test_poll_finds_the_leaders_transactions(monkeypatch):
    ct.set_follow(OWNER, LEADER, {"chains": ["base"]})
    chain = FakeChain([{**transfer(TOKEN, POOL, LEADER, 5), "transactionHash": "0xabc", "blockNumber": hex(99)}], 0)
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    seen = []

    async def handle(c, leader, tx, block):
        seen.append((c, leader, tx, block))
    monkeypatch.setattr(evm, "handle_tx", handle)

    async def go():
        await evm.poll_chain("base")
        await asyncio.sleep(0)
    asyncio.run(go())
    assert seen == [("base", LEADER, "0xabc", 99)]
    assert evm._last_block["base"] == 100 and evm.status["base"]["state"] == "watching"


def test_a_position_is_closed_by_hand(monkeypatch):
    ct.set_follow(OWNER, LEADER, {"chains": ["base"], "sizing": "fixed", "fixed_usd": 40})
    _quotes(monkeypatch)
    chain = FakeChain([transfer(WETH, ROUTER, POOL, ETH // 10), transfer(TOKEN, POOL, LEADER, 10 ** 11)], -ETH // 10)
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    asyncio.run(evm.handle_tx("base", LEADER, "0xb", 100))
    row = asyncio.run(ct.close_position(OWNER, LEADER, evm.position_key("base", TOKEN)))
    assert row["status"] == "sim" and row["manual"] and LEADER not in ct.account(OWNER)["positions"]


# ── KyberSwap's answer ───────────────────────────────────────────────────

def _kyber(monkeypatch, handler):
    import httpx
    real = httpx.AsyncClient
    monkeypatch.setattr(evm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_kyber_route_reads_the_route_summary(monkeypatch):
    import httpx
    asked = {}

    def handler(request):
        asked.update(path=request.url.path, params=dict(request.url.params), client=request.headers.get("x-client-id"))
        return httpx.Response(200, json={"code": 0, "data": {"routeSummary": {
            "amountOut": "123456", "amountInUsd": "300.5", "amountOutUsd": "299.1"}}})
    _kyber(monkeypatch, handler)
    r = asyncio.run(evm.kyber_route("bsc", evm.NATIVE, TOKEN, 10 ** 17))
    assert r == {"amount_out": 123456, "in_usd": 300.5, "out_usd": 299.1}
    assert asked["path"] == "/bsc/api/v1/routes" and asked["params"]["amountIn"] == str(10 ** 17)
    assert asked["client"] == evm.KYBER_CLIENT


def test_kyber_without_a_route_is_no_route(monkeypatch):
    import httpx
    _kyber(monkeypatch, lambda request: httpx.Response(400, json={"code": 4008, "message": "route not found"}))
    with pytest.raises(evm.NoRoute, match="route not found"):
        asyncio.run(evm.kyber_route("base", evm.NATIVE, TOKEN, 1))
    with pytest.raises(evm.NoRoute, match="does not trade on Arc"):
        asyncio.run(evm.kyber_route("arc", evm.NATIVE, TOKEN, 1))


def test_a_slow_network_does_not_hold_the_balances(monkeypatch):
    evm._balance_cache.clear()
    evm._balance_jobs.clear()

    async def slow(chain, owner, block="latest"):
        if chain == "ethereum":
            await asyncio.sleep(0.3)
        return 2 * ETH
    monkeypatch.setattr(evm, "native_balance", slow)

    async def go():
        first = await evm.native_balances(LEADER, wait_s=0.05)     # too slow: nothing yet, no wait
        await asyncio.sleep(0.4)
        second = await evm.native_balances(LEADER, wait_s=0.05)    # the background read landed
        return first, second
    first, second = asyncio.run(go())
    assert first == {} and second["ethereum"] == 2.0 and set(second) == set(evm.CHAINS)
