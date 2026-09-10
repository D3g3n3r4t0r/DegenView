from fastapi.testclient import TestClient

from app import auth, main


def test_symbols_search_includes_binance_results(monkeypatch):
    async def fake_search(self, query):
        return [{"symbol": "BTCUSDT", "name": "Bitcoin", "exchange": "Binance (USDT)"}]

    monkeypatch.setattr(main.binance_provider.__class__, "search_symbols", fake_search)
    monkeypatch.setattr(main.mexc_provider.__class__, "search_symbols", fake_search)
    monkeypatch.setattr(main.kucoin_provider.__class__, "search_symbols", fake_search)

    client = TestClient(main.app)
    main.app.dependency_overrides[auth.get_current_user] = lambda: object()
    try:
        resp = client.get("/api/symbols", params={"query": "BTC"})
    finally:
        main.app.dependency_overrides.clear()

    assert resp.status_code == 200
    providers = {item["provider"] for item in resp.json()}
    assert "binance" in providers
