"""Profitability of an EVM wallet (wallet_pnl_evm.py), on a fake chain."""
import asyncio
import time

import pytest

from app.trading.onchain import copytrade_evm as evm
from app.trading.onchain import wallet_pnl_evm as pnl

W = "0x" + "ab" * 20
ROUTER = "0x" + "cd" * 20
POOL = "0x" + "ef" * 20
TOKEN = "0x" + "12" * 20
WETH = evm.CHAINS["base"]["wrapped"]
ETH = 10 ** 18


def _t(a):
    return "0x" + "0" * 24 + a[2:]


def transfer(token, src, dst, amount, tx="0x1", block=100):
    return {"address": token, "topics": [evm.TRANSFER, _t(src), _t(dst)], "data": hex(amount),
            "transactionHash": tx, "blockNumber": hex(block)}


def withdrawal(amount):
    return {"address": WETH, "topics": [pnl.WITHDRAWAL, _t(ROUTER)], "data": hex(amount)}


# ── pure part ────────────────────────────────────────────────────────────

def test_native_paid_is_the_value_sent_and_received_is_the_unwrap():
    assert pnl.native_delta_from_tx("base", W, {"from": W, "value": hex(ETH)}, {"logs": []}) == -ETH
    sell = {"logs": [transfer(TOKEN, W, POOL, 5), withdrawal(2 * ETH)]}
    assert pnl.native_delta_from_tx("base", W, {"from": W, "value": "0x0"}, sell) == 2 * ETH
    # someone else's transaction (a router acting for him): no value counted
    assert pnl.native_delta_from_tx("base", W, {"from": ROUTER, "value": hex(ETH)}, {"logs": []}) == 0


def test_a_sell_for_eth_through_an_unwrap_parses_as_a_sell():
    receipt = {"logs": [transfer(TOKEN, W, POOL, 400), transfer(WETH, POOL, ROUTER, ETH), withdrawal(ETH)]}
    delta = pnl.native_delta_from_tx("base", W, {"from": W, "value": "0x0"}, receipt)
    s = evm.parse_evm_swap("base", W, receipt["logs"], delta, {TOKEN: 0})
    assert s["side"] == "sell" and s["native"] == pytest.approx(1.0)


def test_block_time_is_interpolated():
    known = [(100, 1_000), (200, 1_200)]
    assert pnl.block_time(150, known) == 1_100
    assert pnl.block_time(200, known) == 1_200
    assert pnl.block_time(250, known) == 1_300          # past the edge: the same rate


def test_range_errors_are_recognised():
    assert pnl.too_wide("RPC base (eth_getLogs): {'code': -32005, 'message': 'query returned more than 10000 results'}")
    assert pnl.too_wide("block range is too large")
    assert not pnl.too_wide("All RPC endpoints for base failed (last error: 403 Forbidden)")


# ── reading ──────────────────────────────────────────────────────────────

class Chain:
    """Blocks 0..LATEST one second apart starting at T0; logs and txs given."""
    LATEST = 3_000_000

    def __init__(self, logs, txs, max_span=None):
        self.T0 = int(time.time()) - self.LATEST
        self.logs, self.txs, self.max_span = logs, txs, max_span
        self.spans = []

    async def rpc(self, chain, method, params):
        if method == "eth_blockNumber":
            return hex(self.LATEST)
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(self.T0 + int(params[0], 16))}
        if method == "eth_getLogs":
            f = params[0]
            a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            self.spans.append(b - a + 1)
            if self.max_span and b - a + 1 > self.max_span:
                raise RuntimeError("RPC base (eth_getLogs): block range is too large")
            want_from = f["topics"][1] is not None
            who = (f["topics"][1] if want_from else f["topics"][2])
            out = []
            for lg in self.logs:
                blk = int(lg["blockNumber"], 16)
                pos = 1 if want_from else 2
                if a <= blk <= b and len(lg["topics"]) > pos and lg["topics"][pos] == who:
                    out.append(lg)
            return out
        if method == "eth_getTransactionByHash":
            return self.txs[params[0]][0]
        if method == "eth_getTransactionReceipt":
            return self.txs[params[0]][1]
        if method == "eth_call":
            return hex(0)                                   # decimals(): 0 for the fake token
        raise AssertionError(method)


def test_ranges_shrink_when_a_node_refuses_them(monkeypatch):
    chain = Chain([], {}, max_span=800)
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    logs, covered = asyncio.run(pnl.wallet_logs("base", W, 0, 20_000, time.time() + 60, lambda m: None))
    assert covered == 0 and logs == []
    assert min(chain.spans) < 800 and all(s <= 800 for s in chain.spans[-3:])


def test_a_closed_trade_is_measured_end_to_end(monkeypatch):
    now_block = Chain.LATEST
    buy_b, sell_b = now_block - 3_600, now_block - 600          # an hour ago, ten minutes ago
    buy = [transfer(WETH, ROUTER, POOL, ETH // 10, "0xbuy", buy_b), transfer(TOKEN, POOL, W, 1_000, "0xbuy", buy_b)]
    sell = [transfer(TOKEN, W, POOL, 1_000, "0xsell", sell_b), transfer(WETH, POOL, ROUTER, ETH // 5, "0xsell", sell_b),
            {**withdrawal(ETH // 5), "transactionHash": "0xsell", "blockNumber": hex(sell_b)}]
    chain = Chain(buy + sell, {
        "0xbuy": ({"from": W, "value": hex(ETH // 10)}, {"status": "0x1", "logs": buy}),
        "0xsell": ({"from": W, "value": "0x0"}, {"status": "0x1", "logs": sell}),
    })
    monkeypatch.setattr(evm, "rpc", chain.rpc)
    evm._decimals.clear()

    async def history(native, since):
        return [], []

    async def price(c, probe=None):
        return 3000.0
    monkeypatch.setattr(pnl, "_price_history", history)
    monkeypatch.setattr(evm, "native_usd", price)
    r = asyncio.run(pnl.analyze(W, "base"))
    day = r["windows"]["24h"]
    assert r["chain"] == "base" and r["coverage"]["swaps"] == 2 and not r["coverage"]["partial"]
    assert day["trades"] == 1 and day["wins"] == 1
    assert day["invested_usd"] == pytest.approx(300.0) and day["returned_usd"] == pytest.approx(600.0)
    assert day["pnl_usd"] == pytest.approx(300.0)
    assert r["tokens"][0]["mint"] == TOKEN
    assert pnl.cached("base", W.upper().replace("0X", "0x")) is r


def test_bad_input():
    with pytest.raises(ValueError):
        asyncio.run(pnl.analyze("9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM", "base"))
    with pytest.raises(ValueError):
        asyncio.run(pnl.analyze(W, "polygon"))
