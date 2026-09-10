"""Un 500 vero deve finire nel registro (server_errors.json) e restare
consultabile via GET /api/errors — senza bisogno di SSH sul server per
vederlo, che era l'intero motivo per cui esiste."""
from fastapi.testclient import TestClient

from app import auth, error_log, main
from app.models import User


def _user() -> User:
    return User(id="u-err", email="err@example.com", password_hash="x")


def test_unhandled_exception_is_recorded_and_readable(monkeypatch):
    # Cookie di sessione vero: l'handler dell'errore legge request.cookies
    # direttamente (dependency_overrides non lo raggiunge, non passa dalla
    # dependency injection di FastAPI), quindi serve un cookie che
    # _verify_session_cookie() accetti per davvero per verificare che
    # user_id finisca nel registro.
    user = _user()
    client = TestClient(main.app, raise_server_exceptions=False,
                         cookies={auth.SESSION_COOKIE: auth.make_session_cookie(user.id)})
    monkeypatch.setitem(auth._users, user.id, user)
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    try:
        def _boom(*a, **k):
            raise RuntimeError("credenziale corrotta, per la prova")

        monkeypatch.setattr(auth, "set_trading_credential", _boom)

        resp = client.patch("/api/auth/trading", json={
            "exchange": "mexc", "api_key": "k", "api_secret": "s",
            "passphrase": "", "enabled": True, "size_mode": "fixed_usdt", "size_value": 50,
        })
        assert resp.status_code == 500
        # Il body al client resta generico: niente traceback esposto a chi chiama.
        assert resp.json() == {"detail": "Internal Server Error"}

        listed = client.get("/api/errors").json()["errors"]
        assert listed, "l'errore non e' stato registrato"
        top = listed[0]
        assert top["exc_type"] == "RuntimeError"
        assert "credenziale corrotta" in top["message"]
        assert "RuntimeError" in top["traceback"]
        assert top["path"] == "/api/auth/trading"
        assert top["user_id"] == "u-err"
    finally:
        main.app.dependency_overrides.clear()


def test_recent_caps_and_orders_newest_first():
    error_log._errors.clear()
    for i in range(3):
        error_log.record(
            method="GET", path=f"/x/{i}", exc=ValueError(f"err{i}"), user_id=None,
        )
    out = error_log.recent(limit=10)
    assert [e["message"] for e in out] == ["err2", "err1", "err0"]
