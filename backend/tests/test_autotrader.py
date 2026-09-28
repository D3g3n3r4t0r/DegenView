"""The system trading the Robinhood wallet (autotrader.py), on a fake chain."""
import asyncio
from types import SimpleNamespace

import pytest

from app.trading.onchain import alert_track as at
from app.trading.onchain import autotrader as tr

T0 = 1_790_000_000
LABEL = "Trend HF"


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
    a["alert_bt"] = {LABEL: {"state": state, "in_at": in_at, "events": events or [{"side": "buy", "t": in_at}], "ret": 0}}
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
    a["alert_bt"][LABEL] = {"state": "out", "events": [{"side": "buy"}, {"side": "sell"}]}
    rows = asyncio.run(tr.tick([USER], now=T0 + 180, market=_market()))
    assert rows[0]["side"] == "sell" and rows[0]["why"] == "system sold" and tr.view("u1")["position"] is None


def test_old_alert_is_not_chased_and_off_means_no_entries():
    _alert()                                     # alerted at T0 - 600
    tr.configure("u1", "sim", 100, usdg_now=10.0)
    assert asyncio.run(tr.tick([USER], now=T0 + tr.FRESH_S, market=_market())) == []
    _alert(sym="NEW")
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


USDC = "0x" + "c" * 40


def _cash_market(usdc=60_000_000, usdg=0, swaps=None):
    m = _market(usdg=usdg, swaps=swaps)

    async def tok(owner, token):
        return usdc if token == USDC else 5_000_000

    async def quote(tin, tout, amount):
        if {tin, tout} == {USDC, tr.USDG}:
            return {"out": amount * 999 // 1000, "route": "uniswap-v3", "fee": 100, "impact": 0.01}
        return {"out": 5_000_000 if tin == tr.USDG else amount * 2, "route": "uniswap-v3", "fee": 3000, "impact": 0.5}

    async def find():
        return USDC
    m.token_balance, m.quote, m.find_usdc = tok, quote, find
    return m


def test_real_buy_converts_usdc_to_usdg_first_and_sells_back_to_usdc():
    a = _alert()
    swaps = []
    tr.configure("u1", "real", 50)
    rows = asyncio.run(tr.tick([USER], now=T0 + 60, market=_cash_market(usdc=60_000_000, usdg=0, swaps=swaps)))
    assert rows[0]["ok"] and rows[0]["via"] == ["USDC→USDG"]
    assert swaps[0]["token_in"] == USDC and swaps[0]["token_out"] == tr.USDG and swaps[0]["amount_in"] == 30_000_000 - 1
    assert swaps[1]["token_in"] == tr.USDG and swaps[1]["amount_in"] == int((30_000_000 - 1) * 999 // 1000 * (1 - tr.CASH_SLIPPAGE))
    a["alert_bt"][LABEL] = {"state": "out", "events": [{"side": "sell"}]}
    rows = asyncio.run(tr.tick([USER], now=T0 + 120, market=_cash_market(swaps=swaps)))
    assert rows[0]["ok"] and rows[0]["via"] == ["USDG→USDC"] and swaps[-1]["token_out"] == USDC


def test_sim_follows_every_alert_on_every_chain_with_the_backtest_trade():
    """Lorenzo, 28/09: "il wallet simulato non sembra replicare gli ingressi
    [...] voglio che li segua". Each alert gets its share; the result is the
    Strategies tab's trade on it."""
    a = _alert(sym="FROG")
    b = at.record({"chain": "solana", "pair_address": "PS", "token_address": "SOL1", "symbol": "SOLY"}, "meme", T0 - 300)
    b["alert_bt"] = {LABEL: {"state": "in", "in_at": T0 - 300, "events": [{"side": "buy"}], "ret": 0}}
    tr.configure("u1", "sim", 25, usdg_now=100.0)
    rows = asyncio.run(tr.tick([USER], now=T0))
    assert [(r["symbol"], r["usdg"]) for r in rows] == [("FROG", 25.0), ("SOLY", 25.0)]
    assert len(tr.view("u1")["positions"]) == 2
    b["alert_bt"][LABEL].update(ret=0.5)
    a["alert_bt"][LABEL] = {"state": "out", "ret": -0.2, "events": [{"side": "buy"}, {"side": "sell", "why": "signal"}]}
    rows = asyncio.run(tr.tick([USER], now=T0 + 60))
    assert rows[0]["side"] == "sell" and rows[0]["usdg"] == pytest.approx(20.0) and rows[0]["why"] == "system sold"
    v = tr.view("u1")
    assert v["sim"]["equity"] == pytest.approx(50 + 20 + 37.5) and v["positions"][0]["symbol"] == "SOLY"
    # no repeat entries, and at 100% one open trade takes all the cash
    assert asyncio.run(tr.tick([USER], now=T0 + 120)) == []


def test_all_cash_in_open_trades_is_said():
    _alert(sym="ONE")
    _alert(sym="TWO")
    tr.configure("u1", "sim", 100, usdg_now=10.0)
    rows = asyncio.run(tr.tick([USER], now=T0))
    assert rows[0]["ok"] and not rows[1]["ok"] and "all cash" in rows[1]["reason"]
