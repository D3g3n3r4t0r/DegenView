"""Fast live market snapshot & macro regime detector for TradingView Composite Tickers.

Computes real-time values, formatted display strings, 24h percentage changes,
and macro market regime classification (`Altseason Expansion`,
`BTC Dominance Surge`, `Risk-Off / Stablecoin Flight`, `Balanced Rotation`)
across all 20 composite indices defined in `app.providers.composites.COMPOSITES`.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from cachetools import TTLCache

from app import http_client
from app.providers import composites
from app.providers.composites import (
    ALL_CONSTITUENTS,
    COMPOSITES,
    SUPPLY_BILLIONS,
    USDC_B,
    USDT_B,
    STABLES_B,
    _DEFI_BASKET_MULT,
    _OTHERS_MAJOR_ALT_MULT,
    _OTHERS_MIDCAP_MULT,
    _fetch_global_calibration,
    composite_provider,
)
from app.providers.mexc import BASE_URL as MEXC_BASE_URL

# 30-second in-memory TTL cache for composite snapshots
_snapshot_cache: TTLCache = TTLCache(maxsize=4, ttl=30)
_last_good_snapshot: dict[str, Any] | None = None
_snapshot_lock: asyncio.Lock | None = None

# Baseline fallback prices (used only if both MEXC 24hr ticker and klines are unreachable)
_FALLBACK_PRICES: dict[str, tuple[float, float]] = {
    # coin: (last_price, open_24h_price)
    "BTC": (85_000.0, 84_200.0),
    "ETH": (2_200.0, 2_165.0),
    "SOL": (145.0, 141.5),
    "BNB": (610.0, 604.0),
    "XRP": (2.15, 2.10),
    "ADA": (0.72, 0.705),
    "DOGE": (0.175, 0.171),
    "TRX": (0.235, 0.233),
    "AVAX": (22.5, 21.8),
    "LINK": (15.8, 15.3),
    "UNI": (7.40, 7.20),
    "AAVE": (185.0, 179.0),
}


def _get_lock() -> asyncio.Lock:
    global _snapshot_lock
    if _snapshot_lock is None:
        _snapshot_lock = asyncio.Lock()
    return _snapshot_lock


def format_composite_display(value: float, unit: str) -> str:
    """Format a composite index numerical value according to its unit (`B_USD`, `PCT`, `RATIO`)."""
    if unit == "B_USD":
        if value >= 1000.0:
            return f"${value / 1000.0:.2f}T"
        if value >= 100.0:
            return f"${value:.1f}B"
        return f"${value:.2f}B"
    if unit == "PCT":
        return f"{value:.2f}%"
    # unit == "RATIO"
    if value >= 10.0:
        return f"{value:.2f}"
    if value >= 1.0:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.5f}"
    return f"{value:.6f}"


async def _fetch_mexc_24hr_single(client: Any, coin: str) -> tuple[str, float, float] | None:
    """Fetch 24h `(lastPrice, openPrice)` for `{coin}USDT` from MEXC `/api/v3/ticker/24hr`."""
    symbol = f"{coin}USDT"
    try:
        resp = await client.get(
            f"{MEXC_BASE_URL}/api/v3/ticker/24hr",
            params={"symbol": symbol},
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        if not isinstance(payload, dict):
            return None
        last_price = float(payload.get("lastPrice") or 0.0)
        open_price = float(payload.get("openPrice") or payload.get("prevClosePrice") or 0.0)
        if last_price <= 0.0:
            return None
        if open_price <= 0.0:
            # Derive open_price from priceChangePercent if openPrice is missing
            pct_raw = float(payload.get("priceChangePercent") or 0.0)
            open_price = last_price / (1.0 + pct_raw) if (1.0 + pct_raw) > 0 else last_price
        return coin, last_price, open_price
    except Exception:  # noqa: BLE001
        return None


async def _fetch_constituent_1h_fallback(coin: str) -> tuple[str, float, float] | None:
    """Fallback to 25x 1h candles via `composite_provider` if 24hr ticker stats fail."""
    try:
        df = await composite_provider._fetch_constituent(coin, "1h", 25, None)
        if df is None or df.empty:
            return None
        last_price = float(df["close"].iloc[-1])
        open_price = float(df["open"].iloc[0]) if len(df) >= 24 else float(df["open"].iloc[0])
        if last_price <= 0.0 or open_price <= 0.0:
            return None
        return coin, last_price, open_price
    except Exception:  # noqa: BLE001
        return None


async def _fetch_all_constituent_24h_prices() -> tuple[dict[str, float], dict[str, float]]:
    """Fetch current and 24h-ago USD prices for all 12 constituent coins in parallel (<0.5s)."""
    prices_now: dict[str, float] = {}
    prices_24h: dict[str, float] = {}

    try:
        async with http_client.pooled(timeout=3.5) as client:
            tasks = [_fetch_mexc_24hr_single(client, coin) for coin in ALL_CONSTITUENTS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, tuple) and len(res) == 3:
                    coin, last_p, open_p = res
                    prices_now[coin] = last_p
                    prices_24h[coin] = open_p
    except httpx.HTTPError:
        pass

    missing = [coin for coin in ALL_CONSTITUENTS if coin not in prices_now]
    if missing:
        fallback_tasks = [_fetch_constituent_1h_fallback(coin) for coin in missing]
        fallback_results = await asyncio.gather(*fallback_tasks, return_exceptions=True)
        for res in fallback_results:
            if isinstance(res, tuple) and len(res) == 3:
                coin, last_p, open_p = res
                prices_now[coin] = last_p
                prices_24h[coin] = open_p

    for coin in ALL_CONSTITUENTS:
        if coin not in prices_now or prices_now[coin] <= 0.0:
            fb_now, fb_open = _FALLBACK_PRICES.get(coin, (1.0, 1.0))
            prices_now[coin] = fb_now
            prices_24h[coin] = fb_open

    return prices_now, prices_24h


def _compute_composite_values(
    prices: dict[str, float],
    cal: dict[str, float],
    others_scale_override: float | None = None,
) -> tuple[dict[str, float], float]:
    """Compute scalar values for all 20 composites from a constituent price map."""
    mcap: dict[str, float] = {
        coin: float(prices[coin]) * SUPPLY_BILLIONS[coin]
        for coin in ALL_CONSTITUENTS
    }

    btc = mcap["BTC"]
    eth = mcap["ETH"]
    sol = mcap["SOL"]
    bnb = mcap["BNB"]
    xrp = mcap["XRP"]
    doge = mcap["DOGE"]
    ada = mcap["ADA"]
    trx = mcap["TRX"]
    avax = mcap["AVAX"]
    link = mcap["LINK"]
    uni = mcap["UNI"]
    aave = mcap["AAVE"]

    usdt_b = float(cal.get("usdt_b", USDT_B))
    usdc_b = float(cal.get("usdc_b", USDC_B))
    stables_b = float(cal.get("stables_b", STABLES_B))

    defi = _DEFI_BASKET_MULT * (
        uni + aave + link + 0.35 * avax + 0.12 * sol + 0.05 * eth
    )

    major_alts = sol + bnb + xrp + doge + ada + trx
    mid = avax + link + uni + aave
    others_raw = _OTHERS_MIDCAP_MULT * mid + _OTHERS_MAJOR_ALT_MULT * major_alts

    if others_scale_override is not None:
        scale = others_scale_override
    else:
        scale = 1.0
        total_target_b = cal.get("total_target_b")
        if total_target_b and others_raw > 0:
            desired_others = float(total_target_b) - (btc + eth + major_alts + stables_b)
            scale = max(0.5, min(2.0, desired_others / others_raw))

    others = others_raw * scale
    total3_es = major_alts + others
    total3 = total3_es + stables_b
    total2_es = eth + total3_es
    total2 = eth + total3
    totales = btc + total2_es
    total = max(btc + total2, 1e-9)

    btc_p = max(float(prices["BTC"]), 1e-12)
    eth_p = max(float(prices["ETH"]), 1e-12)
    sol_p = max(float(prices["SOL"]), 1e-12)
    eth_mcap_safe = max(eth, 1e-12)

    values: dict[str, float] = {
        # Market Cap Indices (B_USD)
        "TOTAL": total,
        "TOTAL2": total2,
        "TOTAL3": total3,
        "TOTALES": totales,
        "TOTAL2ES": total2_es,
        "TOTAL3ES": total3_es,
        "OTHERS": others,
        "TOTALDEFI": defi,
        # Dominance Indices (PCT)
        "BTC.D": (btc / total) * 100.0,
        "ETH.D": (eth / total) * 100.0,
        "USDT.D": (usdt_b / total) * 100.0,
        "USDC.D": (usdc_b / total) * 100.0,
        "STABLE.C.D": (stables_b / total) * 100.0,
        "OTHERS.D": (others / total) * 100.0,
        "TOTAL3.D": (total3 / total) * 100.0,
        "ALTS.D": (total2 / total) * 100.0,
        # Ratios & Rotation Indices (RATIO)
        "ETHBTC": eth_p / btc_p,
        "SOLBTC": sol_p / btc_p,
        "SOLETH": sol_p / eth_p,
        "DEFIETH": (defi / eth_mcap_safe) * 100.0,
    }
    return values, scale


def _detect_regime(by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Classify the current macro market regime from composite 24h changes."""
    total = by_symbol["TOTAL"]
    total3 = by_symbol["TOTAL3"]
    totales = by_symbol["TOTALES"]
    btc_d = by_symbol["BTC.D"]
    usdt_d = by_symbol["USDT.D"]
    others_d = by_symbol["OTHERS.D"]

    total_chg = float(total["change_24h_pct"])
    total3_chg = float(total3["change_24h_pct"])
    totales_chg = float(totales["change_24h_pct"])
    btc_d_chg = float(btc_d["change_24h_pct"])
    usdt_d_chg = float(usdt_d["change_24h_pct"])
    others_d_chg = float(others_d["change_24h_pct"])

    if total3_chg > 0.0 and btc_d_chg < 0.0:
        label = "Altseason Expansion"
        tone = "bull"
        lead = "Rotazione risk-on verso le altcoin (Altseason Expansion)"
    elif btc_d_chg > 0.3 and total_chg > 0.0:
        label = "BTC Dominance Surge"
        tone = "bull"
        lead = "Afflusso guidato da Bitcoin (BTC Dominance Surge)"
    elif usdt_d_chg > 0.3 and totales_chg < 0.0:
        label = "Risk-Off / Stablecoin Flight"
        tone = "bear"
        lead = "Difesa su liquidita' stablecoin (Risk-Off / Stablecoin Flight)"
    else:
        label = "Balanced Rotation"
        tone = "neutral"
        lead = "Mercato in rotazione bilanciata (Balanced Rotation)"

    summary = (
        f"{lead}: "
        f"TOTAL {total['display']} ({total_chg:+.2f}%), "
        f"TOTALES {totales['display']} ({totales_chg:+.2f}%), "
        f"TOTAL3 {total3['display']} ({total3_chg:+.2f}%), "
        f"BTC.D {btc_d['display']} ({btc_d_chg:+.2f}%), "
        f"USDT.D {usdt_d['display']} ({usdt_d_chg:+.2f}%), "
        f"OTHERS.D {others_d['display']} ({others_d_chg:+.2f}%)."
    )

    return {
        "label": label,
        "tone": tone,
        "summary": summary,
    }


async def get_composites_snapshot(force: bool = False) -> dict[str, Any]:
    """Return live market snapshot and macro regime across all 20 composite tickers.

    Cached in `_snapshot_cache` for 30 seconds (`<1ms` on cache hit, `<0.5s` cold).
    """
    global _last_good_snapshot

    if not force:
        cached = _snapshot_cache.get("snapshot")
        if cached is not None:
            return cached

    async with _get_lock():
        if not force:
            cached = _snapshot_cache.get("snapshot")
            if cached is not None:
                return cached

        # Use already-cached global calibration if present; otherwise kick off a short
        # bounded calibration alongside the MEXC 24hr parallel fetch so latency stays <0.5s.
        cal = composites._global_cal_cache.get("cal")
        if cal is None:
            cal = {
                "usdt_b": USDT_B,
                "usdc_b": USDC_B,
                "stables_b": STABLES_B,
                "others_scale": 1.0,
            }
            # Populate calibration opportunistically if fast, without blocking >250ms
            try:
                prices_res, cal_res = await asyncio.gather(
                    _fetch_all_constituent_24h_prices(),
                    asyncio.wait_for(_fetch_global_calibration(), timeout=0.25),
                    return_exceptions=True,
                )
                if isinstance(cal_res, dict):
                    cal = cal_res
                if isinstance(prices_res, tuple) and len(prices_res) == 2:
                    prices_now, prices_24h = prices_res
                else:
                    prices_now, prices_24h = await _fetch_all_constituent_24h_prices()
            except Exception:  # noqa: BLE001
                prices_now, prices_24h = await _fetch_all_constituent_24h_prices()
        else:
            prices_now, prices_24h = await _fetch_all_constituent_24h_prices()

        values_now, scale_now = _compute_composite_values(prices_now, cal)
        values_24h, _ = _compute_composite_values(prices_24h, cal, others_scale_override=scale_now)

        items: list[dict[str, Any]] = []
        by_symbol: dict[str, dict[str, Any]] = {}

        for symbol, meta in COMPOSITES.items():
            unit = str(meta["unit"])
            val_now = float(values_now[symbol])
            val_prev = float(values_24h[symbol])
            chg_pct = ((val_now - val_prev) / val_prev) * 100.0 if val_prev > 0.0 else 0.0

            if unit == "B_USD":
                rounded_val = round(val_now, 2)
            elif unit == "PCT":
                rounded_val = round(val_now, 2)
            else:
                rounded_val = round(val_now, 6)

            entry: dict[str, Any] = {
                "symbol": symbol,
                "name": str(meta["name"]),
                "category": str(meta["category"]),
                "unit": unit,
                "value": rounded_val,
                "display": format_composite_display(val_now, unit),
                "change_24h_pct": round(chg_pct, 2),
                "formula": str(meta["formula"]),
                "description": str(meta["description"]),
            }
            items.append(entry)
            by_symbol[symbol] = entry

        regime = _detect_regime(by_symbol)
        now_ms = int(time.time() * 1000)

        payload: dict[str, Any] = {
            "items": items,
            "composites": items,
            "by_symbol": by_symbol,
            "tickers": by_symbol,
            "regime": regime,
            "count": len(items),
            "updated_at": now_ms,
            "updated_at_iso": datetime.now(timezone.utc).isoformat(),
        }

        _snapshot_cache["snapshot"] = payload
        _last_good_snapshot = payload
        return payload
