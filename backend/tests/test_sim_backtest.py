from app.trading.onchain import sim_backtest as sb


def _tok(sym, events, interval="1d"):
    return {"chain": "solana", "token": sym, "symbol": sym, "interval": interval, "events": events}


def test_trades_share_one_wallet_in_time_order():
    a = _tok("A", [{"t": 100, "side": "buy", "price": 1.0}, {"t": 300, "side": "sell", "price": 2.0, "ret": 1.0}])
    b = _tok("B", [{"t": 200, "side": "buy", "price": 1.0}, {"t": 400, "side": "sell", "price": 0.5, "ret": -0.5}])
    r = sb.replay([a, b], 10_000, 0.10)
    # A: 1000 -> 2000. B: 10% of 10000 (A at cost) = 1000 -> 500.
    assert r["equity"] == 10_500 and r["ret"] == 0.05
    assert r["trades"] == 2 and r["wins"] == 1 and not r["open"]
    assert [c["symbol"] for c in r["closed"]] == ["B", "A"]


def test_open_trade_marked_at_live_price_or_cost():
    a = _tok("A", [{"t": 100, "side": "buy", "price": 2.0}])
    r = sb.replay([a], 10_000, 0.10, marks={"solana:A": 3.0}, now=500)
    assert r["open"][0]["ret"] == 0.5 and r["equity"] == 10_500 and r["curve"][-1] == [500, 10_500]
    r = sb.replay([a], 10_000, 0.10)
    assert r["open"][0]["ret"] is None and r["equity"] == 10_000


def test_never_spends_more_than_free_cash():
    toks = [_tok(str(i), [{"t": 100 + i, "side": "buy", "price": 1.0}]) for i in range(12)]
    r = sb.replay(toks, 1000, 0.5)
    assert r["cash"] >= 0 and r["skipped"] > 0


def test_token_trades_follows_the_top_row():
    daily = {"interval": "8h", "rows": [{"trades": 2}], "best": {"events": [{"t": 1, "side": "buy"}]}}
    assert sb.token_trades({"daily": daily})[0] == "8h"
    no_daily = {"daily": {"rows": [{"trades": 0}]}, "best": {"events": [{"t": 1, "side": "buy"}]}}
    assert sb.token_trades(no_daily)[0] == "5m"
    assert sb.token_trades(None) is None


def test_ledger_keeps_trades_the_window_slid_past(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "_FILE", tmp_path / "l.json")
    sb.reset_for_tests()
    first = {"best": {"events": [{"t": 100, "side": "buy", "price": 1.0},
                                 {"t": 200, "side": "sell", "price": 2.0, "ret": 1.0}]}}
    later = {"best": {"events": [{"t": 300, "side": "buy", "price": 2.0}]}}
    assert sb.remember("solana", "A", "A", first) and sb.remember("solana", "A", "A", later)
    assert not sb.remember("solana", "A", "A", later)
    sb.reset_for_tests()
    monkeypatch.setattr(sb, "_loaded", False)
    toks = sb.ledger_tokens()
    assert [e["t"] for e in toks[0]["events"]] == [100, 200, 300]
    r = sb.replay(toks, 10_000, 0.10)
    assert r["trades"] == 1 and len(r["open"]) == 1
