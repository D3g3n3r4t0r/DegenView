"""Un 429 di GeckoTerminal non deve mai diventare "nessun dato" (FLIP su
Robinhood: grafico vuoto mentre DexScreener lo mostrava)."""
import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.providers import dexscreener
from app.providers.base import NoDataYet
from app.providers.dexscreener import DexScreenerProvider, GeckoBusy, gecko_get

URL = "https://gecko.test/networks/robinhood/pools/0xpool/ohlcv/minute"
OHLCV = {"data": {"attributes": {"ohlcv_list": [[1_790_199_480, 1, 2, 0.5, 1.5, 10]]}}}


def _client(statuses: list[int], calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        status = statuses.pop(0) if statuses else 200
        return httpx.Response(status, json=OHLCV if status == 200 else {"status": {"error_code": status}})

    real = httpx.AsyncClient

    def make(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)
    return make


@pytest.fixture(autouse=True)
def _no_pauses():
    real_sleep = asyncio.sleep
    with patch.object(dexscreener.asyncio, "sleep", lambda s: real_sleep(0)):
        yield


def test_rate_limit_is_retried_not_read_as_empty():
    calls: list[str] = []
    with patch("httpx.AsyncClient", _client([429, 429], calls)):
        payload = asyncio.run(gecko_get(URL, {"aggregate": 1}))
    assert payload == OHLCV
    assert len(calls) == 3


def test_same_request_is_served_once():
    calls: list[str] = []

    async def both():
        return await asyncio.gather(gecko_get(URL), gecko_get(URL))

    with patch("httpx.AsyncClient", _client([], calls)):
        first, second = asyncio.run(both())
        asyncio.run(gecko_get(URL))
    assert first == second == OHLCV
    assert len(calls) == 1


def test_refusal_falls_back_to_last_good_answer():
    calls: list[str] = []
    with patch("httpx.AsyncClient", _client([], calls)):
        asyncio.run(gecko_get(URL))
    key = next(iter(dexscreener._gecko_seen))
    ts, payload = dexscreener._gecko_seen[key]
    dexscreener._gecko_seen[key] = (ts - 60, payload)
    with patch("httpx.AsyncClient", _client([429, 429, 429], calls)):
        assert asyncio.run(gecko_get(URL)) == OHLCV


def test_refusal_without_history_is_busy_not_missing_pool():
    with patch("httpx.AsyncClient", _client([429, 429, 429], [])):
        with pytest.raises(GeckoBusy):
            asyncio.run(gecko_get(URL))
    assert issubclass(GeckoBusy, NoDataYet)


def test_chart_candles_survive_a_rate_limit():
    provider = DexScreenerProvider(geckoterminal_base="https://gecko.test")
    with patch("httpx.AsyncClient", _client([429], [])):
        df = asyncio.run(provider.fetch_ohlcv("FLIP@robinhood:0x408af913f33fa1bb", "1m", 10))
    assert len(df) == 1 and df["close"].iloc[-1] == 1.5


def test_background_calls_leave_room_for_the_chart():
    now = dexscreener.time.monotonic()
    dexscreener._gecko_calls.extend([now] * dexscreener._GECKO_BACKGROUND_PER_MIN)

    async def urgent():
        dexscreener.gecko_urgent.set(True)
        await asyncio.wait_for(dexscreener._gecko_slot(), 0.5)

    asyncio.run(urgent())
    assert len(dexscreener._gecko_calls) == dexscreener._GECKO_BACKGROUND_PER_MIN + 1
