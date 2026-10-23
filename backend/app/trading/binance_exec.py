import hashlib
import hmac
import math
import time
import urllib.parse

import httpx

BINANCE_BASE = "https://api.binance.com"
MEXC_BASE = "https://api.mexc.com"

# MEXC espone la stessa API v3 di Binance — stessi percorsi, stessa firma
# HMAC, stessi nomi dei parametri — tranne l'intestazione con cui si presenta
# la chiave. Mandare a MEXC quella di Binance produce
# {"code":400,"msg":"api key required"}: la chiave c'era, ma nella busta
# sbagliata, e il messaggio dell'exchange dice "manca" perche' dal suo punto di
# vista mancava davvero. Il modulo dei saldi usa da sempre l'intestazione
# giusta, ed e' per questo che i saldi si vedevano mentre gli ordini no.
_API_KEY_HEADER = {
    "binance": "X-MBX-APIKEY",
    "mexc": "X-MEXC-APIKEY",
}

# Gli errori piu' comuni dei due exchange, tradotti in cosa fare. Il testo
# grezzo resta comunque nel messaggio: e' quello che serve per capire il caso
# che qui non e' previsto.
_HINTS = {
    "api key required": "the key never reached the exchange",
    "signature for this request is not valid": "the secret does not match the key",
    "invalid api key": "invalid key, or not enabled for spot trading",
    "api key info invalid": "invalid key for this exchange",
    "invalid symbol": "this pair does not exist on this exchange",
    "oversold": "insufficient balance for the requested amount",
    "insufficient position": "insufficient balance for the requested amount",
    "not authorized": "the key lacks order permission (spot trading)",
    # Non "ip" e basta: comparirebbe dentro parole qualunque del messaggio.
    "ip white": "the server IP is not whitelisted for this key",
    "ip address": "the server IP is not whitelisted for this key",
    # MEXC risponde cosi' quando la chiave puo' fare ordini ma non puo'
    # leggere il saldo — succede solo con "% saldo" (che deve leggerlo prima
    # di calcolare quanto ordinare), mai con un importo fisso, che salta
    # questo passaggio: da qui il sintomo "fisso funziona, percentuale no".
    "no authority": "the key lacks balance-read (account) permission — needed on top of trading",
    "no permission to access the endpoint": "the key lacks balance-read (account) permission — needed on top of trading",
}


def _explain(exchange: str, action: str, body: str) -> RuntimeError:
    """L'errore dell'exchange piu' cosa significa, quando lo sappiamo."""
    low = body.lower()
    for needle, hint in _HINTS.items():
        if needle in low:
            return RuntimeError(f"{exchange} {action} error: {body} — {hint}")
    return RuntimeError(f"{exchange} {action} error: {body}")


def _base_asset(symbol: str) -> str:
    """Strip USDT or BTC suffix to get the base asset (e.g. BTCUSDT → BTC)."""
    for quote in ("USDT", "BTC", "ETH", "USDC"):
        if symbol.endswith(quote):
            return symbol[: -len(quote)]
    return symbol


def _sign(secret: str, params: dict) -> str:
    """Add timestamp, build query string, append HMAC-SHA256 signature."""
    params["timestamp"] = int(time.time() * 1000)
    query = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig


# A pct_balance buy keeps this share of the free USDT aside: the quantity is
# priced at the last trade, and a market order filled a tick higher would
# otherwise ask for more than there is.
PCT_BUY_MARGIN = 0.995
_RULES_TTL_S = 3600
_rules_cache: dict[tuple[str, str], tuple[float, dict]] = {}


async def _rules(client: httpx.AsyncClient, exchange: str, symbol: str) -> dict:
    """The pair's order rules: how many decimals a quantity may have and the
    smallest order in USDT. Read from exchangeInfo, never assumed: MEXC
    allows 8 decimals on BTC, 3 on SOL, 2 on KAS and none on PEPE, and the
    6 decimals sent before (23/10) made most low-priced coins unbuyable."""
    key = (exchange, symbol)
    hit = _rules_cache.get(key)
    if hit and time.time() - hit[0] < _RULES_TTL_S:
        return hit[1]
    resp = await client.get(f"/api/v3/exchangeInfo?symbol={symbol}")
    if resp.status_code >= 400:
        raise _explain(exchange, "pair rules", resp.text)
    row = next((x for x in resp.json().get("symbols", []) if x.get("symbol") == symbol), None)
    if row is None:
        raise RuntimeError(f"{exchange}: pair {symbol} not found — check the exact name (e.g. BTCUSDT)")
    rules = {"decimals": 6, "step": None, "min_quote": 0.0, "tradable": True, "taker_fee": 0.0}
    if exchange == "mexc":
        rules["decimals"] = int(row.get("baseAssetPrecision", 6))
        # MEXC takes the fee out of the coins a buy receives.
        rules["taker_fee"] = float(row.get("takerCommission") or 0)
        rules["min_quote"] = float(row.get("quoteAmountPrecisionMarket") or row.get("quoteAmountPrecision") or 0)
        rules["tradable"] = str(row.get("status")) in ("1", "ENABLED", "TRADING") and row.get("isSpotTradingAllowed", True)
    else:
        for f in row.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                rules["step"] = float(f.get("stepSize") or 0) or None
            if f.get("filterType") in ("NOTIONAL", "MIN_NOTIONAL"):
                rules["min_quote"] = float(f.get("minNotional") or 0)
        rules["tradable"] = row.get("status") == "TRADING"
    _rules_cache[key] = (time.time(), rules)
    return rules


def floor_qty(qty: float, rules: dict) -> float:
    """Rounded down, never up: selling 100% rounded up asks for more than the
    balance, and MEXC answers "Oversold"."""
    if rules.get("step"):
        step = rules["step"]
        return math.floor(qty / step + 1e-9) * step
    scale = 10 ** rules["decimals"]
    return math.floor(qty * scale + 1e-9) / scale


def fmt_qty(qty: float, rules: dict) -> str:
    decimals = rules["decimals"] if not rules.get("step") else max(0, -int(math.floor(math.log10(rules["step"]))))
    text = f"{qty:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


async def _free(client: httpx.AsyncClient, exchange: str, api_secret: str, headers: dict) -> dict[str, float]:
    resp = await client.get(f"/api/v3/account?{_sign(api_secret, {})}", headers=headers)
    if resp.status_code >= 400:
        raise _explain(exchange, "account", resp.text)
    return {b["asset"]: float(b["free"]) for b in resp.json()["balances"]}


async def _price(client: httpx.AsyncClient, exchange: str, symbol: str) -> float:
    resp = await client.get(f"/api/v3/ticker/price?symbol={symbol}")
    if resp.status_code >= 400:
        raise _explain(exchange, "price", resp.text)
    price = float(resp.json()["price"])
    if price <= 0:
        raise RuntimeError("Market price not available for this symbol")
    return price


async def place_order(
    exchange: str,
    symbol: str,
    side: str,
    size_mode: str,
    size_value: float,
    api_key: str,
    api_secret: str,
    max_usdt: float | None = None,
) -> dict:
    """size_mode: "fixed_usdt" (USDT to spend, or USDT worth to sell),
    "pct_balance" (share of free USDT to spend, or of the free coin to sell)
    or, on a sell, "base_qty" (exactly this many coins, at most what is free:
    how a bot closes the position it opened)."""
    if exchange not in _API_KEY_HEADER:
        raise RuntimeError(f"Exchange not handled by this executor: {exchange}")
    base_url = BINANCE_BASE if exchange == "binance" else MEXC_BASE
    headers = {_API_KEY_HEADER[exchange]: api_key}

    # The key goes on the signed calls only: MEXC refuses even its public
    # exchangeInfo and ticker when a wrong key comes along (seen 23/10).
    async with httpx.AsyncClient(base_url=base_url) as client:
        order_params: dict = {"symbol": symbol, "side": side, "type": "MARKET"}
        rules = await _rules(client, exchange, symbol)
        if not rules["tradable"]:
            raise RuntimeError(f"{exchange}: {symbol} is not open for spot trading right now")

        if side == "BUY":
            if size_mode == "fixed_usdt":
                quote_qty = size_value
            elif size_mode == "pct_balance":
                free_usdt = (await _free(client, exchange, api_secret, headers)).get("USDT", 0.0)
                quote_qty = free_usdt * size_value / 100 * PCT_BUY_MARGIN
            else:
                raise RuntimeError(f"Unknown size mode for a buy: {size_mode}")
            # Tetto per singolo ingresso, indipendente dal size_mode — mai
            # applicato lato SELL (vedi place_order_for_signal in executor.py).
            if max_usdt:
                quote_qty = min(quote_qty, max_usdt)
            if quote_qty < rules["min_quote"]:
                raise RuntimeError(f"{exchange}: {quote_qty:.2f} USDT is below the minimum order of "
                                   f"{rules['min_quote']:g} USDT for {symbol}")
            if exchange == "mexc":
                # MEXC dichiara quoteOrderQty a documentazione, ma su piu'
                # pair (specie quelli meno liquidi) lo ignora e tratta il
                # numero come quantita' di moneta base — un ordine da "10
                # USDT" diventa "10 monete", spesso molto piu' del saldo
                # disponibile. Bypassato calcolando la quantita' noi stessi
                # dal prezzo corrente e mandando "quantity", come gia' si fa
                # per il lato SELL qui sotto — MEXC quella la rispetta sempre.
                price = await _price(client, exchange, symbol)
                qty = floor_qty(quote_qty / price, rules)
                if qty <= 0:
                    raise RuntimeError(f"{exchange}: {quote_qty:.2f} USDT buys less than the smallest "
                                       f"quantity of {symbol}")
                order_params["quantity"] = fmt_qty(qty, rules)
            else:
                order_params["quoteOrderQty"] = quote_qty

        else:  # SELL
            if size_mode == "fixed_usdt":
                qty = size_value / await _price(client, exchange, symbol)
            elif size_mode == "pct_balance":
                free = (await _free(client, exchange, api_secret, headers)).get(_base_asset(symbol), 0.0)
                qty = free * size_value / 100
            elif size_mode == "base_qty":
                free = (await _free(client, exchange, api_secret, headers)).get(_base_asset(symbol), 0.0)
                qty = min(size_value, free)
            else:
                raise RuntimeError(f"Unknown size mode for a sell: {size_mode}")
            qty = floor_qty(qty, rules)
            if qty <= 0:
                raise RuntimeError("Computed quantity is zero or negative — insufficient balance or price unavailable")
            if rules["min_quote"] and size_mode != "fixed_usdt":
                value = qty * await _price(client, exchange, symbol)
                if value < rules["min_quote"]:
                    raise RuntimeError(f"{exchange}: {qty:g} {_base_asset(symbol)} is worth {value:.2f} USDT, "
                                       f"below the minimum order of {rules['min_quote']:g} USDT")
            order_params["quantity"] = fmt_qty(qty, rules)

        signed_qs = _sign(api_secret, order_params)
        order_resp = await client.post(f"/api/v3/order?{signed_qs}", headers=headers)
        if order_resp.status_code >= 400:
            raise _explain(exchange, "order", order_resp.text)
        result = order_resp.json()
        if isinstance(result, dict) and "quantity" in order_params:
            result.setdefault("requestedQty", order_params["quantity"])
            if side == "BUY":
                # What lands on the account after the fee: the coins a bot's
                # exit may sell without touching any that were there before.
                result["netQty"] = float(order_params["quantity"]) * (1 - rules["taker_fee"])
        return result
