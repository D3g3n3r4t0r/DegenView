import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets
from fastapi import WebSocket

from app.providers.kraken import KrakenProvider

logger = logging.getLogger("kraken_stream")

WS_URL = "wss://ws.kraken.com/v2"
# Stesso limite del REST OHLC (vedi kraken.py): niente 1M, il feed live non
# ha nessun bisogno di una candela mensile in tempo reale.
_CANONICAL_TO_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
}
RECONNECT_DELAY_SECONDS = 3

_provider = KrakenProvider()


class KrakenStreamManager:
    """Relays Kraken's pubblico OHLC websocket v2 ai client collegati.

    Stessa semplificazione di MexcStreamManager: un solo (symbol, set di
    intervalli) e' "live" alla volta, adatta a un'app mono-utente.
    """

    def __init__(self) -> None:
        self._clients: dict[WebSocket, tuple[str, tuple]] = {}
        self._active_key: tuple[str, tuple] | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def add_client(self, ws: WebSocket, symbol: str, intervals: dict[str, str]) -> None:
        ws_symbol = await _provider.get_ws_symbol(symbol)
        if ws_symbol is None:
            return  # pair sconosciuto: il frontend resta sul polling
        key = (ws_symbol, tuple(sorted(intervals.items())))
        self._clients[ws] = key
        await self._ensure_subscription(key)

    async def remove_client(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)
        if not self._clients:
            await self._teardown()

    async def _ensure_subscription(self, key: tuple[str, tuple]) -> None:
        async with self._lock:
            if key == self._active_key and self._task and not self._task.done():
                return
            self._active_key = key
            if self._task:
                self._task.cancel()
            self._task = asyncio.create_task(self._run(key))

    async def _teardown(self) -> None:
        async with self._lock:
            if self._task:
                self._task.cancel()
            self._task = None
            self._active_key = None

    async def _run(self, key: tuple[str, tuple]) -> None:
        ws_symbol, interval_items = key
        tf_by_minutes: dict[int, str] = {}
        for tf_key, canonical_interval in interval_items:
            minutes = _CANONICAL_TO_MINUTES.get(canonical_interval)
            if minutes is None:
                continue  # intervallo sintetico (2D/3D/5D/1M): niente canale nativo
            tf_by_minutes[minutes] = tf_key

        if not tf_by_minutes:
            return

        while True:
            try:
                async with websockets.connect(WS_URL) as ws:
                    for minutes in tf_by_minutes:
                        await ws.send(json.dumps({
                            "method": "subscribe",
                            "params": {"channel": "ohlc", "symbol": [ws_symbol], "interval": minutes},
                        }))
                    async for message in ws:
                        await self._handle_message(message, ws_symbol, tf_by_minutes)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Kraken stream error for %s, reconnecting", ws_symbol)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _handle_message(self, raw, ws_symbol: str, tf_by_minutes: dict[int, str]) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(msg, dict) or msg.get("channel") != "ohlc":
            return

        dead: list[WebSocket] = []
        for row in msg.get("data") or []:
            tf_key = tf_by_minutes.get(row.get("interval"))
            if tf_key is None:
                continue
            try:
                ts = int(datetime.fromisoformat(
                    row["interval_begin"].replace("Z", "+00:00")
                ).astimezone(timezone.utc).timestamp())
                candle = {
                    "time": ts,
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            except (KeyError, ValueError, TypeError):
                continue
            payload = json.dumps({"symbol": ws_symbol, "timeframe": tf_key, "candle": candle})
            for client_ws, (client_symbol, _) in self._clients.items():
                if client_symbol != ws_symbol:
                    continue
                try:
                    await client_ws.send_text(payload)
                except Exception:
                    dead.append(client_ws)
        for d in dead:
            self._clients.pop(d, None)


kraken_stream_manager = KrakenStreamManager()
