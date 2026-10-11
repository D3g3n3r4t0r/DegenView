"""Manual archive save re-runs on the candles the Lab showed (board issue f3cdcc63)."""
import pandas as pd

from app.main import ArchiveIn, _slice_to_window


def _df():
    idx = pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC")
    return pd.DataFrame({"close": range(10)}, index=idx)


def _ms(day: int) -> int:
    return int(pd.Timestamp(f"2026-01-{day:02d}", tz="UTC").timestamp() * 1000)


def test_window_keeps_both_ends():
    out = _slice_to_window(_df(), _ms(3), _ms(6))
    assert list(out["close"]) == [2, 3, 4, 5]


def test_open_ended_window():
    assert len(_slice_to_window(_df(), _ms(8), None)) == 3
    assert len(_slice_to_window(_df(), None, None)) == 10


def test_archive_request_carries_the_window():
    req = ArchiveIn(symbol="BTCUSDT", strategy_name="x", data_start=1, data_end=2, intrabar=False)
    assert (req.data_start, req.data_end, req.intrabar) == (1, 2, False)
    assert ArchiveIn(symbol="BTCUSDT", strategy_name="x").data_start is None
