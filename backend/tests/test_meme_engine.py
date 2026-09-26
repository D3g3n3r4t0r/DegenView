"""The Meme Sniper's engine: a score with reasons and a trade that could
really have been made. Request: "dobbiamo rendere tutto piu' professionale"."""
from __future__ import annotations

import pytest

from app.trading.onchain import meme_engine as me
from app.trading.onchain import outcomes

T0 = 1_790_000_000.0
H = 3600.0
ORGANIC = {"buys_h1": 90.0, "sells_h1": 45.0, "buy_ratio": 90 / 135, "vol_h1": 13_500.0,
           "chg_h1": 18.0, "chg_h6": 60.0, "mcap": 400_000.0}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(outcomes, "_STORE_FILE", tmp_path / "outcomes.json")
    outcomes.reset_for_tests()
    yield
    outcomes.reset_for_tests()


def test_organic_flow_beats_bot_flow_and_says_why():
    good = me.score(ORGANIC, 50_000, 400_000, {"top_holder_pct": 3.0})
    bots = me.score({**ORGANIC, "buys_h1": 300.0, "sells_h1": 0.0, "buy_ratio": 1.0, "vol_h1": 600.0},
                    50_000, 400_000, {"top_holder_pct": 3.0})
    assert good["score"] > 80 > 40 > bots["score"]
    assert any("two-way flow" in r for r in good["reasons"])
    assert any("one-way flow" in r for r in bots["risks"])
    assert any("bot activity" in r for r in bots["risks"])


def test_parabolic_wash_and_whales_are_risks():
    late = me.score({**ORGANIC, "chg_h1": 450.0}, 50_000, 400_000)
    wash = me.score({**ORGANIC, "vol_h1": 500_000.0}, 50_000, 400_000)
    whale = me.score(ORGANIC, 50_000, 400_000, {"top_holder_pct": 14.0})
    base = me.score(ORGANIC, 50_000, 400_000)
    assert late["score"] < base["score"] and "late" in " ".join(late["risks"])
    assert wash["score"] < base["score"] and "wash" in " ".join(wash["risks"])
    assert whale["score"] < base["score"]


def test_rugcheck_warnings_cost_points():
    clean = me.score(ORGANIC, 50_000, 400_000, {"top_holder_pct": 3.0, "warnings": []})
    dirty = me.score(ORGANIC, 50_000, 400_000,
                     {"top_holder_pct": 3.0, "warnings": ["Creator history of rugged tokens", "Bundled buys"]})
    assert clean["score"] - dirty["score"] == pytest.approx(30)
    assert "creator has rugged before" in dirty["risks"] and "bundled launch" in dirty["risks"]


def test_trade_pays_costs_both_ways_and_takes_profit_at_the_target():
    t = me.open_trade(20_000, T0)
    assert t["cost_in"] == pytest.approx(0.003 + 0.01)
    me.step_trade(t, 0.2, 20_000, T0 + H, can_sell=True)
    assert t["open"]
    me.step_trade(t, 0.9, 20_000, T0 + 2 * H, can_sell=True)
    assert t["exit"] == "target" and t["gross"] == 0.5
    assert t["ret"] == pytest.approx(1.5 * 0.987 * 0.987 - 1, abs=1e-4)
    assert me.won(t) is True


def test_stop_fills_at_the_sample_not_at_the_stop():
    t = me.open_trade(50_000, T0)
    me.step_trade(t, -0.55, 50_000, T0 + H, can_sell=True)
    assert t["exit"] == "stop" and t["gross"] == -0.55 and t["ret"] < -0.55


def test_unsellable_pump_is_a_total_loss_and_rug_closes_the_trade():
    t = me.open_trade(20_000, T0)
    me.step_trade(t, 3.0, 20_000, T0 + H, can_sell=False)
    assert t["open"]
    me.step_trade(t, 3.0, 20_000, T0 + 7 * 24 * H, can_sell=False, final=True)
    assert t["exit"] == "stuck" and t["ret"] == -1.0
    r = me.open_trade(20_000, T0)
    me.step_trade(r, None, None, T0 + H, can_sell=False, rug=True)
    assert r["exit"] == "rug" and r["ret"] == -1.0


def _seen(token, market, prices, *, liq=40_000.0):
    item = {"chain": "solana", "symbol": token.upper(), "name": token, "token_address": token,
            "pair_address": f"P{token}", "market_cap": 300_000, "liquidity_usd": liq, "age_hours": 6,
            "checks": [{"key": "name", "ok": False}]}
    e = outcomes.observe(item, "rejected", T0, "nome da meme coin", "radar", now=T0)
    for i, p in enumerate(prices):
        outcomes.apply_sample(e, p, liq, T0 + i * 600, market)
    return e


def test_journal_runs_the_trade_and_the_lane_shows_reasons_and_track():
    good = {**ORGANIC, "sells_h24": 200.0}
    _seen("frog", good, [1.0, 1.1, 1.6])
    _seen("dud", good, [1.0, 0.95, 0.6])
    _seen("live", good, [1.0, 1.05])
    assert outcomes._journal["solana:frog"]["trade"]["exit"] == "target"
    assert outcomes._journal["solana:dud"]["trade"]["exit"] == "stop"
    board = outcomes.meme_board(T0 + 1200)
    live = next(i for i in board["items"] if i["symbol"] == "LIVE")
    assert live["reasons"] and live["band"] and 0 <= live["score"] <= 100
    assert board["track"]["baseline"]["n"] == 2
    assert outcomes.mark_shown(T0 + 1200) == 3          # what the lane shows, from now
    assert outcomes.mark_shown(T0 + 1300) == 0
    assert outcomes._journal["solana:live"]["shown"]["price"] == 1.05
    outcomes.apply_sample(outcomes._journal["solana:live"], 1.05 * 1.6, 40_000, T0 + 1800, good)
    track = outcomes.meme_track(T0 + 1800)
    assert track["shown"]["n"] == 1 and track["shown"]["win_rate"] == 1.0
    assert track["exits"] == {"target": 1}
