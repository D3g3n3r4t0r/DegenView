import asyncio
import time

import pytest

from app.trading.onchain import copytrade as ct

LEADER = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
ME = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


@pytest.fixture(autouse=True)
def _store(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "STORE_FILE", tmp_path / "copytrade.json")
    monkeypatch.setattr(ct, "_store", None)
    ct._handled.clear()
    ct._mint_cache.clear()
    yield


def _tx(sol_delta: float, pre: int, post: int, *, fee=5000, err=None, owner=LEADER, wsol=0):
    pre_b, post_b = 10_000_000_000, 10_000_000_000 + int(sol_delta * 1e9) - fee
    tok = lambda amt, mint=MINT: {"accountIndex": 2, "mint": mint, "owner": owner,  # noqa: E731
                                  "uiTokenAmount": {"amount": str(amt), "decimals": 6}}
    pre_t, post_t = [tok(pre)], [tok(post)]
    if wsol:
        pre_t.append(tok(0, ct.WSOL) | {"uiTokenAmount": {"amount": "0", "decimals": 9}})
        post_t.append(tok(0, ct.WSOL) | {"uiTokenAmount": {"amount": str(int(wsol * 1e9)), "decimals": 9}})
    return {"blockTime": int(time.time()), "transaction": {"message": {"accountKeys": [{"pubkey": LEADER}, {"pubkey": "x"}]}},
            "meta": {"err": err, "fee": fee, "preBalances": [pre_b, 0], "postBalances": [post_b, 0],
                     "preTokenBalances": pre_t, "postTokenBalances": post_t}}


def test_parse_buy_ignores_the_network_fee():
    s = ct.parse_swap(_tx(-2.0, 0, 5_000_000), LEADER)
    assert s["side"] == "buy" and s["mint"] == MINT and s["units"] == 5.0
    assert s["sol"] == pytest.approx(2.0) and s["frac"] == 1.0


def test_parse_sell_share_of_the_position():
    s = ct.parse_swap(_tx(1.0, 10_000_000, 6_000_000), LEADER)
    assert s["side"] == "sell" and s["frac"] == pytest.approx(0.4)
    assert ct.parse_swap(_tx(1.0, 10_000_000, 0), LEADER)["frac"] == 1.0


def test_parse_counts_wsol_as_sol():
    s = ct.parse_swap(_tx(0.0, 10_000_000, 0, wsol=3.0), LEADER)
    assert s["side"] == "sell" and s["sol"] == pytest.approx(3.0)


def test_parse_ignores_transfers_failures_and_others():
    assert ct.parse_swap(_tx(0.0, 0, 5_000_000), LEADER) is None          # tokens in, nothing paid
    assert ct.parse_swap(_tx(0.0, 5_000_000, 0), LEADER) is None          # tokens out, nothing received
    assert ct.parse_swap(_tx(-1.0, 0, 5, err={"x": 1}), LEADER) is None
    assert ct.parse_swap(_tx(-1.0, 0, 5), ME) is None


def _q(amount, out):
    return {"in_amount": amount, "out_amount": out, "price_impact_pct": 80.0, "raw": {}}   # Jupiter's figure is ignored


def test_own_impact_not_jupiters():
    assert ct.buy_impact_pct(1_000_000_000, 900, 10_000_000, 10) == pytest.approx(10.0)
    assert ct.buy_impact_pct(1_000_000_000, 1000, 10_000_000, 10) == 0.0
    assert ct.buy_impact_pct(1, 0, 1, 1) == 100.0


def _follow(**kw):
    return {**ct.DEFAULT_FOLLOW, "address": LEADER, **kw}


def test_size_pct_fixed_and_caps():
    lim = dict(ct.DEFAULT_LIMITS)
    assert ct.size_buy(_follow(pct=10), lim, 400, 0, 0, False) == (40, "")
    assert ct.size_buy(_follow(pct=10), lim, 1000, 0, 0, False)[0] == 50             # max per trade
    assert ct.size_buy(_follow(sizing="fixed", fixed_usd=50), lim, 9999, 0, 0, False) == (50, "")
    assert ct.size_buy(_follow(sizing="fixed"), lim, 1000, 0, 0, True)[0] is None    # re-buy ignored
    assert ct.size_buy(_follow(pct=10), lim, 400, 0, 0, True)[0] == 40               # re-buy at pct copied
    assert ct.size_buy(_follow(pct=10), lim, 20, 0, 0, False)[0] is None             # $2 < minimum
    assert ct.size_buy(_follow(pct=10), lim, 1000, 460, 0, False)[0] is None         # daily cap
    assert ct.size_buy(_follow(pct=10), lim, 1000, 0, 10, False)[0] is None          # max open


def test_old_default_cap_moves_to_50_unless_chosen():
    ct._load()["users"] = {"a": {"limits": {"max_trade_usd": 100.0, "max_day_usd": 500.0, "max_open": 10}},
                           "b": {"limits": {"max_trade_usd": 100.0, "max_day_usd": 500.0, "max_open": 10},
                                 "limits_set_at": 1.0}}
    assert ct.DEFAULT_LIMITS == {"max_trade_usd": 50.0, "max_day_usd": 500.0, "max_open": 10}
    assert ct.account("a")["limits"]["max_trade_usd"] == 50.0
    assert ct.account("b")["limits"]["max_trade_usd"] == 100.0
    ct.set_limits("a", {"max_trade_usd": 100})
    assert ct.account("a")["limits"]["max_trade_usd"] == 100.0


def test_follow_validation_and_real_consent():
    with pytest.raises(ValueError):
        ct.set_follow("u1", "not-an-address", {})
    with pytest.raises(ValueError):
        ct.set_follow("u1", LEADER, {"mode": "real"})
    ct.set_real_ok("u1", True)
    assert ct.set_follow("u1", LEADER, {"mode": "real"})["mode"] == "real"
    ct.set_real_ok("u1", False)
    assert ct.account("u1")["follows"][LEADER]["mode"] == "sim"
    assert ct.watched() == {LEADER: ["u1"]}


def test_simulated_copy_in_and_out(monkeypatch):
    ct.set_follow("u1", LEADER, {"mode": "sim", "copy": "both", "sizing": "fixed", "fixed_usd": 50})
    txs = {"buy": _tx(-10.0, 0, 1_000_000_000), "sell": _tx(5.0, 1_000_000_000, 500_000_000)}

    async def rpc(method, params):
        if method == "getTransaction":
            return txs[params[0]]
        if method == "getAccountInfo":
            return {"value": {"data": {"parsed": {"info": {"mintAuthority": None, "freezeAuthority": None}}}}}
        raise AssertionError(method)

    async def quote(i, o, amount, slip):
        if i == ct.WSOL:       # buy: $50 at 100 $/SOL = 0.5 SOL -> 52 tokens (his price 1.0, ours ~0.96)
            return _q(amount, amount * 52_000_000 // 500_000_000)
        return _q(amount, int(amount / 1e6 * 1.5 / 100 * 1e9))

    async def price():
        return 100.0
    monkeypatch.setattr(ct, "rpc", rpc)
    monkeypatch.setattr(ct.quotes, "jupiter_quote", quote)
    monkeypatch.setattr(ct, "sol_price", price)

    asyncio.run(ct.handle_signature(LEADER, "buy"))
    acc = ct.account("u1")
    assert acc["trades"][0]["status"] == "sim" and acc["trades"][0]["usd"] == 50
    pos = acc["positions"][LEADER][MINT]
    assert pos["qty"] == pytest.approx(52.0) and pos["cost_usd"] == 50

    asyncio.run(ct.handle_signature(LEADER, "sell"))       # he sells half: we sell half
    row = acc["trades"][0]
    assert row["status"] == "sim" and row["frac"] == 0.5
    assert row["usd"] == pytest.approx(39.0) and row["pnl_usd"] == pytest.approx(14.0)
    assert acc["trades"][1]["impact_pct"] == 0.0
    assert acc["positions"][LEADER][MINT]["qty"] == pytest.approx(26.0)

    asyncio.run(ct.handle_signature(LEADER, "sell"))       # same signature twice: once only
    assert len(acc["trades"]) == 2


def test_chase_and_freeze_authority_skip(monkeypatch):
    ct.set_follow("u1", LEADER, {"mode": "sim", "pct": 10})
    frozen = {"v": "Freeze1111"}

    async def rpc(method, params):
        if method == "getTransaction":
            return _tx(-10.0, 0, 1_000_000_000)
        return {"value": {"data": {"parsed": {"info": {"freezeAuthority": frozen["v"]}}}}}

    async def quote(i, o, amount, slip):     # $100 buys 50 tokens: twice his price
        return _q(amount, amount * 50_000_000 // 1_000_000_000 if i == ct.WSOL else amount * 20)

    async def price():
        return 100.0
    monkeypatch.setattr(ct, "rpc", rpc)
    monkeypatch.setattr(ct.quotes, "jupiter_quote", quote)
    monkeypatch.setattr(ct, "sol_price", price)
    asyncio.run(ct.handle_signature(LEADER, "a"))
    assert "freeze" in ct.account("u1")["trades"][0]["reason"]
    frozen["v"] = None
    ct._mint_cache.clear()
    asyncio.run(ct.handle_signature(LEADER, "b"))
    t = ct.account("u1")["trades"][0]
    assert t["status"] == "skipped" and "above his" in t["reason"]
    assert not ct.account("u1")["positions"]


def test_real_mode_waits_for_the_server_switch(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "onchain_execution_enabled", False)
    ct.set_real_ok("u1", True)
    ct.set_follow("u1", LEADER, {"mode": "real", "sizing": "fixed", "fixed_usd": 50})

    async def rpc(method, params):
        if method == "getTransaction":
            return _tx(-10.0, 0, 1_000_000_000)
        return {"value": {"data": {"parsed": {"info": {}}}}}

    async def quote(i, o, amount, slip):
        return _q(amount, amount * 52_000_000 // 500_000_000 if i == ct.WSOL else amount * 10)

    async def price():
        return 100.0
    monkeypatch.setattr(ct, "rpc", rpc)
    monkeypatch.setattr(ct.quotes, "jupiter_quote", quote)
    monkeypatch.setattr(ct, "sol_price", price)
    asyncio.run(ct.handle_signature(LEADER, "r"))
    t = ct.account("u1")["trades"][0]
    assert t["status"] == "skipped" and "server" in t["reason"]
    assert not ct.account("u1")["positions"]
