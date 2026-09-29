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


def test_memory_labels_are_english_and_ai_drops_its_own_memory_counts():
    assert ms.english("5 similar: 1 rug, after 13.2h, 4 buono, 1 finto") == \
        "5 similar: 1 rug, after 13.2h, 4 fine, 1 fake volume"
    ai = ms.clean_flags({"risk": 78, "flags": ["defi impersonation", "4/5 similar rugged", "no github"]})
    assert ai["flags"] == ["defi impersonation", "no github"]
    assert ms.clean_flags(None) is None


def test_backtest_view_keeps_the_best_fast_strategy_and_the_daily_trend():
    r = {"at": 1, "backtests": {"hold_pct": 40.0, "rows": [
        {"label": "Trend EMA", "return_pct": 12.0, "trades": 3, "win_rate": 66.0, "max_dd": 5.0},
        {"label": "Trend HF", "return_pct": 30.0, "trades": 9, "win_rate": 55.0, "max_dd": 8.0},
        {"label": "RSI+BB", "return_pct": None, "trades": 0}]},
        "daily": {"interval": "1d", "hold_pct": 90.0, "rows": [
            {"label": "Trend EMA", "return_pct": 120.0, "trades": 4, "win_rate": 75.0, "max_dd": 20.0}]}}
    v = ms.backtest_view(r)
    assert v["fast"]["label"] == "Trend HF" and v["fast"]["hold_pct"] == 40.0
    assert v["daily"]["return_pct"] == 120.0 and v["daily"]["interval"] == "1d"
    assert ms.backtest_view(None) is None
    assert ms.backtest_view({"backtests": {"rows": []}}) is None


def test_an_unknown_project_is_queued_for_the_gem_finder(tmp_path, monkeypatch):
    from app.trading.onchain import leaderboard, projects_db
    monkeypatch.setattr(projects_db, "get", lambda c, t: None)
    seen = []
    monkeypatch.setattr(projects_db, "upsert", lambda item, src, now=None: seen.append((item["token_address"], src)))
    monkeypatch.setattr(leaderboard, "_entries", {})
    v = ms.gem_view({"chain": "robinhood", "token_address": "0xabc", "symbol": "HYDX"})
    assert v["status"] == "queued" and seen == [("0xabc", "manual")]
