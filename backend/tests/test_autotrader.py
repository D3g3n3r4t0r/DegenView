"""The system trading the Robinhood wallet (autotrader.py), on a fake chain."""
import asyncio
from types import SimpleNamespace

import pytest

from app.trading.onchain import alert_track as at
from app.trading.onchain import autotrader as tr

T0 = 1_790_000_000
LABEL = "Lorenzo HF"


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "a.json")
    monkeypatch.setattr(at, "_BARS_FILE", tmp_path / "b.json")
    monkeypatch.setattr(tr, "_STORE_FILE", tmp_path / "t.json")
    at.reset_for_tests()
    tr.reset_for_tests()
    yield
    at.reset_for_tests()
    tr.reset_for_tests()


def _alert(state="in", in_at=T0, sym="FROG", events=None):
    a = at.record({"chain": "robinhood", "pair_address": f"P{sym}", "token_address": f"0x{sym}", "symbol": sym}, "meme", T0 - 600)
    a["entry"] = 1.0
    a["last"] = {"price": 1.0, "ret": 0, "at": T0}
    a["system"] = {LABEL: {"state": state, "in_at": in_at, "events": events or [{"side": "buy", "t": in_at}], "ret": 0}}
    return a


def _market(usdg=100_000_000, eth=10**18, route="uniswap-v3", out=5_000_000, swaps=None):
    swaps = swaps if swaps is not None else []

    async def bal(owner):
        return usdg

    async def tok(owner, token):
        return out

    async def eth_(owner):
        return eth

    async def gas():
        return 10**8

    async def dec(token):
        return 6

    async def quote(tin, tout, amount):
        return {"out": out if tin == tr.USDG else amount * 2, "route": route, "fee": 3000, "impact": 0.5}

    async def swap(**kw):
        swaps.append(kw)
        return {"ok": True, "tx": "0xabc"}
    return tr.Market(bal, tok, eth_, gas, dec, quote, swap)


USER = SimpleNamespace(id="u1", onchain_wallets={"robinhood": SimpleNamespace(address="0x" + "1" * 40)})


def test_sim_buys_the_share_then_sells_when_the_system_leaves():
    a = _alert()
    tr.configure("u1", "sim", 50, usdg_now=80.0)
    rows = asyncio.run(tr.tick([USER], now=T0 + 60, market=_market()))
    assert rows[0]["side"] == "buy" and rows[0]["ok"] and rows[0]["usdg"] == pytest.approx(40.0, abs=1e-5)
    v = tr.view("u1")
    assert v["position"]["symbol"] == "FROG" and v["sim"]["usdg"] == pytest.approx(40.0, abs=1e-5)
    # nothing new: no second entry, no exit
    assert asyncio.run(tr.tick([USER], now=T0 + 120, market=_market())) == []
    a["system"][LABEL] = {"state": "out", "events": [{"side": "buy"}, {"side": "sell"}]}
    rows = asyncio.run(tr.tick([USER], now=T0 + 180, market=_market()))
    assert rows[0]["side"] == "sell" and rows[0]["why"] == "system sold" and tr.view("u1")["position"] is None


def test_old_buy_signal_is_not_chased_and_off_means_no_entries():
    _alert(in_at=T0 - tr.FRESH_S - 60)
    tr.configure("u1", "sim", 100, usdg_now=10.0)
    assert asyncio.run(tr.tick([USER], now=T0, market=_market())) == []
    _alert(sym="NEW", in_at=T0)
    tr.configure("u1", "off")
    assert asyncio.run(tr.tick([USER], now=T0 + 10, market=_market())) == []


def test_real_needs_gas_and_a_signable_route():
    _alert()
    tr.configure("u1", "real", 100)
    rows = asyncio.run(tr.tick([USER], now=T0 + 60, market=_market(eth=0)))
    assert not rows[0]["ok"] and "ETH for gas" in rows[0]["reason"]
    tr.reset_for_tests()
    _alert(sym="AGG")
    tr.configure("u1", "real", 100)
    rows = asyncio.run(tr.tick([USER], now=T0 + 60, market=_market(route="aggregator")))
    assert not rows[0]["ok"] and "aggregator" in rows[0]["reason"]


def test_real_buy_spends_the_share_minus_one_unit_with_slippage_floor():
    _alert()
    swaps = []
    tr.configure("u1", "real", 25)
    rows = asyncio.run(tr.tick([USER], now=T0 + 60, market=_market(usdg=100_000_000, swaps=swaps)))
    assert rows[0]["ok"] and swaps[0]["amount_in"] == 25_000_000 - 1
    assert swaps[0]["min_out"] == int(5_000_000 * (1 - tr.SLIPPAGE)) and swaps[0]["token_in"] == tr.USDG


def test_rug_closes_the_position():
    a = _alert()
    tr.configure("u1", "sim", 100, usdg_now=10.0)
    asyncio.run(tr.tick([USER], now=T0 + 60, market=_market()))
    a["gone"] = True
    rows = asyncio.run(tr.tick([USER], now=T0 + 120, market=_market()))
    assert rows[0]["why"] == "pool gone"


def test_bad_settings_are_refused():
    with pytest.raises(ValueError):
        tr.configure("u1", pct=33)
    with pytest.raises(ValueError):
        tr.configure("u1", mode="yolo")
