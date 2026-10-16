"""The on-chain app as it was on 15/10, kept for the accounts in
settings.onchain_v1_emails; everyone else gets the current app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, main

_PASSWORD = "app-v1-pass-123"


@pytest.fixture
def users(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(main.settings, "onchain_v1_emails", "Old@Example.com, x@example.com")
    auth._users.clear()
    auth.create_user("old@example.com", _PASSWORD)
    auth.create_user("new@example.com", _PASSWORD)
    yield


def _page(email: str | None) -> str:
    with TestClient(main.app) as client:
        if email:
            assert client.post("/api/auth/login", json={"email": email, "password": _PASSWORD}).status_code == 200
        resp = client.get("/onchain-app.html")
        assert resp.status_code == 200
        return resp.text


def test_listed_account_gets_the_frozen_app(users):
    html = _page("old@example.com")
    assert f'src="/static/onchain-v1/main.js?v={main._ASSET_VERSION}"' in html
    assert '"@onchain/main.js":"/static/onchain-v1/main.js' in html
    assert "/static/onchain/" not in html
    assert '"app_variant":"v1"' in html


def test_other_accounts_and_the_login_screen_get_the_current_app(users):
    for email in ("new@example.com", None):
        html = _page(email)
        assert f'src="/static/onchain/main.js?v={main._ASSET_VERSION}"' in html
        assert "/static/onchain-v1/" not in html


def test_every_frozen_module_the_page_imports_exists():
    names = {m.name for m in main._onchain_modules(main._ONCHAIN_V1_DIR)}
    assert "main.js" in names and "top.js" in names
