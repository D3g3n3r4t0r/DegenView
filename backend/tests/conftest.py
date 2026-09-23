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
