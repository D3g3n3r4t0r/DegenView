"""
L'ordine reale su MEXC non partiva: chiave presente, exchange che rispondeva
"api key required".

MEXC espone la stessa API v3 di Binance — stessi percorsi, stessa firma, stessi
parametri — tranne l'intestazione con cui si presenta la chiave. L'esecutore
era condiviso fra i due, e condivideva anche quella: a MEXC arrivava
X-MBX-APIKEY, che per lui non esiste. Da qui "la chiave manca", che era vero
dal suo punto di vista.

Il modulo dei saldi ha sempre usato X-MEXC-APIKEY, ed e' per questo che i saldi
si vedevano mentre gli ordini no: due percorsi diversi verso lo stesso account,
uno solo autenticato.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.trading import binance_exec


def _client_with(handler):
    """Sostituisce il trasporto, non il codice: intestazioni, firma e percorso
    restano quelli veri, e sono proprio quelli che il test guarda."""
    real = httpx.AsyncClient

    def make(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(**kwargs)

    return make


@pytest.fixture
def captured(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"orderId": 1, "status": "FILLED"})

    monkeypatch.setattr(binance_exec.httpx, "AsyncClient", _client_with(handler))
    return seen


def test_mexc_gets_its_own_api_key_header(captured):
    asyncio.run(binance_exec.place_order("mexc", "BTCUSDT", "BUY", "fixed_usdt", 50.0, "k", "s"))
    req = captured[-1]
    assert req.headers.get("X-MEXC-APIKEY") == "k"
    assert "X-MBX-APIKEY" not in req.headers, "l'intestazione di Binance non deve arrivare a MEXC"
    assert "api.mexc.com" in str(req.url)


def test_binance_keeps_its_own(captured):
    asyncio.run(binance_exec.place_order("binance", "BTCUSDT", "BUY", "fixed_usdt", 50.0, "k", "s"))
    req = captured[-1]
    assert req.headers.get("X-MBX-APIKEY") == "k"
    assert "X-MEXC-APIKEY" not in req.headers


def test_the_order_is_signed_and_market(captured):
    asyncio.run(binance_exec.place_order("mexc", "BTCUSDT", "BUY", "fixed_usdt", 50.0, "k", "s"))
    url = str(captured[-1].url)
    assert "signature=" in url and "timestamp=" in url
    assert "type=MARKET" in url and "quoteOrderQty=50" in url


def test_an_unknown_exchange_is_refused_instead_of_treated_as_mexc(monkeypatch):
    with pytest.raises(RuntimeError, match="non gestito"):
        asyncio.run(binance_exec.place_order("kraken", "BTCUSDT", "BUY", "fixed_usdt", 50.0, "k", "s"))


def test_the_exchange_error_carries_what_to_do_about_it(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": 400, "msg": "api key required"})

    monkeypatch.setattr(binance_exec.httpx, "AsyncClient", _client_with(handler))
    with pytest.raises(RuntimeError) as err:
        asyncio.run(binance_exec.place_order("mexc", "BTCUSDT", "BUY", "fixed_usdt", 50.0, "k", "s"))
    message = str(err.value)
    assert "api key required" in message          # il testo dell'exchange resta
    assert "non e' arrivata all'exchange" in message   # piu' cosa significa


def test_the_hint_table_does_not_match_words_by_accident():
    # "ip" dentro "description" farebbe scattare il suggerimento sbagliato.
    innocuous = binance_exec._explain("mexc", "order", "Order description: filled")
    assert "indirizzo del server" not in str(innocuous)
