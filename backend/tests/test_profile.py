"""Account profile (profiles.py) and wallet history (wealth.py)."""
import base64
import io

import pytest
from PIL import Image

from app import profiles
from app.trading.onchain import wealth


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "_STORE_FILE", tmp_path / "p.json")
    monkeypatch.setattr(profiles, "_AVATARS", tmp_path / "av")
    monkeypatch.setattr(wealth, "_STORE_FILE", tmp_path / "w.json")
    profiles.reset_for_tests()
    wealth.reset_for_tests()
    yield


def test_defaults_from_email_and_unique_handles():
    a = profiles.get("u1", "lorenzo@example.com")
    b = profiles.get("u2", "lorenzo@other.com")
    assert a["handle"] == "lorenzo" and b["handle"] != "lorenzo" and a["display_name"] == "lorenzo"
    with pytest.raises(ValueError):
        profiles.update("u2", handle="Lorenzo")
    with pytest.raises(ValueError):
        profiles.update("u2", handle="a b")
    p = profiles.update("u2", display_name="  Kr$n  ", handle="@WattTheHodl", bio="gm " * 100)
    assert p["display_name"] == "Kr$n" and p["handle"] == "WattTheHodl" and len(p["bio"]) <= profiles.BIO_MAX


def test_avatar_is_reencoded_square_webp():
    buf = io.BytesIO()
    Image.new("RGB", (640, 400), (200, 30, 30)).save(buf, "PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    p = profiles.set_avatar("u1", url)
    img = Image.open(profiles.avatar_path("u1"))
    assert img.format == "WEBP" and img.size == (profiles.AVATAR_PX, profiles.AVATAR_PX)
    assert profiles.public("u1", p)["avatar_url"].endswith("?v=1")
    with pytest.raises(ValueError):
        profiles.set_avatar("u1", "data:text/html;base64,PGgxPg==")
    with pytest.raises(ValueError):
        profiles.set_avatar("u1", "data:image/png;base64," + base64.b64encode(b"not an image").decode())


def test_wealth_series_thins_with_age_and_ranges():
    now = 1_790_000_000
    for i in range(0, 60 * 86_400, 600):      # a reading every 10 min for 60 days
        wealth.record("u1", 100 + i / 86_400, now=now - 60 * 86_400 + i)
    rows = wealth.series("u1", "all", now=now)
    assert len(rows) < 30 + 28 * 24 + 2 * 144 + 10
    assert len(wealth.series("u1", "24h", now=now)) >= 140
    assert wealth.change("u1", "7d", 200.0, now=now) == pytest.approx(200.0 - wealth.series("u1", "7d", now=now)[0][1])


def test_a_chain_that_does_not_answer_counts_at_its_last_value():
    now = 1_790_000_000
    assert wealth.combine("u1", {"solana": 100.0, "bsc": 5.0}, [], now=now) == 105.0
    # bsc down 10 minutes later: its last value stands in
    assert wealth.combine("u1", {"solana": 110.0}, ["bsc"], now=now + 600) == 115.0
    # down for longer than CARRY_S: no point at all, rather than a fake dip
    assert wealth.combine("u1", {"solana": 110.0}, ["bsc"], now=now + wealth.CARRY_S + 700) is None
    # a chain never seen with a value is not a loss
    assert wealth.combine("u2", {"solana": 1.0}, ["base"], now=now) == 1.0


def test_old_readings_are_dropped(tmp_path, monkeypatch):
    import json
    f = tmp_path / "old.json"
    f.write_text(json.dumps({"u1": [[1, 2.0]]}))           # v1 file: a bare dict of series
    monkeypatch.setattr(wealth, "_STORE_FILE", f)
    wealth.reset_for_tests()
    wealth._load()
    assert wealth.series("u1", "all") == []
