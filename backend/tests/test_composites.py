"""Unit tests for TradingView Composite Tickers (`composites.py` & `composites_snapshot.py`)."""
from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd

from app.providers import composites, composites_snapshot
from app.providers.composites import (
    ALL_CONSTITUENTS,
    COMPOSITES,
    get_composite_meta,
    is_composite_symbol,
    resolve_composite,
    search_composites,
)
from app.providers.mexc import MexcProvider, format_symbol

EXPECTED_20_COMPOSITES = (
    "TOTAL",
    "TOTAL2",
    "TOTAL3",
    "TOTALES",
    "TOTAL2ES",
    "TOTAL3ES",
    "OTHERS",
    "TOTALDEFI",
    "BTC.D",
    "ETH.D",
    "USDT.D",
    "USDC.D",
    "STABLE.C.D",
    "OTHERS.D",
    "TOTAL3.D",
    "ALTS.D",
    "ETHBTC",
    "SOLBTC",
    "SOLETH",
    "DEFIETH",
)

# Realistic baseline prices for deterministic constituent OHLCV generation
_BASE_PRICES: dict[str, float] = {
    "BTCUSDT": 85_000.0,
    "ETHUSDT": 2_200.0,
    "SOLUSDT": 145.0,
    "BNBUSDT": 610.0,
    "XRPUSDT": 2.15,
    "ADAUSDT": 0.72,
    "DOGEUSDT": 0.175,
    "TRXUSDT": 0.235,
    "AVAXUSDT": 22.5,
    "LINKUSDT": 15.8,
    "UNIUSDT": 7.40,
    "AAVEUSDT": 185.0,
}


def _make_synthetic_ohlcv(pair: str, n: int = 50) -> pd.DataFrame:
    """Create a deterministic, realistic OHLCV DataFrame for a constituent pair."""
    base = _BASE_PRICES.get(pair, 10.0)
    idx = pd.date_range("2026-01-01 00:00:00", periods=n, freq="1h", tz="UTC")
    seed = sum(ord(ch) for ch in pair)
    t = np.linspace(0.0, 4.0 * np.pi, n)
    wave = 1.0 + 0.04 * np.sin(t + (seed % 7) * 0.4) + 0.015 * np.cos(2.0 * t)

    open_p = base * wave
    close_p = base * (wave + 0.008 * np.sin(3.0 * t + (seed % 5)))
    high_p = np.maximum(open_p, close_p) * (1.0 + 0.012 + 0.003 * (np.sin(t) + 1.0))
    low_p = np.minimum(open_p, close_p) * (1.0 - 0.011 - 0.003 * (np.cos(t) + 1.0))
    vol = (1_000_000.0 / max(base, 0.1)) * (1.0 + 0.25 * np.abs(np.sin(t)))

    return pd.DataFrame(
        {
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": vol,
        },
        index=idx,
    )


def test_all_20_composites_registered():
    assert len(COMPOSITES) == 20
    for sym in EXPECTED_20_COMPOSITES:
        assert sym in COMPOSITES, f"Missing composite ticker: {sym}"
        meta = COMPOSITES[sym]
        assert meta["symbol"] == sym
        assert isinstance(meta["name"], str) and len(meta["name"]) > 0
        assert meta["category"] in ("market_cap", "dominance", "ratio")
        assert meta["unit"] in ("B_USD", "PCT", "RATIO")
        assert isinstance(meta["formula"], str) and len(meta["formula"]) > 0
        assert isinstance(meta["description"], str) and len(meta["description"]) > 10

        # Helper metadata functions should agree
        assert is_composite_symbol(sym) is True
        meta_copy = get_composite_meta(sym)
        assert meta_copy is not None
        assert meta_copy["symbol"] == sym


def test_aliases_resolution():
    assert resolve_composite("btcd") == "BTC.D"
    assert resolve_composite("BTCDOM") == "BTC.D"
    assert resolve_composite("total3") == "TOTAL3"
    assert resolve_composite("totales") == "TOTALES"
    assert resolve_composite("stable.d") == "STABLE.C.D"
    assert resolve_composite("others.d") == "OTHERS.D"
    assert resolve_composite("eth/btc") == "ETHBTC"
    assert resolve_composite("CRYPTOCAP:TOTAL2") == "TOTAL2"
    assert resolve_composite("BTCUSDT") is None
    assert resolve_composite("") is None
    assert is_composite_symbol("BTCUSDT") is False


def test_format_mexc_symbol_preserves_composites():
    assert format_symbol("TOTAL3") == "TOTAL3"
    assert format_symbol("TOTALES") == "TOTALES"
    assert format_symbol("BTC.D") == "BTC.D"
    assert format_symbol("btcd") == "BTC.D"
    assert format_symbol("BTC") == "BTCUSDT"
    assert format_symbol("ETH/USDT") == "ETHUSDT"


def test_composite_ohlcv_synthesis_invariants(monkeypatch):
    composites._constituent_cache.clear()
    composites._constituent_locks.clear()
    composites._global_cal_cache.clear()

    # Keep calibration deterministic offline
    composites._global_cal_cache["cal"] = {
        "usdt_b": composites.USDT_B,
        "usdc_b": composites.USDC_B,
        "stables_b": composites.STABLES_B,
        "others_scale": 1.0,
    }

    class FakeMexc(MexcProvider):
        async def fetch_ohlcv(
            self,
            symbol: str,
            interval: str,
            outputsize: int,
            since_ms: int | None = None,
        ) -> pd.DataFrame:
            return _make_synthetic_ohlcv(symbol, n=outputsize)

    monkeypatch.setattr(composites.composite_provider, "_mexc", FakeMexc())
    frames: dict[str, pd.DataFrame] = {}

    async def _run_all():
        for sym in EXPECTED_20_COMPOSITES:
            frames[sym] = await composites.composite_provider.fetch_ohlcv(sym, "1h", 50)

    asyncio.run(_run_all())

    for sym in EXPECTED_20_COMPOSITES:
        df = frames[sym]
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert len(df) == 50
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert not df.isna().any().any(), f"NaN values found in {sym}"

        # Strict OHLC invariants on every bar
        assert (df["high"] >= df["open"]).all(), f"{sym}: high < open"
        assert (df["high"] >= df["close"]).all(), f"{sym}: high < close"
        assert (df["low"] <= df["open"]).all(), f"{sym}: low > open"
        assert (df["low"] <= df["close"]).all(), f"{sym}: low > close"
        assert (df["low"] > 0).all(), f"{sym}: low <= 0"
        assert (df["volume"] >= 0).all(), f"{sym}: volume < 0"

    # Cross-composite mathematical invariants on every bar
    for col in ("open", "high", "low", "close"):
        assert (frames["TOTAL"][col] > frames["TOTAL2"][col]).all()
        assert (frames["TOTAL2"][col] > frames["TOTAL3"][col]).all()
        assert (frames["TOTAL3"][col] > 0).all()
        assert (frames["TOTAL"][col] > frames["TOTALES"][col]).all()
        assert (frames["TOTALES"][col] > 0).all()
        assert (frames["TOTAL2"][col] > frames["TOTAL2ES"][col]).all()
        assert (frames["TOTAL3"][col] > frames["TOTAL3ES"][col]).all()

    for dom_sym in ("BTC.D", "ETH.D", "USDT.D", "USDC.D", "STABLE.C.D", "OTHERS.D", "TOTAL3.D", "ALTS.D"):
        dom_df = frames[dom_sym]
        assert (dom_df["low"] > 0.0).all(), f"{dom_sym} low <= 0"
        assert (dom_df["high"] <= 100.0).all(), f"{dom_sym} high > 100"
        assert (dom_df["open"] > 0.0).all() and (dom_df["open"] < 100.0).all()
        assert (dom_df["close"] > 0.0).all() and (dom_df["close"] < 100.0).all()

    # BTC.D + ALTS.D == 100% on open and close
    diff_open = (frames["BTC.D"]["open"] + frames["ALTS.D"]["open"] - 100.0).abs()
    diff_close = (frames["BTC.D"]["close"] + frames["ALTS.D"]["close"] - 100.0).abs()
    assert (diff_open < 0.5).all()
    assert (diff_close < 0.5).all()


def test_search_composites():
    total_matches = search_composites("TOTAL")
    total_symbols = [m["symbol"] for m in total_matches]
    for expected in ("TOTAL", "TOTAL2", "TOTAL3", "TOTALES", "TOTAL2ES", "TOTAL3ES", "TOTALDEFI", "TOTAL3.D"):
        assert expected in total_symbols
    assert total_symbols[0] == "TOTAL"

    btcd_matches = search_composites("BTC.D")
    btcd_symbols = [m["symbol"] for m in btcd_matches]
    assert "BTC.D" in btcd_symbols
    assert btcd_symbols[0] == "BTC.D"

    alias_matches = search_composites("BTCDOM")
    assert alias_matches and alias_matches[0]["symbol"] == "BTC.D"

    assert search_composites("") == []


def test_composites_snapshot_and_regime(monkeypatch):
    composites_snapshot._snapshot_cache.clear()
    composites_snapshot._snapshot_lock = None
    composites._global_cal_cache["cal"] = {
        "usdt_b": composites.USDT_B,
        "usdc_b": composites.USDC_B,
        "stables_b": composites.STABLES_B,
        "others_scale": 1.0,
    }

    async def fake_fetch_prices():
        prices_now = {c: _BASE_PRICES[f"{c}USDT"] for c in ALL_CONSTITUENTS}
        # Simulate altcoin expansion: BTC flat (+0.2%), alts up (+5%)
        prices_24h = {}
        for c in ALL_CONSTITUENTS:
            if c == "BTC":
                prices_24h[c] = prices_now[c] / 1.002
            else:
                prices_24h[c] = prices_now[c] / 1.05
        return prices_now, prices_24h

    monkeypatch.setattr(composites_snapshot, "_fetch_all_constituent_24h_prices", fake_fetch_prices)

    snap = asyncio.run(composites_snapshot.get_composites_snapshot(force=True))
    assert snap["count"] == 20
    assert len(snap["items"]) == 20
    assert set(snap["by_symbol"].keys()) == set(EXPECTED_20_COMPOSITES)
    assert snap["regime"]["label"] == "Altseason Expansion"
    assert snap["regime"]["tone"] == "bull"
    assert "TOTAL" in snap["regime"]["summary"]
