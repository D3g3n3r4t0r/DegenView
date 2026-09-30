import asyncio
import time

from app.trading.onchain import unlocks


def _fake(code: str, views: dict):
    async def rpc(chain, method, params, client):
        if method == "eth_getCode":
            return code
        data = params[0]["data"][2:10]
        for sig, v in views.items():
            if unlocks._sel(sig) == data:
                return "0x" + format(v, "064x")
        return "0x"
    return rpc


def test_eip7702_account_is_a_wallet(monkeypatch):
    monkeypatch.setattr(unlocks, "_rpc", _fake("0xef01006c35fbcf24e57e5aa2e3aa2ca82e052499d02cf8", {}))
    assert asyncio.run(unlocks.probe("robinhood", "0xt", "0xa", None))["kind"] == "wallet"


def test_vesting_wallet_gives_its_end(monkeypatch):
    start = 1_780_000_000
    monkeypatch.setattr(unlocks, "_rpc", _fake("0x6080", {"start()": start, "duration()": 365 * 86400}))
    r = asyncio.run(unlocks.probe("base", "0xt", "0xa", None))
    assert r["kind"] == "vesting" and r["end"] == start + 365 * 86400


def test_locker_with_the_lp_position(monkeypatch):
    monkeypatch.setattr(unlocks, "_rpc", _fake("0x6080", {"isLocked(address)": 1, "lockedPositions(address)": 3216729}))
    r = asyncio.run(unlocks.probe("robinhood", "0xt", "0xa", None))
    assert r["kind"] == "locker" and "LP position" in r["note"] and "no release" in r["note"]


def test_annotate_retags_holders_and_soon_flags_near_unlocks(monkeypatch):
    now = time.time()

    async def probe(chain, token, address, client):
        return {"0xw": {"kind": "wallet", "note": "7702"},
                "0xv": {"kind": "timelock", "unlock_at": int(now + 5 * 86400), "note": "unlocks soon"}}[address]
    monkeypatch.setattr(unlocks, "probe", probe)
    info = {"holders": [{"address": "0xw", "percent": "0.05", "is_contract": 1},
                        {"address": "0xv", "percent": "0.10", "is_contract": 1},
                        {"address": "0xpool", "percent": "0.20", "is_contract": 1}]}
    out = asyncio.run(unlocks.annotate("base", "0xt", info, None, skip={"0xPOOL"}))
    assert info["holders"][0]["is_contract"] == 0 and info["holders"][1]["tag"] == "timelock lock"
    assert len(out) == 2 and unlocks.soon(out, now)[0].startswith("10% unlocks on")
