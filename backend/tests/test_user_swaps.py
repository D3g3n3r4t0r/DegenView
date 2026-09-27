"""Swaps prepared for the user's own wallet (user_swaps.py): nothing signed here."""
import asyncio

import pytest

from app.trading.onchain import execution, quotes, token_metadata, user_swaps

OWNER = "0x" + "1" * 40
TOKEN = "0x" + "2" * 40


@pytest.fixture
def chain(monkeypatch):
    state = {"balance": 50_000_000, "allowance": 0}

    async def rpc(method, params):
        data = params[0]["data"]
        if data.startswith("0x70a08231"):
            return hex(state["balance"])
        if data.startswith("0xdd62ed3e"):
            return hex(state["allowance"])
        raise AssertionError(method)

    async def dec(chain, token):
        return 6

    async def pool(a, b):
        return ("0xpool", 3000)

    async def quote(a, b, fee, amount):
        return {"amount_out": amount * 10, "price_impact_pct": 0.4}
    monkeypatch.setattr(user_swaps, "_rpc", rpc)
    monkeypatch.setattr(token_metadata, "get_token_decimals", dec)
    monkeypatch.setattr(quotes, "find_pool_and_fee", pool)
    monkeypatch.setattr(quotes, "uniswap_v3_quote", quote)
    return state


def test_buy_needs_approve_then_swap_to_the_owner(chain):
    r = asyncio.run(user_swaps.build_evm(OWNER, "buy", TOKEN, 20.0, None, user_swaps.USDG, 300))
    assert [t["label"] for t in r["txs"]] == ["Allow the swap", "Swap"]
    assert r["txs"][0]["to"] == user_swaps.USDG and r["txs"][0]["data"].startswith("0x095ea7b3")
    assert r["txs"][1]["to"] == execution.ROBINHOOD_SWAP_ROUTER02
    assert r["amount_in"] == 20_000_000 and r["min_out"] == 200_000_000 * 97 // 100
    assert OWNER[2:] in r["txs"][1]["data"]          # the output goes to the user's own wallet


def test_enough_allowance_skips_approve_and_balance_is_checked(chain):
    chain["allowance"] = 10**30
    r = asyncio.run(user_swaps.build_evm(OWNER, "buy", TOKEN, 1.0, None, user_swaps.USDG, 300))
    assert [t["label"] for t in r["txs"]] == ["Swap"]
    with pytest.raises(user_swaps.SwapError, match="holds"):
        asyncio.run(user_swaps.build_evm(OWNER, "buy", TOKEN, 999.0, None, user_swaps.USDG, 300))


def test_sell_takes_the_share_of_the_token_balance(chain):
    chain["allowance"] = 10**30
    r = asyncio.run(user_swaps.build_evm(OWNER, "sell", TOKEN, None, 50, None, 300))
    assert r["amount_in"] == 25_000_000 and r["token_out"] == user_swaps.USDG
