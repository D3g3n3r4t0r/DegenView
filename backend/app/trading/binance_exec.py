import hashlib
import hmac
import time
import urllib.parse

import httpx

BINANCE_BASE = "https://api.binance.com"
MEXC_BASE = "https://api.mexc.com"


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


async def place_order(
    exchange: str,
    symbol: str,
    side: str,
    size_mode: str,
    size_value: float,
    api_key: str,
    api_secret: str,
) -> dict:
    base_url = BINANCE_BASE if exchange == "binance" else MEXC_BASE
    headers = {"X-MBX-APIKEY": api_key}

    async with httpx.AsyncClient(base_url=base_url, headers=headers) as client:
        order_params: dict = {"symbol": symbol, "side": side, "type": "MARKET"}

        if side == "BUY":
            if size_mode == "fixed_usdt":
                order_params["quoteOrderQty"] = size_value
            else:
                resp = await client.get(f"/api/v3/account?{_sign(api_secret, {})}")
                if resp.status_code >= 400:
                    raise RuntimeError(f"{exchange} account error: {resp.text}")
                balances = {b["asset"]: float(b["free"]) for b in resp.json()["balances"]}
                free_usdt = balances.get("USDT", 0.0)
                order_params["quoteOrderQty"] = free_usdt * size_value / 100

        else:  # SELL
            if size_mode == "fixed_usdt":
                price_resp = await client.get(f"/api/v3/ticker/price?symbol={symbol}")
                if price_resp.status_code >= 400:
                    raise RuntimeError(f"{exchange} price error: {price_resp.text}")
                price = float(price_resp.json()["price"])
                qty = size_value / price
                order_params["quantity"] = f"{qty:.6f}".rstrip("0").rstrip(".")
            else:
                base = _base_asset(symbol)
                resp = await client.get(f"/api/v3/account?{_sign(api_secret, {})}")
                if resp.status_code >= 400:
                    raise RuntimeError(f"{exchange} account error: {resp.text}")
                balances = {b["asset"]: float(b["free"]) for b in resp.json()["balances"]}
                free = balances.get(base, 0.0)
                qty = free * size_value / 100
                order_params["quantity"] = f"{qty:.6f}".rstrip("0").rstrip(".")

        signed_qs = _sign(api_secret, order_params)
        order_resp = await client.post(f"/api/v3/order?{signed_qs}")
        if order_resp.status_code >= 400:
            raise RuntimeError(f"{exchange} order error: {order_resp.text}")
        return order_resp.json()
