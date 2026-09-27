"""Scanning one token by hand (manual_scan.py)."""
from app.trading.onchain import manual_scan as ms


def _pair(chain, sym, addr, liq):
    return {"chainId": chain, "baseToken": {"symbol": sym, "address": addr, "name": sym}, "liquidity": {"usd": liq},
            "pairAddress": "p" + addr, "marketCap": 1e6}


def test_pick_prefers_the_exact_match_then_liquidity_on_our_chains():
    pairs = [_pair("solana", "PEPE", "A1", 5_000), _pair("solana", "PEPE", "A2", 90_000),
             _pair("arbitrum", "PEPE", "A3", 9e9), _pair("base", "PEPEX", "A4", 1e6)]
    assert ms.pick(pairs, "$pepe")["baseToken"]["address"] == "A2"
    addr = "0x" + "ab" * 20
    pairs.append(_pair("bsc", "ZZZ", addr, 10))
    assert ms.pick(pairs, addr.upper().replace("0X", "0x"))["chainId"] == "bsc"
    assert ms.pick([_pair("arbitrum", "X", "a", 1)], "X") is None


def test_item_has_what_the_checks_need():
    it = ms.item_of({**_pair("solana", "CAT", "C1", 20_000), "url": "u", "pairCreatedAt": 1_700_000_000_000})
    assert it["chain"] == "solana" and it["token_address"] == "C1" and it["liquidity_usd"] == 20_000
    assert it["created_at"] == 1_700_000_000
