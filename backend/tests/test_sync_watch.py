import asyncio
import json

import pytest

from app.trading.onchain import storage, sync_sells as ss, sync_watch as sw

S = ss.SAMPLE
W, POOL, SUPPLY = S["wallets"], S["pools"][0], S["total_supply"]


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    return tmp_path


def upload(**kw):
    return {"chain": "robinhood", "token": S["token"], "symbol": "VERDEX", "pools": [POOL],
            "wallets": W[:3], "extra_wallets": [W[3]], "details": [{"address": W[0], "pct_now": 2.5}], **kw}


def test_clean_rejects_bad_uploads():
    for bad in ({}, upload(chain="mars"), upload(token="nope"), upload(wallets=[W[0]], extra_wallets=[]),
                upload(pools=["0x12"])):
        with pytest.raises(ValueError):
            sw.clean(bad)
    cfg = sw.clean(upload(shares={W[1]: 0.01}))
    assert cfg["wallets"] == W[:4] and cfg["shares"] == {W[0]: 0.025, W[1]: 0.01}


def test_upload_run_writes_report_and_keeps_wallets_off_summary(data):
    sw.save(upload())
    topic = lambda a: "0x" + "0" * 24 + a[2:]  # noqa: E731
    logs = [{"blockNumber": "0x64", "logIndex": hex(i), "transactionHash": f"0x{i}",
             "topics": [ss.TRANSFER_TOPIC, topic(w), topic(POOL)], "data": hex(SUPPLY // 100)}
            for i, w in enumerate(W[:3])]
    seen = []

    async def rpc(method, params):
        seen.append(method)
        if method == "eth_blockNumber":
            return hex(200)
        if method == "eth_getLogs":
            return logs if params[0]["fromBlock"] == hex(0) else []
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(int(__import__("time").time()))}
        return hex(SUPPLY)

    cfg = sw.watched()[0]
    state = asyncio.run(sw.run_one(cfg, rpc))
    assert state["next_block"] == 201 and state["error"] is None
    rep = json.loads((data / "coordinated_sells" / f"robinhood-{S['token']}.json").read_text())
    assert rep["version"] == 1 and rep["events"][0]["wallets"] == 3 and rep["clusters"][0]["share"] == 0.025
    [row] = sw.summary()
    assert row["wallets"] == 4 and "0x" not in json.dumps({k: v for k, v in row.items() if k != "token"})
    assert sw.remove("robinhood", S["token"]) and sw.watched() == []
