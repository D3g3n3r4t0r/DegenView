"""The public project page: open without an account, rules taken from the radar."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.trading.onchain import radar


def test_page_is_public_and_leads_to_the_app():
    resp = TestClient(main.app).get("/engn")
    assert resp.status_code == 200
    assert "ENTER THE APP" in resp.text
    assert 'href="/onchain-app.html"' in resp.text


def test_rules_come_from_the_radar_not_from_the_page():
    html = TestClient(main.app).get("/engn").text
    assert "{{" not in html
    assert f"≤ {radar.AGE_MAX_DAYS} days" in html
    assert f"≥ {radar.MIN_PROFIT_FACTOR:g}" in html
