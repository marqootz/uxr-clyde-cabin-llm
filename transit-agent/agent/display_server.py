"""WebSocket server for the 1080×360 cabin display. Broadcasts layout + data to clients."""

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)
_clients: set[WebSocketServerProtocol] = set()


async def register(ws: WebSocketServerProtocol) -> None:
    _clients.add(ws)
    logger.info("Display client connected (total=%d)", len(_clients))


async def unregister(ws: WebSocketServerProtocol) -> None:
    _clients.discard(ws)
    logger.info("Display client disconnected (total=%d)", len(_clients))


async def send_layout(layout: str, data: dict[str, Any]) -> None:
    """Push a layout and its data to all connected display clients."""
    msg = json.dumps({"layout": layout, "data": data})
    if not _clients:
        logger.debug("No display clients; message dropped: %s", layout)
        return
    await asyncio.gather(
        *[client.send(msg) for client in _clients],
        return_exceptions=True,
    )


async def handler(ws: WebSocketServerProtocol, path: str) -> None:
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
