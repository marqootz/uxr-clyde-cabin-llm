"""WebSocket server for the 1080×360 cabin display. Broadcasts layout + data to clients."""

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)
_clients: set[WebSocketServerProtocol] = set()
_client_connected_event: asyncio.Event | None = None
_last_layout: str | None = None
_last_data: dict[str, Any] | None = None


async def register(ws: WebSocketServerProtocol) -> None:
    _clients.add(ws)
    if _client_connected_event is not None:
        _client_connected_event.set()
    # Send current state immediately so new clients get ride data (next_stop, eta) without waiting for the next message
    if _last_layout is not None and _last_data is not None:
        try:
            await ws.send(json.dumps({"layout": _last_layout, "data": _last_data}))
        except Exception:
            pass
    logger.info("Display client connected (total=%d)", len(_clients))


async def wait_for_client(timeout: float = 2.0) -> bool:
    """Wait for at least one display client to connect. Returns True if a client connected, False on timeout."""
    global _client_connected_event
    if _clients:
        return True
    if _client_connected_event is None:
        _client_connected_event = asyncio.Event()
    try:
        await asyncio.wait_for(_client_connected_event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


async def unregister(ws: WebSocketServerProtocol) -> None:
    _clients.discard(ws)
    logger.info("Display client disconnected (total=%d)", len(_clients))


async def broadcast_audio_level(level: float) -> None:
    """Broadcast audio level (0.0–1.0) to all connected display clients for presence animation."""
    if not _clients:
        return
    msg = json.dumps({"type": "audio_level", "value": level})
    await asyncio.gather(
        *[client.send(msg) for client in _clients],
        return_exceptions=True,
    )


async def send_layout(layout: str, data: dict[str, Any]) -> None:
    """Push a layout and its data to all connected display clients. Stores state for late-joining clients."""
    global _last_layout, _last_data
    _last_layout = layout
    _last_data = data
    msg = json.dumps({"layout": layout, "data": data})
    if not _clients:
        logger.debug("No display clients; message dropped: %s", layout)
        return
    if layout == "speaking":
        text_preview = (data.get("text") or "")[:60]
        logger.info("Display send_layout speaking: %s", text_preview + ("..." if len(data.get("text") or "") > 60 else ""))
    await asyncio.gather(
        *[client.send(msg) for client in _clients],
        return_exceptions=True,
    )


async def handler(ws: WebSocketServerProtocol, path: str | None = None) -> None:
    """Connection handler. path is optional for websockets API compatibility."""
    await register(ws)
    try:
        async for _ in ws:
            pass  # display is output-only; ignore incoming
    finally:
        await unregister(ws)


async def run(port: int = 8765) -> None:
    async with websockets.serve(handler, "127.0.0.1", port, ping_interval=20, ping_timeout=10):
        logger.info("Display WebSocket server on ws://127.0.0.1:%d", port)
        await asyncio.Future()  # run forever
