"""Chart indicators against their TradingView definitions."""
import numpy as np
import pandas as pd

from app.analysis.indicators import bull_market_support_band, compute_indicators


def _daily(n=400, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")   # a Monday
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": rng.uniform(1, 10, n)}, index=idx)


def _weekly(daily):
    return daily.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})


def _ind(df, interval):
    return {i.name: np.array([np.nan if v is None else v for v in i.values]) for i in compute_indicators(df, interval)}


def test_bollinger_uses_population_deviation_like_the_strategy():
    df = _daily()
    c = df["close"]
    upper = c.rolling(20).mean() + 2 * c.rolling(20).std(ddof=0)
    got = _ind(df, "1d")["BB_upper"]
    assert np.nanmax(np.abs(got - upper.values)) < 1e-9


def test_vwap_on_daily_is_not_the_bar_typical_price():
    df = _daily()
    vwap = _ind(df, "1d")["VWAP"]
    tp = ((df.high + df.low + df.close) / 3).values
    # Monthly anchor: only each month's first bar equals its own typical price.
    same = np.isclose(vwap, tp)
    assert same.sum() <= 14
    assert same[0]


def test_bmsb_never_reads_a_close_after_the_candle():
    df = _daily()
    weekly = _weekly(df)
    full = {i.name: i.values for i in bull_market_support_band(df, weekly)}
    k = 300
    cut = df.iloc[: k + 1]
    part = {i.name: i.values for i in bull_market_support_band(cut, _weekly(cut))}
    for name in ("BMSB_SMA20W", "BMSB_EMA21W"):
        assert full[name][k] is not None
        assert abs(full[name][k] - part[name][k]) < 1e-9


def test_bmsb_on_weekly_chart_is_plain_sma_and_ema():
    w = _weekly(_daily())
    out = {i.name: np.array([np.nan if v is None else v for v in i.values]) for i in bull_market_support_band(w, w)}
    sma = w.close.rolling(20).mean().values
    ema = w.close.ewm(span=21, adjust=False).mean().values
    ok = ~np.isnan(out["BMSB_SMA20W"])
    assert ok.sum() > 0
    assert np.allclose(out["BMSB_SMA20W"][ok], sma[ok])
    assert np.allclose(out["BMSB_EMA21W"][ok], ema[ok])
