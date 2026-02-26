"""Spotify Web API: token refresh, search, start playback. Requires Premium for playback.
Optional: set SPOTIFY_OUTPUT_DEVICE_NAME and install switchaudio-osx (brew install switchaudio-osx)
to route Spotify (cabin tab) audio to the same speakers as the agent. See SPOTIFY_INTEGRATION.md."""

import asyncio
import base64
import logging
import subprocess
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
CABIN_DEVICE_NAME = "Clyde Cabin"


def _basic_auth() -> str:
    raw = f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}"
    return base64.b64encode(raw.encode()).decode()


async def get_access_token() -> str | None:
    """Get a valid access token using refresh token (no cache; tokens expire in 1h)."""
    if not config.SPOTIFY_REFRESH_TOKEN or not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": config.SPOTIFY_REFRESH_TOKEN,
            },
            headers={
                "Authorization": f"Basic {_basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if r.status_code != 200:
        logger.warning("Spotify token refresh failed: %s %s", r.status_code, r.text[:200])
        return None
    data = r.json()
    return data.get("access_token")


async def search(query: str, type: str = "playlist", limit: int = 5) -> dict[str, Any]:
    """Search Spotify. type: track, playlist, album, artist. Returns API response."""
    token = await get_access_token()
    if not token:
        return {"error": "Spotify not configured or token refresh failed"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{API_BASE}/search",
            params={"q": query, "type": type, "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        return {"error": f"Search failed: {r.status_code}"}
    return r.json()


def _first_uri(data: dict, kind: str) -> str | None:
    """Get the first URI from search results. kind is singular: playlist, track, album, artist."""
    key = f"{kind}s"  # playlists, tracks, albums, artists
    items = (data.get(key) or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    if item is None or not isinstance(item, dict):
        return None
    return item.get("uri")


def _log_search_debug(data: dict, kind: str, query: str) -> None:
    """Log why search returned no usable result (for debugging empty/odd API responses)."""
    key = f"{kind}s"
    inner = data.get(key) or {}
    items = inner.get("items") or []
    total = inner.get("total", "?")
    logger.warning(
        "Spotify search q=%r type=%s returned total=%s items=%s; keys=%s",
        query, kind, total, len(items), list(data.keys())
    )


async def get_devices() -> list[dict[str, Any]]:
    """Fetch the user's available Spotify devices (for targeting the cabin)."""
    token = await get_access_token()
    if not token:
        return []
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(
            f"{API_BASE}/me/player/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("devices") or []


async def resolve_cabin_device_id() -> str | None:
    """Return device_id for 'Clyde Cabin' if it appears in the user's devices; otherwise None."""
    devices = await get_devices()
    for d in devices:
        if d and d.get("name") == CABIN_DEVICE_NAME:
            return d.get("id")
    return None


async def play(uri: str, device_id: str | None = None) -> dict[str, Any]:
    """Start playback of a URI (track, playlist, album, artist). Requires Premium and an active device."""
    token = await get_access_token()
    if not token:
        return {"error": "Spotify not configured or token refresh failed"}
    if uri.startswith("spotify:playlist:") or uri.startswith("spotify:album:") or uri.startswith("spotify:artist:"):
        body = {"context_uri": uri}
    else:
        body = {"uris": [uri]}
    params = {}
    if device_id:
        params["device_id"] = device_id
    # Debug: log what we're sending (device_id truncated for logs)
    device_log = (device_id[:12] + "..." if device_id and len(device_id) > 12 else device_id) or "default"
    logger.info("Spotify play: uri=%s device_id=%s", uri, device_log)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.put(
            f"{API_BASE}/me/player/play",
            params=params or None,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 204:
        logger.info("Spotify play: 204 OK (playback started on device; if it stops, check browser console on cabin tab for [Spotify SDK] playback_error / state)")
        return {"ok": True, "uri": uri}
    if r.status_code == 404:
        logger.warning("Spotify play: 404 (no active device). Response: %s", r.text[:150])
        return {"error": "No active Spotify device. Open the cabin display and ensure Spotify is connected."}
    logger.warning("Spotify play: %s %s", r.status_code, r.text[:200])
    return {"error": f"Playback failed: {r.status_code} {r.text[:200]}"}


def _set_system_output_if_configured() -> None:
    """Route macOS system audio to SPOTIFY_OUTPUT_DEVICE_NAME so cabin tab uses cabin speakers. Requires switchaudio-osx."""
    name = getattr(config, "SPOTIFY_OUTPUT_DEVICE_NAME", "") or ""
    if not name:
        return
    logger.info("Spotify: setting system output to %r (from SPOTIFY_OUTPUT_DEVICE_NAME)", name)
    try:
        r = subprocess.run(
            ["SwitchAudioSource", "-s", name],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if r.returncode == 0:
            logger.info("Spotify: system output set to %s", name)
        else:
            err = (r.stderr or r.stdout or "").strip() or "(no message)"
            logger.warning("Spotify: SwitchAudioSource -s %r failed (exit %s): %s", name, r.returncode, err)
            _log_available_audio_sources()
    except FileNotFoundError:
        logger.warning(
            "Spotify: SwitchAudioSource not found. Install with: brew install switchaudio-osx. "
            "Spotify tab audio will use the current system output."
        )
    except Exception as e:
        logger.warning("Spotify: set system output failed: %s", e)


def _log_available_audio_sources() -> None:
    """Log available output device names so user can fix SPOTIFY_OUTPUT_DEVICE_NAME."""
    try:
        r = subprocess.run(
            ["SwitchAudioSource", "-a"],
            capture_output=True,
            timeout=2,
            text=True,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            logger.info("Spotify: available output devices (use exact name in SPOTIFY_OUTPUT_DEVICE_NAME): %s", r.stdout.strip().replace("\n", ", "))
        else:
            logger.info("Spotify: run 'SwitchAudioSource -a' in a terminal to list output device names.")
    except Exception:
        pass


async def search_and_play(query: str, type: str = "playlist", device_id: str | None = None) -> dict[str, Any]:
    """Search for query, take first result, start playback. Returns result for the agent to report."""
    # Route system audio to cabin speakers before playing (macOS: SwitchAudioSource)
    await asyncio.get_running_loop().run_in_executor(None, _set_system_output_if_configured)
    data = await search(query, type=type, limit=5)
    if data.get("error"):
        return data
    uri = _first_uri(data, type)
    # If playlist search returned no items, try track search (e.g. "jazz" can hit rate limits or empty playlist results)
    if not uri and type == "playlist":
        data = await search(query, type="track", limit=5)
        if not data.get("error"):
            uri = _first_uri(data, "track")
            if uri:
                type = "track"
        if not uri:
            _log_search_debug(data, type, query)
            return {"error": f"No {type} found for '{query}'"}
    elif not uri:
        _log_search_debug(data, type, query)
        return {"error": f"No {type} found for '{query}'"}
    # Target cabin device so playback goes to the display tab, not another device
    if not device_id and config.SPOTIFY_DEVICE_ID:
        device_id = config.SPOTIFY_DEVICE_ID
    if not device_id:
        device_id = await resolve_cabin_device_id()
    if device_id:
        logger.info("Spotify: playing to device_id=%s (cabin tab)", device_id[:20] + "..." if len(device_id) > 20 else device_id)
    else:
        logger.warning("Spotify: no cabin device found; playback may go to another Spotify app/tab. Open display/spotify_connect.html and connect.")
    result = await play(uri, device_id=device_id)
    if result.get("ok"):
        name = _get_name(data, type)
        result["name"] = name or query
    return result


def _get_name(data: dict, kind: str) -> str | None:
    key = f"{kind}s"
    items = (data.get(key) or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    if item is None or not isinstance(item, dict):
        return None
    return item.get("name")
