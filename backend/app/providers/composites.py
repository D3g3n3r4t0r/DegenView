"""TradingView-style Crypto Composite Index Engine (`CompositeProvider`).

Synthesizes historical and live OHLCV candles for 20 canonical market-cap,
dominance, and rotation/ratio indices from constituent spot klines on MEXC:

Market Cap Indices (unit="B_USD", in Billions USD, e.g. 2450.32 = $2.45T):
  - TOTAL     : Crypto Total Market Cap (All Crypto)
  - TOTAL2    : Crypto Total Market Cap Ex-BTC (TOTAL - BTC)
  - TOTAL3    : Crypto Total Market Cap Ex-BTC & ETH (TOTAL - BTC - ETH)
  - TOTALES   : Crypto Total Market Cap Ex-Stablecoins (TOTAL - STABLES)
  - TOTAL2ES  : Crypto Total Market Cap Ex-BTC & Stablecoins (TOTAL2 - STABLES)
  - TOTAL3ES  : Crypto Total Market Cap Ex-BTC, ETH & Stablecoins (TOTAL3 - STABLES)
  - OTHERS    : Crypto Total Market Cap Excluding Top 10 (Altcoin Mid/Small Cap Index)
  - TOTALDEFI : DeFi Total Market Cap (DeFi Basket Market Cap)

Dominance Indices (unit="PCT", 0.0 to 100.0):
  - BTC.D      : Bitcoin Dominance % (BTC / TOTAL * 100)
  - ETH.D      : Ethereum Dominance % (ETH / TOTAL * 100)
  - USDT.D     : Tether USDT Dominance % (USDT / TOTAL * 100)
  - USDC.D     : USD Coin Dominance % (USDC / TOTAL * 100)
  - STABLE.C.D : Total Stablecoin Dominance % (STABLES / TOTAL * 100)
  - OTHERS.D   : Others (Ex-Top 10) Dominance % (OTHERS / TOTAL * 100)
  - TOTAL3.D   : Total3 (Ex-BTC & ETH) Dominance % (TOTAL3 / TOTAL * 100)
  - ALTS.D     : Altcoin (Ex-BTC) Dominance % (TOTAL2 / TOTAL * 100)

Ratios & Rotation Indices (unit="RATIO"):
  - ETHBTC     : Ethereum / Bitcoin Ratio (ETH / BTC)
  - SOLBTC     : Solana / Bitcoin Ratio (SOL / BTC)
  - SOLETH     : Solana / Ethereum Ratio (SOL / ETH)
  - DEFIETH    : DeFi / Ethereum Rotation Index (TOTALDEFI / ETH_MCAP * 100)
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import numpy as np
import pandas as pd
from cachetools import TTLCache

from app import http_client
from app.providers.base import DataProvider, ProviderError
from app.providers.mexc import MexcProvider

# ---------------------------------------------------------------------------
# Circulating supply baselines & basket calibration (Billions of coins / USD)
# ---------------------------------------------------------------------------
# Multiplying a coin's USD price by (supply / 1e9) yields its market cap
# directly in Billions USD (B_USD).
CIRCULATING_SUPPLY: dict[str, float] = {
    "BTC": 19_850_000.0,
    "ETH": 120_400_000.0,
    "SOL": 488_000_000.0,
    "BNB": 144_000_000.0,
    "XRP": 58_000_000_000.0,
    "DOGE": 148_000_000_000.0,
    "ADA": 35_900_000_000.0,
    "TRX": 86_100_000_000.0,
    "AVAX": 414_000_000.0,
    "LINK": 638_000_000.0,
    "UNI": 600_500_000.0,
    "AAVE": 15_100_000.0,
}

SUPPLY_BILLIONS: dict[str, float] = {
    coin: supply / 1e9 for coin, supply in CIRCULATING_SUPPLY.items()
}

# Stablecoin market cap baselines in Billions USD
USDT_B: float = 142.5
USDC_B: float = 56.2
DAI_B: float = 5.3
STABLES_B: float = 204.0  # USDT_B + USDC_B + DAI_B

# Constituent MEXC spot pairs
ALL_CONSTITUENTS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "ADA",
    "DOGE",
    "TRX",
    "AVAX",
    "LINK",
    "UNI",
    "AAVE",
)

TOP8_NON_STABLE: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "TRX",
)

MIDCAP_BASKET: tuple[str, ...] = (
    "AVAX",
    "LINK",
    "UNI",
    "AAVE",
)

# Multipliers that scale our liquid proxy baskets to the full market-wide
# long-tail (Top 11..5000 for OTHERS, and the broader DeFi ecosystem for TOTALDEFI).
_OTHERS_MIDCAP_MULT: float = 9.5
_OTHERS_MAJOR_ALT_MULT: float = 0.18
_DEFI_BASKET_MULT: float = 2.1

# ---------------------------------------------------------------------------
# Canonical Composite Index Metadata Registry (20 indices)
# ---------------------------------------------------------------------------
COMPOSITES: dict[str, dict[str, Any]] = {
    # --- Market Cap Indices (unit="B_USD") ---
    "TOTAL": {
        "symbol": "TOTAL",
        "name": "Crypto Total Market Cap ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Total market capitalization of all cryptocurrencies in Billions USD.",
        "formula": "BTC + ETH + Top10 Alts + OTHERS + STABLES",
        "aliases": ["CRYPTOCAP:TOTAL", "TOTAL1", "CRYPTO.TOTAL"],
    },
    "TOTAL2": {
        "symbol": "TOTAL2",
        "name": "Crypto Total Market Cap Ex-BTC ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Total cryptocurrency market capitalization excluding Bitcoin, in Billions USD.",
        "formula": "TOTAL - BTC",
        "aliases": ["CRYPTOCAP:TOTAL2", "TOTAL.2"],
    },
    "TOTAL3": {
        "symbol": "TOTAL3",
        "name": "Crypto Total Market Cap Ex-BTC & ETH ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Total altcoin market capitalization excluding Bitcoin and Ethereum, in Billions USD.",
        "formula": "TOTAL - BTC - ETH",
        "aliases": ["CRYPTOCAP:TOTAL3", "TOTAL.3"],
    },
    "TOTALES": {
        "symbol": "TOTALES",
        "name": "Crypto Total Market Cap Ex-Stablecoins ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Total cryptocurrency market capitalization excluding stablecoins, in Billions USD.",
        "formula": "TOTAL - STABLES",
        "aliases": ["CRYPTOCAP:TOTALES", "TOTAL.ES", "TOTAL_ES"],
    },
    "TOTAL2ES": {
        "symbol": "TOTAL2ES",
        "name": "Crypto Total Market Cap Ex-BTC & Stablecoins ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Total altcoin market cap excluding Bitcoin and stablecoins, in Billions USD.",
        "formula": "TOTAL2 - STABLES",
        "aliases": ["CRYPTOCAP:TOTAL2ES", "TOTAL2.ES", "TOTAL2_ES"],
    },
    "TOTAL3ES": {
        "symbol": "TOTAL3ES",
        "name": "Crypto Total Market Cap Ex-BTC, ETH & Stablecoins ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Pure altcoin market cap excluding Bitcoin, Ethereum, and stablecoins, in Billions USD.",
        "formula": "TOTAL3 - STABLES",
        "aliases": ["CRYPTOCAP:TOTAL3ES", "TOTAL3.ES", "TOTAL3_ES"],
    },
    "OTHERS": {
        "symbol": "OTHERS",
        "name": "Crypto Total Market Cap Ex-Top 10 ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Altcoin mid/small-cap market capitalization excluding the top 10 coins, in Billions USD.",
        "formula": "TOTAL - TOP10",
        "aliases": ["CRYPTOCAP:OTHERS", "OTHERSMCAP"],
    },
    "TOTALDEFI": {
        "symbol": "TOTALDEFI",
        "name": "DeFi Total Market Cap ($B)",
        "category": "market_cap",
        "unit": "B_USD",
        "description": "Total decentralized finance (DeFi) market capitalization in Billions USD.",
        "formula": "DeFi Basket Market Cap",
        "aliases": ["CRYPTOCAP:TOTALDEFI", "DEFI.MCAP", "TOTAL.DEFI"],
    },
    # --- Dominance Indices (unit="PCT") ---
    "BTC.D": {
        "symbol": "BTC.D",
        "name": "Bitcoin Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Bitcoin share of the total cryptocurrency market capitalization (0-100%).",
        "formula": "BTC / TOTAL * 100",
        "aliases": ["BTCD", "BTCDOM", "BTC.DOM", "CRYPTOCAP:BTC.D"],
    },
    "ETH.D": {
        "symbol": "ETH.D",
        "name": "Ethereum Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Ethereum share of the total cryptocurrency market capitalization (0-100%).",
        "formula": "ETH / TOTAL * 100",
        "aliases": ["ETHD", "ETHDOM", "ETH.DOM", "CRYPTOCAP:ETH.D"],
    },
    "USDT.D": {
        "symbol": "USDT.D",
        "name": "Tether USDT Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Tether (USDT) share of the total cryptocurrency market capitalization (0-100%).",
        "formula": "USDT / TOTAL * 100",
        "aliases": ["USDTD", "USDTDOM", "USDT.DOM", "CRYPTOCAP:USDT.D"],
    },
    "USDC.D": {
        "symbol": "USDC.D",
        "name": "USD Coin Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "USD Coin (USDC) share of the total cryptocurrency market capitalization (0-100%).",
        "formula": "USDC / TOTAL * 100",
        "aliases": ["USDCD", "USDCDOM", "USDC.DOM", "CRYPTOCAP:USDC.D"],
    },
    "STABLE.C.D": {
        "symbol": "STABLE.C.D",
        "name": "Total Stablecoin Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Combined stablecoin (USDT + USDC + DAI) share of total crypto market cap (0-100%).",
        "formula": "STABLES / TOTAL * 100",
        "aliases": ["STABLE.D", "STABLED", "STABLES.D", "STABLESD", "CRYPTOCAP:STABLE.C.D"],
    },
    "OTHERS.D": {
        "symbol": "OTHERS.D",
        "name": "Others (Ex-Top 10) Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Mid/small-cap altcoin (ex-Top 10) share of total crypto market cap (0-100%).",
        "formula": "OTHERS / TOTAL * 100",
        "aliases": ["OTHERSD", "OTHERSDOM", "OTHERS.DOM", "CRYPTOCAP:OTHERS.D"],
    },
    "TOTAL3.D": {
        "symbol": "TOTAL3.D",
        "name": "Total3 (Ex-BTC & ETH) Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Altcoin (ex-BTC & ETH) share of total crypto market cap (0-100%).",
        "formula": "TOTAL3 / TOTAL * 100",
        "aliases": ["TOTAL3D", "TOTAL3.DOM", "CRYPTOCAP:TOTAL3.D"],
    },
    "ALTS.D": {
        "symbol": "ALTS.D",
        "name": "Altcoin (Ex-BTC) Dominance (%)",
        "category": "dominance",
        "unit": "PCT",
        "description": "Total altcoin (ex-BTC) share of total crypto market cap (0-100%).",
        "formula": "TOTAL2 / TOTAL * 100",
        "aliases": ["ALTSD", "TOTAL2.D", "TOTAL2D", "ALTS.DOM", "CRYPTOCAP:TOTAL2.D"],
    },
    # --- Ratios & Rotation Indices (unit="RATIO") ---
    "ETHBTC": {
        "symbol": "ETHBTC",
        "name": "Ethereum / Bitcoin Ratio",
        "category": "ratio",
        "unit": "RATIO",
        "description": "Relative strength ratio of Ethereum priced in Bitcoin (ETH / BTC).",
        "formula": "ETH / BTC",
        "aliases": ["ETH.BTC", "ETH/BTC"],
    },
    "SOLBTC": {
        "symbol": "SOLBTC",
        "name": "Solana / Bitcoin Ratio",
        "category": "ratio",
        "unit": "RATIO",
        "description": "Relative strength ratio of Solana priced in Bitcoin (SOL / BTC).",
        "formula": "SOL / BTC",
        "aliases": ["SOL.BTC", "SOL/BTC"],
    },
    "SOLETH": {
        "symbol": "SOLETH",
        "name": "Solana / Ethereum Ratio",
        "category": "ratio",
        "unit": "RATIO",
        "description": "Relative strength ratio of Solana priced in Ethereum (SOL / ETH).",
        "formula": "SOL / ETH",
        "aliases": ["SOL.ETH", "SOL/ETH"],
    },
    "DEFIETH": {
        "symbol": "DEFIETH",
        "name": "DeFi / Ethereum Rotation Index",
        "category": "ratio",
        "unit": "RATIO",
        "description": "DeFi total market cap relative to Ethereum market cap (TOTALDEFI / ETH_MCAP * 100).",
        "formula": "TOTALDEFI / ETH_MCAP * 100",
        "aliases": ["DEFI.ETH", "DEFI/ETH", "TOTALDEFI/ETH"],
    },
}

# Build fast O(1) lookup table mapping normalized aliases -> canonical symbol
_ALIAS_MAP: dict[str, str] = {}
for _canon, _meta in COMPOSITES.items():
    _ALIAS_MAP[_canon.upper()] = _canon
    for _alias in _meta.get("aliases", []):
        _ALIAS_MAP[_alias.upper()] = _canon


def resolve_composite(symbol: str) -> str | None:
    """Resolve a ticker or alias to its canonical composite symbol, or None."""
    if not symbol or not isinstance(symbol, str):
        return None
    cleaned = symbol.strip().upper()
    if not cleaned:
        return None
    if cleaned in _ALIAS_MAP:
        return _ALIAS_MAP[cleaned]
    # Strip TradingView exchange prefixes such as CRYPTOCAP:, INDEX:, TV:
    if ":" in cleaned:
        _, _, tail = cleaned.partition(":")
        tail = tail.strip()
        if tail in _ALIAS_MAP:
            return _ALIAS_MAP[tail]
    # Handle hyphen/underscore variants
    norm = cleaned.replace("-", ".").replace("_", ".")
    if norm in _ALIAS_MAP:
        return _ALIAS_MAP[norm]
    norm_compact = cleaned.replace("-", "").replace("_", "")
    if norm_compact in _ALIAS_MAP:
        return _ALIAS_MAP[norm_compact]
    return None


def is_composite_symbol(symbol: str) -> bool:
    """Return True if `symbol` is a supported composite index or alias."""
    return resolve_composite(symbol) is not None


def get_composite_meta(symbol: str) -> dict[str, Any] | None:
    """Return metadata dict for `symbol` (or None if not a composite index)."""
    canon = resolve_composite(symbol)
    if canon is None:
        return None
    return dict(COMPOSITES[canon])


def search_composites(query: str) -> list[dict[str, Any]]:
    """Search composite indices matching `query`, formatted as SymbolSuggestion dicts."""
    q_raw = (query or "").strip().upper()
    if not q_raw:
        return []
    q_clean = q_raw.split(":", 1)[-1].strip() if ":" in q_raw else q_raw
    q_compact = q_clean.replace(".", "").replace("/", "").replace("-", "").replace("_", "")

    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for idx, (canon, meta) in enumerate(COMPOSITES.items()):
        aliases_upper = [a.upper() for a in meta.get("aliases", [])]
        canon_compact = canon.replace(".", "")
        name_upper = meta["name"].upper()
        desc_upper = meta["description"].upper()

        if q_clean == canon or q_clean in aliases_upper or q_compact == canon_compact:
            rank = 0
        elif canon.startswith(q_clean) or canon_compact.startswith(q_compact):
            rank = 1
        elif any(a.startswith(q_clean) or a.replace(".", "").startswith(q_compact) for a in aliases_upper):
            rank = 2
        elif q_clean in canon or (q_compact and q_compact in canon_compact):
            rank = 3
        elif any(q_clean in a for a in aliases_upper):
            rank = 4
        elif q_clean in name_upper:
            rank = 5
        elif q_clean in desc_upper or q_clean in meta["category"].upper():
            rank = 6
        else:
            continue

        scored.append(
            (
                rank,
                idx,
                canon,
                {
                    "symbol": canon,
                    "name": meta["name"],
                    "exchange": "TradingView Index",
                    "asset_type": "crypto",
                    "provider": "mexc",
                },
            )
        )

    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[3] for item in scored]


# ---------------------------------------------------------------------------
# Short-lived constituent cache & optional CoinGecko global calibration cache
# ---------------------------------------------------------------------------
_constituent_cache: TTLCache = TTLCache(maxsize=64, ttl=20)
_constituent_locks: dict[tuple, asyncio.Lock] = {}
_global_cal_cache: TTLCache = TTLCache(maxsize=1, ttl=600)


def _required_constituents(canon_symbol: str) -> tuple[str, ...]:
    """Return the constituent coin symbols needed to compute `canon_symbol`."""
    if canon_symbol == "ETHBTC":
        return ("BTC", "ETH")
    if canon_symbol == "SOLBTC":
        return ("BTC", "SOL")
    if canon_symbol == "SOLETH":
        return ("ETH", "SOL")
    if canon_symbol in ("TOTALDEFI", "DEFIETH"):
        return ("ETH", "SOL", "AVAX", "LINK", "UNI", "AAVE")
    return ALL_CONSTITUENTS


async def _fetch_global_calibration() -> dict[str, float]:
    """Optional live calibration from CoinGecko `/api/v3/global` cached for 10 min.

    Falls back immediately to baseline supply multipliers if offline, rate-limited,
    or running under a test HTTP client override.
    """
    cached = _global_cal_cache.get("cal")
    if cached is not None:
        return cached

    default_cal = {
        "usdt_b": USDT_B,
        "usdc_b": USDC_B,
        "stables_b": STABLES_B,
        "others_scale": 1.0,
    }

    # Avoid consuming mock responses when unit tests monkeypatch httpx.AsyncClient
    if httpx.AsyncClient is not http_client._REAL_ASYNC_CLIENT:
        return default_cal

    try:
        async with http_client.pooled(timeout=2.5) as client:
            resp = await client.get("https://api.coingecko.com/api/v3/global")
        if resp.status_code == 200:
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                mcap_map = data.get("total_market_cap") or {}
                pct_map = data.get("market_cap_percentage") or {}
                total_usd = float(mcap_map.get("usd", 0.0) or 0.0)
                if total_usd > 1e11:
                    total_b = total_usd / 1e9
                    usdt_pct = float(pct_map.get("usdt", 0.0) or 0.0)
                    usdc_pct = float(pct_map.get("usdc", 0.0) or 0.0)
                    usdt_b = (total_b * usdt_pct / 100.0) if usdt_pct > 0.5 else USDT_B
                    usdc_b = (total_b * usdc_pct / 100.0) if usdc_pct > 0.2 else USDC_B
                    stables_b = usdt_b + usdc_b + DAI_B
                    cal = {
                        "usdt_b": usdt_b,
                        "usdc_b": usdc_b,
                        "stables_b": stables_b,
                        "total_target_b": total_b,
                        "others_scale": 1.0,
                    }
                    _global_cal_cache["cal"] = cal
                    return cal
    except Exception:  # noqa: BLE001 — instant offline fallback
        pass

    _global_cal_cache["cal"] = default_cal
    return default_cal


class CompositeProvider(DataProvider):
    """Synthesizes TradingView composite crypto indices from MEXC constituent klines."""

    def __init__(self, mexc_provider: MexcProvider | None = None) -> None:
        self._mexc = mexc_provider or MexcProvider()

    async def _fetch_constituent(
        self,
        coin: str,
        interval: str,
        outputsize: int,
        since_ms: int | None,
    ) -> pd.DataFrame:
        pair = f"{coin}USDT"
        cache_key = (pair, interval, outputsize, since_ms)
        cached = _constituent_cache.get(cache_key)
        if cached is not None:
            return cached

        # Also check if a larger outputsize for the same (pair, interval) is already cached
        if since_ms is None:
            for (c_pair, c_int, c_out, c_since), c_df in list(_constituent_cache.items()):
                if c_pair == pair and c_int == interval and c_since is None and c_out >= outputsize:
                    return c_df.tail(outputsize)

        lock = _constituent_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = _constituent_cache.get(cache_key)
            if cached is not None:
                return cached
            df = await self._mexc.fetch_ohlcv(pair, interval, outputsize, since_ms=since_ms)
            _constituent_cache[cache_key] = df
            return df

    async def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        outputsize: int,
        since_ms: int | None = None,
    ) -> pd.DataFrame:
        canon = resolve_composite(symbol)
        if canon is None:
            raise ProviderError(f"Unknown composite index symbol: {symbol}")

        needed = _required_constituents(canon)
        tasks = [
            self._fetch_constituent(coin, interval, outputsize, since_ms)
            for coin in needed
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        frames: dict[str, pd.DataFrame] = {}
        errors: list[ tuple[str, BaseException] ] = []
        for coin, res in zip(needed, results):
            if isinstance(res, BaseException):
                errors.append((coin, res))
            elif isinstance(res, pd.DataFrame) and not res.empty:
                frames[coin] = res

        # Primary anchor coins must be available
        primary_Anchors = [c for c in ("BTC", "ETH", "SOL") if c in needed]
        for anchor in primary_Anchors:
            if anchor not in frames:
                if errors:
                    first_err = errors[0][1]
                    if isinstance(first_err, ProviderError):
                        raise first_err
                    raise ProviderError(f"Failed to load constituent {anchor}USDT for {canon}: {first_err}") from first_err
                raise ProviderError(f"No constituent data returned for {canon} ({interval})")

        if not frames:
            raise ProviderError(f"No constituent data available for {canon} ({interval})")

        # Determine common master datetime index:
        # Intersect primary anchor indices so timestamps are strictly aligned,
        # then reindex + ffill/bfill secondary constituents so older history is preserved.
        master_index: pd.DatetimeIndex | None = None
        for anchor in primary_Anchors:
            idx = frames[anchor].index
            master_index = idx if master_index is None else master_index.intersection(idx)

        if master_index is None or len(master_index) == 0:
            # Fallback to union if intersection is empty
            master_index = frames[next(iter(frames))].index

        master_index = master_index.sort_values()

        aligned: dict[str, pd.DataFrame] = {}
        for coin, df in frames.items():
            sub = df.reindex(master_index).ffill().bfill()
            aligned[coin] = sub

        cal = await _fetch_global_calibration()
        df_out = self._compute_composite_df(canon, aligned, master_index, cal)

        if since_ms is not None:
            df_out = df_out[df_out.index >= pd.Timestamp(since_ms, unit="ms", tz="UTC")]
            return df_out[["open", "high", "low", "close", "volume"]]
        return df_out[["open", "high", "low", "close", "volume"]].tail(outputsize)

    def _compute_composite_df(
        self,
        canon: str,
        aligned: dict[str, pd.DataFrame],
        index: pd.DatetimeIndex,
        cal: dict[str, float],
    ) -> pd.DataFrame:
        n = len(index)
        zeros = np.zeros(n, dtype=float)

        def coin_mcap_ohlc(coin: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            """Return (open_b, high_b, low_b, close_b, usd_vol_b) in Billions USD."""
            df = aligned.get(coin)
            if df is None:
                return zeros, zeros, zeros, zeros, zeros
            sup_b = SUPPLY_BILLIONS[coin]
            o = df["open"].to_numpy(dtype=float) * sup_b
            h = df["high"].to_numpy(dtype=float) * sup_b
            l = df["low"].to_numpy(dtype=float) * sup_b
            c = df["close"].to_numpy(dtype=float) * sup_b
            v = df["volume"].to_numpy(dtype=float) * df["close"].to_numpy(dtype=float) / 1e9
            return o, h, l, c, v

        def coin_price_ohlc(coin: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            df = aligned[coin]
            o = df["open"].to_numpy(dtype=float)
            h = df["high"].to_numpy(dtype=float)
            l = df["low"].to_numpy(dtype=float)
            c = df["close"].to_numpy(dtype=float)
            v = df["volume"].to_numpy(dtype=float) * c / 1e9
            return o, h, l, c, v

        # --- Direct Pair Ratios ---
        if canon in ("ETHBTC", "SOLBTC", "SOLETH"):
            num_coin, den_coin = {
                "ETHBTC": ("ETH", "BTC"),
                "SOLBTC": ("SOL", "BTC"),
                "SOLETH": ("SOL", "ETH"),
            }[canon]
            no, nh, nl, nc, nv = coin_price_ohlc(num_coin)
            do, dh, dl, dc, dv = coin_price_ohlc(den_coin)
            open_s, high_s, low_s, close_s = _ratio_ohlc(no, nh, nl, nc, do, dh, dl, dc, scale=1.0)
            vol_s = nv + dv
            return _pack_ohlcv(index, open_s, high_s, low_s, close_s, vol_s)

        # --- DeFi Basket Market Cap & DEFIETH ---
        eth_o, eth_h, eth_l, eth_c, eth_v = coin_mcap_ohlc("ETH")
        sol_o, sol_h, sol_l, sol_c, sol_v = coin_mcap_ohlc("SOL")
        avax_o, avax_h, avax_l, avax_c, avax_v = coin_mcap_ohlc("AVAX")
        link_o, link_h, link_l, link_c, link_v = coin_mcap_ohlc("LINK")
        uni_o, uni_h, uni_l, uni_c, uni_v = coin_mcap_ohlc("UNI")
        aave_o, aave_h, aave_l, aave_c, aave_v = coin_mcap_ohlc("AAVE")

        defi_o = _DEFI_BASKET_MULT * (uni_o + aave_o + link_o + 0.35 * avax_o + 0.12 * sol_o + 0.05 * eth_o)
        defi_h = _DEFI_BASKET_MULT * (uni_h + aave_h + link_h + 0.35 * avax_h + 0.12 * sol_h + 0.05 * eth_h)
        defi_l = _DEFI_BASKET_MULT * (uni_l + aave_l + link_l + 0.35 * avax_l + 0.12 * sol_l + 0.05 * eth_l)
        defi_c = _DEFI_BASKET_MULT * (uni_c + aave_c + link_c + 0.35 * avax_c + 0.12 * sol_c + 0.05 * eth_c)
        defi_v = uni_v + aave_v + link_v + avax_v

        if canon == "TOTALDEFI":
            return _pack_ohlcv(index, defi_o, defi_h, defi_l, defi_c, defi_v)

        if canon == "DEFIETH":
            open_s, high_s, low_s, close_s = _ratio_ohlc(
                defi_o, defi_h, defi_l, defi_c,
                eth_o, eth_h, eth_l, eth_c,
                scale=100.0,
            )
            return _pack_ohlcv(index, open_s, high_s, low_s, close_s, defi_v + eth_v)

        # --- Full Market Cap & Dominance Synthesis ---
        btc_o, btc_h, btc_l, btc_c, btc_v = coin_mcap_ohlc("BTC")
        bnb_o, bnb_h, bnb_l, bnb_c, bnb_v = coin_mcap_ohlc("BNB")
        xrp_o, xrp_h, xrp_l, xrp_c, xrp_v = coin_mcap_ohlc("XRP")
        doge_o, doge_h, doge_l, doge_c, doge_v = coin_mcap_ohlc("DOGE")
        ada_o, ada_h, ada_l, ada_c, ada_v = coin_mcap_ohlc("ADA")
        trx_o, trx_h, trx_l, trx_c, trx_v = coin_mcap_ohlc("TRX")

        usdt_b = float(cal.get("usdt_b", USDT_B))
        usdc_b = float(cal.get("usdc_b", USDC_B))
        stables_b = float(cal.get("stables_b", STABLES_B))

        # Major altcoins in Top 10 (excluding BTC, ETH, USDT, USDC)
        major_alts_o = sol_o + bnb_o + xrp_o + doge_o + ada_o + trx_o
        major_alts_h = sol_h + bnb_h + xrp_h + doge_h + ada_h + trx_h
        major_alts_l = sol_l + bnb_l + xrp_l + doge_l + ada_l + trx_l
        major_alts_c = sol_c + bnb_c + xrp_c + doge_c + ada_c + trx_c
        major_alts_v = sol_v + bnb_v + xrp_v + doge_v + ada_v + trx_v

        # Mid/small-cap proxy basket for OTHERS (Ex-Top 10)
        mid_o = avax_o + link_o + uni_o + aave_o
        mid_h = avax_h + link_h + uni_h + aave_h
        mid_l = avax_l + link_l + uni_l + aave_l
        mid_c = avax_c + link_c + uni_c + aave_c
        mid_v = avax_v + link_v + uni_v + aave_v

        others_o = _OTHERS_MIDCAP_MULT * mid_o + _OTHERS_MAJOR_ALT_MULT * major_alts_o
        others_h = _OTHERS_MIDCAP_MULT * mid_h + _OTHERS_MAJOR_ALT_MULT * major_alts_h
        others_l = _OTHERS_MIDCAP_MULT * mid_l + _OTHERS_MAJOR_ALT_MULT * major_alts_l
        others_c = _OTHERS_MIDCAP_MULT * mid_c + _OTHERS_MAJOR_ALT_MULT * major_alts_c
        others_v = mid_v + 0.25 * major_alts_v

        # Optional live global market cap calibration on the tail basket
        total_target_b = cal.get("total_target_b")
        if total_target_b and n > 0:
            raw_last_total = float(btc_c[-1] + eth_c[-1] + major_alts_c[-1] + others_c[-1] + stables_b)
            if raw_last_total > 0 and float(others_c[-1]) > 0:
                desired_others = float(total_target_b) - float(btc_c[-1] + eth_c[-1] + major_alts_c[-1] + stables_b)
                scale = float(np.clip(desired_others / float(others_c[-1]), 0.5, 2.0))
                others_o = others_o * scale
                others_h = others_h * scale
                others_l = others_l * scale
                others_c = others_c * scale

        # Aggregate Market Cap series (in Billions USD)
        total3_es_o = major_alts_o + others_o
        total3_es_h = major_alts_h + others_h
        total3_es_l = major_alts_l + others_l
        total3_es_c = major_alts_c + others_c
        total3_v = major_alts_v + others_v

        total3_o = total3_es_o + stables_b
        total3_h = total3_es_h + stables_b
        total3_l = total3_es_l + stables_b
        total3_c = total3_es_c + stables_b

        total2_es_o = eth_o + total3_es_o
        total2_es_h = eth_h + total3_es_h
        total2_es_l = eth_l + total3_es_l
        total2_es_c = eth_c + total3_es_c
        total2_v = eth_v + total3_v

        total2_o = eth_o + total3_o
        total2_h = eth_h + total3_h
        total2_l = eth_l + total3_l
        total2_c = eth_c + total3_c

        totales_o = btc_o + total2_es_o
        totales_h = btc_h + total2_es_h
        totales_l = btc_l + total2_es_l
        totales_c = btc_c + total2_es_c
        total_v = btc_v + total2_v

        total_o = btc_o + total2_o
        total_h = btc_h + total2_h
        total_l = btc_l + total2_l
        total_c = btc_c + total2_c

        # --- Market Cap Index Dispatch ---
        if canon == "TOTAL":
            return _pack_ohlcv(index, total_o, total_h, total_l, total_c, total_v)
        if canon == "TOTAL2":
            return _pack_ohlcv(index, total2_o, total2_h, total2_l, total2_c, total2_v)
        if canon == "TOTAL3":
            return _pack_ohlcv(index, total3_o, total3_h, total3_l, total3_c, total3_v)
        if canon == "TOTALES":
            return _pack_ohlcv(index, totales_o, totales_h, totales_l, totales_c, total_v)
        if canon == "TOTAL2ES":
            return _pack_ohlcv(index, total2_es_o, total2_es_h, total2_es_l, total2_es_c, total2_v)
        if canon == "TOTAL3ES":
            return _pack_ohlcv(index, total3_es_o, total3_es_h, total3_es_l, total3_es_c, total3_v)
        if canon == "OTHERS":
            return _pack_ohlcv(index, others_o, others_h, others_l, others_c, others_v)

        # --- Dominance Index Dispatch (0.0 to 100.0 PCT) ---
        if canon == "BTC.D":
            o, h, l, c = _ratio_ohlc(btc_o, btc_h, btc_l, btc_c, total_o, total_h, total_l, total_c, scale=100.0, is_pct=True)
            return _pack_ohlcv(index, o, h, l, c, total_v)
        if canon == "ETH.D":
            o, h, l, c = _ratio_ohlc(eth_o, eth_h, eth_l, eth_c, total_o, total_h, total_l, total_c, scale=100.0, is_pct=True)
            return _pack_ohlcv(index, o, h, l, c, total_v)
        if canon == "USDT.D":
            o, h, l, c = _const_num_dominance_ohlc(usdt_b, total_o, total_h, total_l, total_c)
            return _pack_ohlcv(index, o, h, l, c, total_v)
        if canon == "USDC.D":
            o, h, l, c = _const_num_dominance_ohlc(usdc_b, total_o, total_h, total_l, total_c)
            return _pack_ohlcv(index, o, h, l, c, total_v)
        if canon == "STABLE.C.D":
            o, h, l, c = _const_num_dominance_ohlc(stables_b, total_o, total_h, total_l, total_c)
            return _pack_ohlcv(index, o, h, l, c, total_v)
        if canon == "OTHERS.D":
            o, h, l, c = _ratio_ohlc(others_o, others_h, others_l, others_c, total_o, total_h, total_l, total_c, scale=100.0, is_pct=True)
            return _pack_ohlcv(index, o, h, l, c, others_v)
        if canon == "TOTAL3.D":
            o, h, l, c = _ratio_ohlc(total3_o, total3_h, total3_l, total3_c, total_o, total_h, total_l, total_c, scale=100.0, is_pct=True)
            return _pack_ohlcv(index, o, h, l, c, total3_v)
        if canon == "ALTS.D":
            o, h, l, c = _ratio_ohlc(total2_o, total2_h, total2_l, total2_c, total_o, total_h, total_l, total_c, scale=100.0, is_pct=True)
            return _pack_ohlcv(index, o, h, l, c, total2_v)

        raise ProviderError(f"Unsupported composite index: {canon}")

    async def search_symbols(self, query: str) -> list[dict]:
        return search_composites(query)


def _ratio_ohlc(
    no: np.ndarray,
    nh: np.ndarray,
    nl: np.ndarray,
    nc: np.ndarray,
    do: np.ndarray,
    dh: np.ndarray,
    dl: np.ndarray,
    dc: np.ndarray,
    scale: float = 1.0,
    is_pct: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute realistic OHLC arrays for (N / D * scale) with strict wick invariants."""
    do_safe = np.maximum(do, 1e-12)
    dh_safe = np.maximum(dh, 1e-12)
    dl_safe = np.maximum(dl, 1e-12)
    dc_safe = np.maximum(dc, 1e-12)

    open_s = (no / do_safe) * scale
    close_s = (nc / dc_safe) * scale

    d_body_high = np.maximum(do_safe, dc_safe)
    d_body_low = np.minimum(do_safe, dc_safe)
    n_body_high = np.maximum(no, nc)
    n_body_low = np.minimum(no, nc)

    # Blend numerator wick vs denominator body and numerator body vs denominator wick
    up_wick_1 = (nh / d_body_high) * scale
    up_wick_2 = (n_body_high / dl_safe) * scale
    dn_wick_1 = (nl / d_body_low) * scale
    dn_wick_2 = (n_body_low / dh_safe) * scale

    high_s = 0.5 * (up_wick_1 + up_wick_2)
    low_s = 0.5 * (dn_wick_1 + dn_wick_2)

    high_s = np.maximum(np.maximum(open_s, close_s), high_s)
    low_s = np.minimum(np.minimum(open_s, close_s), low_s)
    low_s = np.maximum(low_s, 1e-8)

    if is_pct:
        high_s = np.minimum(high_s, 100.0)
        open_s = np.clip(open_s, 1e-8, 100.0)
        close_s = np.clip(close_s, 1e-8, 100.0)
        low_s = np.minimum(low_s, np.minimum(open_s, close_s))

    return open_s, high_s, low_s, close_s


def _const_num_dominance_ohlc(
    const_b: float,
    do: np.ndarray,
    dh: np.ndarray,
    dl: np.ndarray,
    dc: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute OHLC for constant-numerator stablecoin dominance (const_b / TOTAL * 100)."""
    do_safe = np.maximum(do, 1e-12)
    dh_safe = np.maximum(dh, 1e-12)
    dl_safe = np.maximum(dl, 1e-12)
    dc_safe = np.maximum(dc, 1e-12)

    open_s = (const_b / do_safe) * 100.0
    close_s = (const_b / dc_safe) * 100.0
    # When TOTAL hits its low, stablecoin dominance hits its high, and vice versa
    high_s = (const_b / dl_safe) * 100.0
    low_s = (const_b / dh_safe) * 100.0

    high_s = np.maximum(np.maximum(open_s, close_s), high_s)
    low_s = np.minimum(np.minimum(open_s, close_s), low_s)
    low_s = np.maximum(low_s, 1e-8)
    high_s = np.minimum(high_s, 100.0)
    return open_s, high_s, low_s, close_s


def _pack_ohlcv(
    index: pd.DatetimeIndex,
    open_s: np.ndarray,
    high_s: np.ndarray,
    low_s: np.ndarray,
    close_s: np.ndarray,
    vol_s: np.ndarray,
) -> pd.DataFrame:
    """Enforce strict OHLC invariants on every bar and return the canonical DataFrame."""
    high = np.maximum(np.maximum(open_s, close_s), high_s)
    low = np.minimum(np.minimum(open_s, close_s), low_s)
    low = np.maximum(low, 1e-8)
    open_clean = np.maximum(open_s, 1e-8)
    close_clean = np.maximum(close_s, 1e-8)
    high = np.maximum(np.maximum(open_clean, close_clean), high)
    low = np.minimum(np.minimum(open_clean, close_clean), low)
    vol_clean = np.maximum(np.nan_to_num(vol_s, nan=0.0, posinf=0.0, neginf=0.0), 0.0)

    return pd.DataFrame(
        {
            "open": open_clean,
            "high": high,
            "low": low,
            "close": close_clean,
            "volume": vol_clean,
        },
        index=index,
    )


composite_provider = CompositeProvider()
