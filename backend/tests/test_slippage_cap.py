import asyncio

from app.trading.onchain import autotrader, sim_backtest, slippage


def test_max_size_keeps_slippage_under_limit():
    depth = slippage.depth_of(100_000)          # $50k on the stable side
    top = slippage.max_usd(depth, 1.0)
    assert round(top, 2) == 505.05
    assert abs(slippage.impact_pct(top, depth) - 1.0) < 1e-9
    assert slippage.impact_pct(3_000, depth) > 5          # the $3,000 entry Lorenzo feared


def test_depth_from_quote_inverts_impact():
    depth = 40_000
    imp = slippage.impact_pct(2_000, depth)
    assert abs(slippage.depth_from_quote(2_000, imp) - depth) < 1e-6
    assert slippage.depth_from_quote(2_000, 0.0) is None


def test_cap_unknown_liquidity_leaves_stake():
    assert slippage.cap(1_000, None) == (1_000, {})
    stake, est = slippage.cap(1_000, 100_000, 1.0)
    assert est["capped"] and round(stake, 2) == est["max_usd"] < 1_000


def test_preview_falls_back_to_pool_depth_on_evm():
    p = asyncio.run(slippage.preview("bsc", "0xabc", 3_000, 200_000, pct=1.0))
    assert p["source"] == "pool" and p["capped"] and p["size_usd"] == p["max_usd"]
    assert "size massima all'1%" in slippage.text_it(p) and "ingresso ridotto" in slippage.text_it(p)


def test_preview_uses_live_quote(monkeypatch):
    async def fake(chain, token, usd):
        return slippage.impact_pct(usd, 10_000)
    monkeypatch.setattr(slippage, "_live_impact", fake)
    p = asyncio.run(slippage.preview("solana", "Mint1", 3_000, 1e9, pct=1.0, live=True))
    assert p["source"] == "quote" and round(p["max_usd"], 0) == 101


def _tok(liq):
    return {"chain": "bsc", "token": "0x1", "symbol": "X", "interval": "1d", "liq": liq,
            "events": [{"t": 1, "side": "buy", "price": 1.0}, {"t": 2, "side": "sell", "price": 1.1, "ret": 0.1}]}


def test_replay_caps_entry_on_thin_pool():
    free = sim_backtest.replay([_tok(None)], 30_000, 0.10, max_slip_pct=1.0)
    thin = sim_backtest.replay([_tok(100_000)], 30_000, 0.10, max_slip_pct=1.0)
    assert free["closed"][0]["stake"] == 3_000 and free["capped"] == 0
    c = thin["closed"][0]
    assert thin["capped"] == 1 and c["stake"] == 505.05 and c["wanted"] == 3_000
    assert 0 < c["ret"] < 0.1 and thin["slippage_usd"] > 0


def test_sim_trend_entry_capped(monkeypatch):
    autotrader.reset_for_tests()
    monkeypatch.setattr(autotrader, "_save", lambda: None)
    autotrader._state["u"] = {**autotrader._user("u"), "mode": "sim", "pct": 10,
                              "sim_usdg": 30_000.0, "sim_start": 30_000.0}
    sig = {"side": "buy", "chain": "bsc", "token": "0x1", "symbol": "X", "price": 1.0, "interval": "1d"}
    out = autotrader.trend_signal(["u"], sig, 0, True, max_usd=500.0)
    assert out[0][1]["usdg"] == 500.0 and "capped" in out[0][1]["why"]
