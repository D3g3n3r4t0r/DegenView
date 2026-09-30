import asyncio

import httpx

from app.trading.onchain import depth, linked


def _graph():
    drop = [{"id": "hub", "holdings": 5}] + [{"id": f"r{i}", "holdings": 744} for i in range(30)]
    net = [{"id": "a", "holdings": 900}, {"id": "b", "holdings": 800}, {"id": "pool", "holdings": 1}]
    return [{"nodes": drop + [{"id": "whale", "holdings": 744}],
             "links": [{"source": "hub", "target": f"r{i}"} for i in range(30)] + [{"source": "hub", "target": "whale"}]},
            {"nodes": net, "links": [{"source": "a", "target": "b"}, {"source": "b", "target": "pool"}]}]


def test_airdrop_links_and_pools_do_not_make_groups():
    kept, airdrop, _ = linked.groups(_graph(), skip={"pool"})
    assert kept == [{"a", "b"}] and airdrop == 31


def test_verify_reads_balances_now(monkeypatch):
    balances = {"a": 0.0, "b": 50_000.0}

    async def rpc(chain, method, params, timeout=15.0):
        return {"value": [{"account": {"data": {"parsed": {"info": {"tokenAmount": {"uiAmount": balances[params[0]]}}}}}}]}

    monkeypatch.setattr(linked.rpc_client, "call_rpc", rpc)
    linked._cache.clear()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_graph()))
    report = {"token": {"supply": 1_000_000 * 10**6, "decimals": 6}, "knownAccounts": {"pool": {"type": "AMM"}},
              "totalHolders": 3000, "topHolders": [{"address": "h", "owner": "o", "pct": 2.0}],
              "insiderNetworks": [{"size": 33, "currentHolding": 400_000 * 10**6}], "graphInsidersDetected": 33,
              "mintAuthority": None, "freezeAuthority": None, "markets": [], "transferFee": {"pct": 0}}

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await linked.verify("mint", report, c)

    v = asyncio.run(go())
    assert v["wallets"] == 2 and v["airdrop_wallets"] == 31 and round(v["pct"], 1) == 5.0
    p = depth.judge_tokenomics_solana(report, verified=v)
    assert p["facts"]["linked_pct"] == 5.0 and "checked on-chain" in p["flags"][0]


def test_failed_reads_leave_rugcheck_figure(monkeypatch):
    async def rpc(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(linked.rpc_client, "call_rpc", rpc)
    linked._cache.clear()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_graph()))

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await linked.verify("mint2", {"token": {"supply": 10**12, "decimals": 6}}, c)

    assert asyncio.run(go()) is None
