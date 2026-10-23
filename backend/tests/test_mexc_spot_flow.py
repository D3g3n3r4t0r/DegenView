"""MEXC spot end to end, against a fake MEXC that behaves like the real one.

Real money on the site runs on MEXC only (asked on 23/10: "per il trading con
denaro reale [...] utilizzeremo solo Mexc [...] verificare che sia tutto ok
(chiavi, operazioni, ingressi, uscite, percentuale di portafoglio)"). MEXC
has no testnet, so this fake checks what the real exchange checks:
- the key header and the HMAC-SHA256 signature of the query string;
- the pair rules read from the real exchangeInfo on 23/10: quantity
  decimals (BTC 8, KAS 2, PEPE 0) and the 1 USDT minimum;
- balances: a buy costs quantity x fill price (a tick above the ticker) and
  the 0.05% fee comes out of the coins received; a sell above the free
  balance is "Oversold".
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import urllib.parse

import httpx
import pytest

from app import main
from app.models import StrategySignal
from app.trading import binance_exec, executor, spot_positions

KEY, SECRET = "mx0vglTESTKEY", "TESTSECRET123"
RULES = {"BTCUSDT": 8, "KASUSDT": 2, "PEPEUSDT": 0}
FEE = 0.0005
SLIP = 1.003          # the market fill is 0.3% above the last trade


class FakeMexc:
    def __init__(self, usdt=1000.0, prices=None, coins=None):
        self.free = {"USDT": usdt, **(coins or {})}
        self.price = dict(prices or {"BTCUSDT": 60000.0, "KASUSDT": 0.0812, "PEPEUSDT": 0.000005079})
        self.orders: list[dict] = []

    def _err(self, code, msg):
        return httpx.Response(400, json={"code": code, "msg": msg})

    def _signed(self, request):
        if request.headers.get("X-MEXC-APIKEY") != KEY:
            return self._err(10072, "Api key info invalid")
        raw = request.url.query.decode()
        body, _, sig = raw.rpartition("&signature=")
        want = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if sig != want:
            return self._err(700002, "Signature for this request is not valid.")
        params = dict(urllib.parse.parse_qsl(body))
        if abs(int(params["timestamp"]) - time.time() * 1000) > 60_000:
            return self._err(700003, "Timestamp for this request is outside of the recvWindow.")
        return params

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, q = request.url.path, dict(urllib.parse.parse_qsl(request.url.query.decode()))
        if path == "/api/v3/exchangeInfo":
            sym = q["symbol"]
            if sym not in RULES:
                return self._err(-1121, "Invalid symbol.")
            return httpx.Response(200, json={"symbols": [{
                "symbol": sym, "status": "1", "isSpotTradingAllowed": True, "baseAssetPrecision": RULES[sym],
                "quoteAmountPrecision": "1", "quoteAmountPrecisionMarket": "1", "takerCommission": str(FEE)}]})
        if path == "/api/v3/ticker/price":
            return httpx.Response(200, json={"symbol": q["symbol"], "price": str(self.price[q["symbol"]])})
        params = self._signed(request)
        if isinstance(params, httpx.Response):
            return params
        if path == "/api/v3/account" and request.method == "GET":
            return httpx.Response(200, json={"balances": [{"asset": a, "free": str(v), "locked": "0"}
                                                          for a, v in self.free.items()]})
        if path == "/api/v3/order" and request.method == "POST":
            return self._order(params)
        return httpx.Response(404, json={"msg": "not found"})

    def _order(self, p):
        sym, side = p["symbol"], p["side"]
        base = sym[:-4]
        if p.get("type") != "MARKET" or "quantity" not in p:
            return self._err(700004, "Mandatory parameter 'quantity' was not sent")
        text = p["quantity"]
        if "." in text and len(text.split(".")[1]) > RULES[sym]:
            return self._err(400, "quantity scale is invalid")
        qty = float(text)
        fill = self.price[sym] * (SLIP if side == "BUY" else 1 / SLIP)
        if qty * self.price[sym] < 1:
            return self._err(30002, "Minimum transaction volume cannot be less than :1USDT")
        if side == "BUY":
            cost = qty * fill
            if cost > self.free.get("USDT", 0) + 1e-9:
                return self._err(30004, "Insufficient position")
            self.free["USDT"] -= cost
            self.free[base] = self.free.get(base, 0) + qty * (1 - FEE)
        else:
            if qty > self.free.get(base, 0) + 1e-12:
                return self._err(30005, "Oversold")
            self.free[base] -= qty
            self.free["USDT"] += qty * fill * (1 - FEE)
        self.orders.append({"side": side, "symbol": sym, "qty": qty})
        return httpx.Response(200, json={"symbol": sym, "orderId": f"C02__{len(self.orders)}", "price": "0",
                                         "origQty": text, "type": "MARKET", "side": side,
                                         "transactTime": int(time.time() * 1000)})


@pytest.fixture
def mexc(monkeypatch, tmp_path):
    fake = FakeMexc()
    real = httpx.AsyncClient

    def make(**kw):
        kw["transport"] = httpx.MockTransport(fake)
        return real(**kw)
    monkeypatch.setattr(binance_exec.httpx, "AsyncClient", make)
    binance_exec._rules_cache.clear()
    monkeypatch.setattr(spot_positions, "_STORE_FILE", tmp_path / "spot_positions.json")
    monkeypatch.setattr(spot_positions, "_store", None)
    monkeypatch.setattr(executor, "check_halt", lambda: (True, ""))
    monkeypatch.setattr(executor, "check_exchange", lambda ex: (True, ""))
    return fake


def order(side, symbol, mode, value, key=KEY, secret=SECRET, cap=None):
    return asyncio.run(binance_exec.place_order("mexc", symbol, side, mode, value, key, secret, max_usdt=cap))


def test_a_wrong_key_or_secret_is_refused_with_a_hint(mexc):
    with pytest.raises(RuntimeError, match="invalid key for this exchange"):
        order("BUY", "BTCUSDT", "fixed_usdt", 10, key="other")
    with pytest.raises(RuntimeError, match="secret does not match"):
        order("BUY", "BTCUSDT", "fixed_usdt", 10, secret="wrong")
    assert not mexc.orders


@pytest.mark.parametrize("symbol", ["BTCUSDT", "KASUSDT", "PEPEUSDT"])
def test_a_fixed_buy_respects_each_pairs_decimals(mexc, symbol):
    order("BUY", symbol, "fixed_usdt", 10)
    got = mexc.orders[-1]["qty"] * mexc.price[symbol]
    assert 9.9 < got <= 10.0                         # ~10 USDT, never more
    assert mexc.free["USDT"] == pytest.approx(1000 - got * SLIP)


def test_a_percentage_buy_spends_that_share_of_the_free_usdt(mexc):
    order("BUY", "KASUSDT", "pct_balance", 25)
    spent = 1000 - mexc.free["USDT"]
    assert 245 < spent < 250.5


def test_all_in_survives_a_fill_above_the_ticker(mexc):
    order("BUY", "KASUSDT", "pct_balance", 100)     # without the margin: Insufficient position
    assert 0 <= mexc.free["USDT"] < 5


def test_selling_everything_never_asks_for_more_than_there_is(mexc):
    mexc.free["KAS"] = 1234.5678                     # more decimals than KAS allows
    order("SELL", "KASUSDT", "pct_balance", 100)
    assert mexc.orders[-1]["qty"] == 1234.56 and mexc.free["KAS"] == pytest.approx(0.0078)


def test_below_the_minimum_nothing_is_sent(mexc):
    with pytest.raises(RuntimeError, match="below the minimum order of 1 USDT"):
        order("BUY", "KASUSDT", "fixed_usdt", 0.5)
    with pytest.raises(RuntimeError, match="below the minimum"):
        order("BUY", "KASUSDT", "pct_balance", 0.05)
    assert not mexc.orders


def test_an_unknown_pair_is_named(mexc):
    with pytest.raises(RuntimeError, match="does not exist on this exchange"):
        order("BUY", "NOPEUSDT", "fixed_usdt", 10)


def test_the_cap_per_strategy_limits_a_percentage_entry(mexc):
    order("BUY", "KASUSDT", "pct_balance", 50, cap=40)
    assert 1000 - mexc.free["USDT"] < 40.2


# ── the bot: entry, exit, coins already on the account ─────────────────────

class _Entry:
    exchange, symbol = "mexc", "KASUSDT"


class _Cred:
    def __init__(self, mode, value):
        self.size_mode, self.size_value = mode, value


class _Owner:
    id = "u1"


def bot(fake, signal_type, cred):
    sig = StrategySignal(time=1, type=signal_type, price=fake.price["KASUSDT"], label="x")
    mode, value = main._spot_bot_size(_Owner, _Entry, "Lorenzo", sig, cred)
    if mode is None:
        return {"skipped": True, "reason": value}
    result = asyncio.run(executor.place_order_for_signal("mexc", "KASUSDT", sig, mode, value, KEY, SECRET))
    main._spot_bot_filled(_Owner, _Entry, "Lorenzo", sig, result)
    return result


@pytest.mark.parametrize("cred", [_Cred("fixed_usdt", 50), _Cred("pct_balance", 10)])
def test_the_bot_exits_exactly_what_it_bought(mexc, cred):
    mexc.free["KAS"] = 5000.0                        # coins held before: never touched
    bot(mexc, "entry_long", cred)
    bought = spot_positions.held("u1", "mexc", "KASUSDT", "Lorenzo")
    assert bought > 0 and mexc.free["KAS"] == pytest.approx(5000 + bought)     # net of the fee
    mexc.price["KASUSDT"] *= 1.3                     # the coin rose 30%
    bot(mexc, "exit_long", cred)
    sold = mexc.orders[-1]["qty"]
    assert mexc.orders[-1]["side"] == "SELL"
    assert sold == pytest.approx(bought, abs=0.01)                # all of it
    assert mexc.free["KAS"] == pytest.approx(5000, abs=0.01)      # the old coins stay
    assert spot_positions.held("u1", "mexc", "KASUSDT", "Lorenzo") == 0


def test_an_exit_with_nothing_bought_sells_nothing(mexc):
    mexc.free["KAS"] = 5000.0
    r = bot(mexc, "exit_long", _Cred("fixed_usdt", 50))
    assert r["skipped"] and "Sell all" in r["reason"]
    r = bot(mexc, "entry_short", _Cred("fixed_usdt", 50))       # on spot: back to cash
    assert r["skipped"] and r["reason"] == main._NOTHING_HELD
    assert not mexc.orders and mexc.free["KAS"] == 5000.0


def test_a_short_signal_on_spot_closes_the_long(mexc):
    bot(mexc, "entry_long", _Cred("fixed_usdt", 50))
    bot(mexc, "flip_to_short", _Cred("fixed_usdt", 50))
    assert [o["side"] for o in mexc.orders] == ["BUY", "SELL"]
    assert mexc.free["KAS"] == pytest.approx(0, abs=0.01)


def test_sell_all_by_hand_forgets_the_bots_record(mexc):
    bot(mexc, "entry_long", _Cred("fixed_usdt", 50))
    spot_positions.closed_by_hand("u1", "mexc", "KASUSDT")
    assert spot_positions.held("u1", "mexc", "KASUSDT", "Lorenzo") == 0
