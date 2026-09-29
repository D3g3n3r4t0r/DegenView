import pytest

from app.providers import dexscreener


@pytest.fixture(autouse=True)
def _fresh_gecko_gate():
    """La cache e il tetto di GeckoTerminal sono globali: un test non deve
    vedere le risposte finte di un altro, ne' aspettare il suo minuto."""
    dexscreener._gecko_seen.clear()
    dexscreener._gecko_calls.clear()
    yield
    dexscreener._gecko_seen.clear()
    dexscreener._gecko_calls.clear()


@pytest.fixture(autouse=True)
def _private_projects_db(monkeypatch, tmp_path):
    """The Gem Finder's project database is a file on the volume: every test
    gets its own, empty."""
    from app.trading.onchain import projects_db
    monkeypatch.setattr(projects_db, "_DB_FILE", tmp_path / "projects.db")
    yield


@pytest.fixture(autouse=True)
def _fresh_github_cache():
    """Stessa cosa per la cache e la quota di GitHub."""
    from app.trading.onchain import legit
    legit._gh_cache.clear()
    legit._gh_blocked.clear()
    yield
    legit._gh_cache.clear()
    legit._gh_blocked.clear()


@pytest.fixture(autouse=True)
def _onchain_wallets_on(monkeypatch):
    """Execution tests use made-up owner ids with no user behind them: treat
    their wallets as switched on. Tests of the switch itself re-patch this."""
    from app.trading.onchain import risk
    monkeypatch.setattr(risk, "_wallet_enabled", lambda owner_id, chain: True)
    yield
