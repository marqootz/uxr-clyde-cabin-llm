"""Small HTTP server that serves the current Spotify access token for the display Web Playback SDK."""

import asyncio
import logging

from aiohttp import web

from agent import spotify_client
import config

logger = logging.getLogger(__name__)


async def handle_spotify_token(request: web.Request) -> web.Response:
    """GET /spotify_token -> JSON { access_token } for the display to init Web Playback SDK."""
    if not config.USE_SPOTIFY:
        resp = web.json_response({"error": "Spotify not configured"}, status=503)
    else:
        token = await spotify_client.get_access_token()
        if not token:
            resp = web.json_response({"error": "Token refresh failed"}, status=503)
        else:
            resp = web.json_response({"access_token": token})
    # Allow browser pages (e.g. http://127.0.0.1:8760/spotify_connect.html) to fetch this
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def run_app(port: int) -> web.Application:
    app = web.Application()
    app.router.add_get("/spotify_token", handle_spotify_token)
    return app


async def run(port: int = 8766) -> None:
    app = run_app(port)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info("Spotify token server on http://127.0.0.1:%d/spotify_token", port)
    await asyncio.Future()  # run forever
