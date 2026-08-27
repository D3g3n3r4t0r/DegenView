import asyncio
import json
import logging

import websockets
from fastapi import WebSocket

from app.mexc_pb.PushDataV3ApiWrapper_pb2 import PushDataV3ApiWrapper
from app.providers.mexc import format_symbol

logger = logging.getLogger("mexc_stream")

WS_URL = "wss://wbs-api.mexc.com/ws"
_CANONICAL_TO_WS_INTERVAL = {
    "1m": "Min1",
    "5m": "Min5",
    "15m": "Min15",
    "30m": "Min30",
    "1h": "Min60",
    "4h": "Hour4",
    "1d": "Day1",
    "1w": "Week1",
    "1M": "Month1",
}
PING_INTERVAL_SECONDS = 20  # well under MEXC's 60s no-data-flow disconnect
RECONNECT_DELAY_SECONDS = 3


class MexcStreamManager:
    """Relays MEXC's public kline WebSocket to connected frontend clients.

    Simplification for this single-user local app: only one (symbol, interval
    set) is "live" at a time. A new client watching a different symbol or a
    different HTF/MTF/LTF interval choice switches the shared upstream
    subscription for everyone.
    """

    def __init__(self) -> None:
        self._clients: dict[WebSocket, tuple[str, tuple]] = {}
        self._active_key: tuple[str, tuple] | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def add_client(self, ws: WebSocket, symbol: str, intervals: dict[str, str]) -> None:
        formatted = format_symbol(symbol)
        key = (formatted, tuple(sorted(intervals.items())))
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
        symbol, interval_items = key
        tf_by_channel = {}
        channels = []
        for tf_key, canonical_interval in interval_items:
            ws_interval = _CANONICAL_TO_WS_INTERVAL.get(canonical_interval)
            if ws_interval is None:
                continue  # synthetic interval (2D/3D/5D) has no native MEXC ws channel
            channel = f"spot@public.kline.v3.api.pb@{symbol}@{ws_interval}"
            channels.append(channel)
            tf_by_channel[channel] = tf_key

        if not channels:
            return  # nothing this leg can stream live; frontend falls back to polling

        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=None) as ws:
                    await ws.send(json.dumps({"method": "SUBSCRIPTION", "params": channels}))
                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    try:
                        async for message in ws:
                            if isinstance(message, str):
                                continue  # subscription ack / control message, nothing to relay
                            await self._handle_message(message, symbol, tf_by_channel)
                    finally:
                        ping_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("MEXC stream error for %s, reconnecting", symbol)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _ping_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            await ws.send(json.dumps({"method": "PING"}))

    async def _handle_message(self, raw: bytes, symbol: str, tf_by_channel: dict[str, str]) -> None:
        wrapper = PushDataV3ApiWrapper()
        try:
            wrapper.ParseFromString(raw)
        except Exception:
            return
        if not wrapper.HasField("publicSpotKline"):
            return
        tf_key = tf_by_channel.get(wrapper.channel)
        if tf_key is None:
            return

        k = wrapper.publicSpotKline
        candle = {
            "time": int(k.windowStart),
            "open": float(k.openingPrice),
            "high": float(k.highestPrice),
            "low": float(k.lowestPrice),
            "close": float(k.closingPrice),
            "volume": float(k.volume),
        }
        payload = json.dumps({"symbol": wrapper.symbol, "timeframe": tf_key, "candle": candle})

        dead: list[WebSocket] = []
        for client_ws, (client_symbol, _) in self._clients.items():
            if client_symbol != symbol:
                continue
            try:
                await client_ws.send_text(payload)
            except Exception:
                dead.append(client_ws)
        for d in dead:
            self._clients.pop(d, None)


mexc_stream_manager = MexcStreamManager()
