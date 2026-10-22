import asyncio

from app.trading.onchain import sync_sells as ss

S = ss.SAMPLE
W, POOL = S["wallets"], S["pools"][0]
SUPPLY = S["total_supply"]
OTHER = "0x" + "ee" * 20


def t(block, src, dst, pct, ts=None):
    return {"block": block, "ts": ts, "tx": f"0x{block:x}", "from": src, "to": dst,
            "amount": int(SUPPLY * pct / 100)}


def test_same_block_group_scores_high():
    tx = [t(100, w, POOL, 1.0) for w in W] + [t(100, W[0], W[1], 2.0)]
    r = ss.analyze(tx, W, [POOL], SUPPLY)
    assert r["sellers"] == 5 and r["sold_pct"] == 5.0
    assert len(r["groups"]) == 1 and r["groups"][0]["same_block"]
    assert all(e["to"] != W[1] for e in r["timeline"])  # consolidation is not a sale
    assert r["risk"]["level"] == "high"


def test_window_by_blocks_and_seconds():
    tx = [t(100, W[0], POOL, 0.5, ts=1000), t(103, W[1], POOL, 0.5, ts=1006),
          t(400, W[2], POOL, 0.5, ts=1100), t(9000, W[3], POOL, 0.5, ts=50_000)]
    groups = ss.analyze(tx, W, [POOL], SUPPLY)["groups"]
    assert [g["wallets"] for g in groups] == [sorted(W[:3])]
    assert not groups[0]["same_block"]


def test_lone_seller_and_outflow_weight():
    assert ss.analyze([t(1, W[0], POOL, 3.0)], W, [POOL], SUPPLY)["risk"]["score"] == 0
    sell = ss.analyze([t(1, W[0], POOL, 1.0), t(1, W[1], POOL, 1.0)], W, [POOL], SUPPLY)
    out = ss.analyze([t(1, W[0], OTHER, 1.0), t(1, W[1], OTHER, 1.0)], W, [POOL], SUPPLY)
    assert out["outflow_pct"] == 2.0 and out["risk"]["parts"]["share"] < sell["risk"]["parts"]["share"]


def test_run_with_fake_rpc():
    def topic(a):
        return "0x" + "0" * 24 + a[2:]
    logs = [{"blockNumber": "0x64", "logIndex": hex(i), "transactionHash": f"0x{i}",
             "topics": [ss.TRANSFER_TOPIC, topic(w), topic(POOL)], "data": hex(SUPPLY // 100)}
            for i, w in enumerate(W[:3])]
    calls = []

    async def rpc(method, params):
        calls.append(method)
        if method == "eth_getLogs":
            assert params[0]["topics"][1] and params[0]["address"] == S["token"]
            return logs if params[0]["fromBlock"] == "0x0" else []
        if method == "eth_getBlockByNumber":
            return {"timestamp": "0x10"}
        return hex(SUPPLY)

    r = asyncio.run(ss.run("robinhood", S["token"], W, [POOL], 0, 6_000, rpc=rpc))
    assert calls.count("eth_getLogs") == 2 and calls.count("eth_getBlockByNumber") == 1
    assert r["sold_pct"] == 3.0 and r["timeline"][0]["ts"] == 16 and r["groups"][0]["same_block"]
