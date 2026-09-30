import pytest

from app.trading.onchain import autotrader


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(autotrader, "_save", lambda: None)
    autotrader.reset_for_tests()
    yield
    autotrader.reset_for_tests()


def test_sim_cash_starts_a_simulation_when_there_is_none():
    v = autotrader.configure("u", sim_cash=500)
    assert v["sim"]["usdg"] == 500 and v["sim"]["start"] == 500 and v["sim"]["ret"] == 0


def test_sim_cash_moves_the_start_like_a_deposit():
    autotrader.configure("u", mode="sim", usdg_now=100)
    u = autotrader._user("u")
    u["sim_usdg"] = 120.0  # +20% on a closed trade
    v = autotrader.configure("u", sim_cash=1000)
    assert v["sim"]["usdg"] == 1000
    assert v["sim"]["start"] == pytest.approx(980)
    assert v["mode"] == "sim"


def test_sim_cash_keeps_open_paper_trades_and_leaves_real_mode_alone():
    autotrader.configure("u", mode="sim", usdg_now=100)
    u = autotrader._user("u")
    u["paper"].append({"alert": "a", "symbol": "X", "token": "t", "chain": "solana", "at": 0, "stake": 50.0, "ret": 0.0})
    u["sim_usdg"] = 50.0
    autotrader.configure("u", sim_cash=0)
    assert u["sim_usdg"] == 0 and len(u["paper"]) == 1 and u["sim_start"] == pytest.approx(50)


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), 1e12])
def test_sim_cash_rejects_nonsense(bad):
    with pytest.raises(ValueError):
        autotrader.configure("u", sim_cash=bad)


def _buy(price=1.0, side="buy", token="T"):
    return {"chain": "solana", "token": token, "symbol": "GEM", "pair": "P", "interval": "8h",
            "side": side, "t": 0, "price": price}


def test_trend_signal_opens_and_closes_a_simulated_trade():
    autotrader.configure("u", mode="sim", usdg_now=100)
    autotrader.configure("u", pct=50)
    rows = autotrader.trend_signal(["u"], _buy(2.0), 10, gem_ok=True)
    assert rows[0][1]["ok"] and rows[0][1]["usdg"] == 50
    autotrader.trend_marks({"solana:T": 3.0})
    v = autotrader.view("u")
    assert v["sim"]["equity"] == pytest.approx(125) and v["positions"][0]["route"] == "trend 8h"
    rows = autotrader.trend_signal(["u"], _buy(4.0, "sell"), 20, gem_ok=False)
    assert rows[0][1]["ret"] == pytest.approx(1.0)
    assert autotrader._user("u")["sim_usdg"] == pytest.approx(150) and not autotrader._user("u")["trend"]


def test_trend_signal_skips_non_gems_off_mode_and_repeats():
    autotrader.configure("u", mode="sim", usdg_now=100)
    assert autotrader.trend_signal(["u"], _buy(), 1, gem_ok=False) == []
    assert len(autotrader.trend_signal(["u"], _buy(), 1, gem_ok=True)) == 1
    assert autotrader.trend_signal(["u"], _buy(), 2, gem_ok=True) == []   # already held
    autotrader.configure("u", mode="off")
    assert autotrader.trend_signal(["u"], _buy(token="Z"), 3, gem_ok=True) == []
