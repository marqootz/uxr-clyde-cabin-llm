"""Claude agent with vehicle control tools and ride context injection."""

import asyncio
import json
import logging
import shutil
from typing import Any

import anthropic
import httpx

from agent.context import RideContext
from agent import display_server
from agent import spotify_client
import config

logger = logging.getLogger(__name__)

VEHICLE_BASE = f"http://127.0.0.1:{config.VEHICLE_API_PORT}"

TOOLS = [
    {
        "name": "set_lights",
        "description": "Set cabin lighting brightness (0-100) and color temperature (warm, neutral, cool).",
        "input_schema": {
            "type": "object",
            "properties": {
                "brightness": {"type": "integer", "description": "0-100"},
                "color_temp": {"type": "string", "description": "warm | neutral | cool"},
            },
            "required": ["brightness", "color_temp"],
        },
    },
    {
        "name": "set_climate",
        "description": "Set cabin temperature (F) and fan speed (off, low, medium, high, auto).",
        "input_schema": {
            "type": "object",
            "properties": {
                "temp_f": {"type": "integer", "description": "Temperature in Fahrenheit"},
                "fan_speed": {"type": "string", "description": "off | low | medium | high | auto"},
            },
            "required": ["temp_f", "fan_speed"],
        },
    },
    {
        "name": "set_audio",
        "description": "Play, pause, or stop cabin music through the vehicle speakers (same as the agent voice). Use when the user asks for music and Spotify is not configured or spotify_play failed. Call with action='play' and optional genre (e.g. jazz, classical, lo-fi).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "play | pause | stop"},
                "genre": {"type": "string", "description": "Optional: ambient, jazz, classical, lo-fi, or other genre when action is play"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_ride_info",
        "description": "Get current ride context (route, stops, ETA, cabin state). No parameters.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_display",
        "description": "Update the cabin display. layout: idle | speaking | status | arrival. data: dict of layout-specific fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layout": {"type": "string", "description": "idle | speaking | status | arrival"},
                "data": {"type": "object", "description": "Layout-specific key-value pairs"},
            },
            "required": ["layout", "data"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get current weather for a location. Use when the user asks about weather, temperature, or conditions. location is optional; if omitted, use the default area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City or place name (e.g. San Francisco), or leave empty for default"},
            },
        },
    },
    {
        "name": "spotify_play",
        "description": "Search Spotify and start playback (playlist or track). Use whenever the user asks to play music (e.g. 'play jazz', 'put on some music') if Spotify is available; no need for them to say 'on Spotify'. Fall back to set_audio only if Spotify is not configured or returns an error. Requires Spotify Premium and the cabin display tab connected as a Spotify device.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query: genre (e.g. jazz, lo-fi), song name, artist, or playlist name"},
                "type": {"type": "string", "description": "playlist | track | album | artist. Default playlist for genres, track for specific songs."},
            },
            "required": ["query"],
        },
    },
]

SYSTEM_PROMPT_TEMPLATE = """You are the in-cabin voice assistant for a small autonomous public transit vehicle. You are calm, brief, and co-pilot in tone. Keep responses to 2 sentences max unless the user asks for more. Your replies are spoken aloud; use minimal punctuation so the voice does not pause or read punctuation oddly. Do not ask follow-up questions unless strictly necessary. When you take an action (lights, climate, audio), confirm briefly in speech and use send_display to push a status card.

Current ride context (JSON):
{context_json}

Proactive offers already made this ride (do not repeat these): {offers_made}

When taking an action, always call send_display with layout "status" and a short title/detail so the passenger sees confirmation on the display.

When the user asks about weather or temperature, call get_weather (with optional location) and report the result briefly.
When the user asks to play music (e.g. 'play jazz', 'put on music'), use spotify_play first (query = genre or request); if it returns an error, use set_audio with action 'play' and genre. You do not need the user to say 'on Spotify' — prefer Spotify whenever they ask for music.

Important: After every tool call you must reply with at least one short spoken sentence. After get_weather, say the temperature and conditions. After set_audio (play) or spotify_play (success), reply with only 'Playing.' or 'Done.' — nothing else (no playlist name, no ride commentary like 'enjoy the music on your ride'). If a tool returns an error, say that in one short sentence. Never end your turn with no text after using a tool.

Accuracy: Your spoken reply must match the actual tool result. If a tool returns an "error" or a "note" (e.g. no stream configured, Spotify not connected), do not claim success. Say what the tool reported in one short sentence (e.g. "Spotify isn't connected — open the cabin display to hear music there." or "Cabin audio isn't set up for streaming; I've updated the display.")."""


# Open-Meteo: no API key, free
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> short description (subset)
WMO_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail",
}


async def _fetch_weather(location: str) -> dict:
    """Resolve location to lat/lon (Open-Meteo geocoding), then fetch current weather."""
    lat, lon = None, None
    if location and "," in location:
        parts = location.strip().split(",")
        if len(parts) >= 2:
            try:
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                pass
    if lat is None:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(GEOCODE_URL, params={"name": location or config.WEATHER_DEFAULT_LOCATION, "count": 1})
            r.raise_for_status()
            data = r.json()
        results = data.get("results") or []
        if not results:
            return {"error": f"Could not find location: {location}"}
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        location = results[0].get("name", location)
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            },
        )
        r.raise_for_status()
        data = r.json()
    cur = data.get("current") or {}
    temp_c = cur.get("temperature_2m")
    code = cur.get("weather_code", 0)
    desc = WMO_CODES.get(code, "conditions")
    temp_f = round((temp_c * 9 / 5) + 32) if temp_c is not None else None
    return {
        "location": location,
        "temperature_f": temp_f,
        "temperature_c": temp_c,
        "conditions": desc,
        "humidity_percent": cur.get("relative_humidity_2m"),
        "wind_kmh": cur.get("wind_speed_10m"),
    }


_music_process: asyncio.subprocess.Process | None = None


def _stop_music_playback() -> None:
    global _music_process
    if _music_process is not None:
        try:
            _music_process.terminate()
        except Exception:
            pass
        _music_process = None


def _is_remote_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


async def _start_music_playback(url: str | None = None) -> None:
    """Play the given stream URL in background. Remote URLs need ffplay (afplay does not support HTTP/HTTPS on macOS)."""
    global _music_process
    _stop_music_playback()
    if not url:
        url = config.MUSIC_STREAM_URL or getattr(config, "DEFAULT_MUSIC_STREAM_URL", "") or ""
    if not url:
        logger.warning("No stream URL configured; cabin music will not play. Set MUSIC_STREAM_URL or DEFAULT_MUSIC_STREAM_URL in .env")
        return
    try:
        if _is_remote_url(url):
            # afplay does not support HTTP/HTTPS on macOS; use ffplay for streams (reconnect so brief drops don't stop playback)
            if shutil.which("ffplay"):
                logger.info("Starting cabin music: %s (ffplay)", url[:60] + "..." if len(url) > 60 else url)
                _music_process = await asyncio.create_subprocess_exec(
                    "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                    "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "2000",
                    "-i", url,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _log_music_stderr(_music_process)
            else:
                logger.warning(
                    "Cabin music requires ffplay for stream URLs. Install ffmpeg: brew install ffmpeg. "
                    "Then restart the agent and say 'play jazz' again."
                )
        else:
            # Local file: use afplay on macOS
            if shutil.which("afplay"):
                logger.info("Starting cabin music: %s (afplay)", url[:60] + "..." if len(url) > 60 else url)
                _music_process = await asyncio.create_subprocess_exec(
                    "afplay", url,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _log_music_stderr(_music_process)
            elif shutil.which("ffplay"):
                logger.info("Starting cabin music: %s (ffplay)", url[:60] + "..." if len(url) > 60 else url)
                _music_process = await asyncio.create_subprocess_exec(
                    "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                    "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "2000",
                    "-i", url,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _log_music_stderr(_music_process)
            else:
                logger.warning("No afplay or ffplay found; cabin music will not play.")
    except Exception as e:
        logger.warning("Music playback failed: %s", e)


def _log_music_stderr(process: asyncio.subprocess.Process) -> None:
    """If the music process exits with an error, log its stderr."""
    async def _read() -> None:
        code = await process.wait()
        err = ""
        if process.stderr:
            err = (await process.stderr.read()).decode(errors="replace").strip()
        if code != 0 and (err or code != 0):
            logger.warning("Cabin music process exited %s: %s", code, (err or "(no stderr)")[:300])

    asyncio.create_task(_read())


async def _call_vehicle(path: str, method: str = "GET", body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        if method == "GET":
            r = await client.get(VEHICLE_BASE + path)
        else:
            r = await client.post(VEHICLE_BASE + path, json=body or {})
        r.raise_for_status()
        return r.json()


async def execute_tool(name: str, arguments: dict[str, Any], ctx: RideContext) -> str:
    """Execute one tool and return a string result for Claude."""
    try:
        if name == "set_lights":
            out = await _call_vehicle("/lights", "POST", arguments)
            return json.dumps(out)
        if name == "set_climate":
            out = await _call_vehicle("/climate", "POST", arguments)
            return json.dumps(out)
        if name == "set_audio":
            out = await _call_vehicle("/audio", "POST", arguments)
            action = (arguments.get("action") or "").strip().lower()
            if action == "play":
                play_url = config.MUSIC_STREAM_URL or getattr(config, "DEFAULT_MUSIC_STREAM_URL", "") or ""
                if play_url:
                    asyncio.create_task(_start_music_playback(play_url))
                else:
                    out["note"] = (
                        "No audio will play from cabin speakers: no stream URL configured. "
                        "Set MUSIC_STREAM_URL or DEFAULT_MUSIC_STREAM_URL in .env, or open the cabin display and connect Spotify."
                    )
            elif action in ("pause", "stop"):
                _stop_music_playback()
            return json.dumps(out)
        if name == "get_ride_info":
            return json.dumps({
                "route_name": ctx.route_name,
                "current_stop": ctx.current_stop,
                "next_stop": ctx.next_stop,
                "eta_seconds": ctx.eta_seconds,
                "ride_duration_seconds": ctx.ride_duration_seconds,
                "elapsed_seconds": ctx.elapsed_seconds,
                "hour_of_day": ctx.hour_of_day,
                "passenger_count": ctx.passenger_count,
                "cabin": ctx.cabin.to_dict(),
            })
        if name == "send_display":
            layout = arguments.get("layout", "idle")
            data = arguments.get("data") or {}
            await display_server.send_layout(layout, data)
            return json.dumps({"ok": True, "layout": layout})
        if name == "get_weather":
            location = (arguments.get("location") or config.WEATHER_DEFAULT_LOCATION).strip()
            result = await _fetch_weather(location)
            return json.dumps(result)
        if name == "spotify_play":
            query = (arguments.get("query") or "").strip()
            if not query:
                return json.dumps({"error": "query is required"})
            kind = (arguments.get("type") or "playlist").strip().lower()
            if kind not in ("playlist", "track", "album", "artist"):
                kind = "playlist"
            device_id = config.SPOTIFY_DEVICE_ID or None
            result = await spotify_client.search_and_play(query, type=kind, device_id=device_id)
            return json.dumps(result)
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        logger.exception("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})


def _build_system_prompt(ctx: RideContext, offers_made: list[str]) -> str:
    import json as _json
    context_dict = {
        "route_name": ctx.route_name,
        "current_stop": ctx.current_stop,
        "next_stop": ctx.next_stop,
        "eta_seconds": ctx.eta_seconds,
        "ride_duration_seconds": ctx.ride_duration_seconds,
        "elapsed_seconds": ctx.elapsed_seconds,
        "hour_of_day": ctx.hour_of_day,
        "passenger_count": ctx.passenger_count,
        "cabin": ctx.cabin.to_dict(),
    }
    context_json = _json.dumps(context_dict, indent=2)
    return SYSTEM_PROMPT_TEMPLATE.format(
        context_json=context_json,
        offers_made=", ".join(offers_made) or "none",
    )


async def run_turn(
    user_message: str,
    ctx: RideContext,
    offers_made: list[str],
    conversation: list[dict],
) -> tuple[str, list[dict]]:
    """
    Send user message to Claude with context and tools; execute tool calls and loop until done.
    Returns (final assistant text for TTS, updated conversation messages).
    """
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    system = _build_system_prompt(ctx, offers_made)
    messages = conversation + [{"role": "user", "content": user_message}]
    final_text = ""
    tools_executed = 0

    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=TOOLS,
            tool_choice={"type": "auto"},
        )

        if response.stop_reason == "end_turn":
            final_text = _text_from_content(response.content)
            if not final_text.strip() and tools_executed > 0:
                logger.warning("Model ended turn with no text after %d tool(s); not speaking", tools_executed)
            messages = messages + [
                {"role": "assistant", "content": response.content},
            ]
            break

        if response.stop_reason == "tool_use":
            messages = messages + [{"role": "assistant", "content": response.content}]
            for block in response.content:
                if (isinstance(block, dict) and block.get("type") == "tool_use") or getattr(block, "type", None) == "tool_use":
                    tool_id = block.get("id") if isinstance(block, dict) else block.id
                    name = block.get("name") if isinstance(block, dict) else block.name
                    inp = block.get("input") if isinstance(block, dict) else block.input
                    args = inp if isinstance(inp, dict) else json.loads(inp or "{}")
                    result = await execute_tool(name, args, ctx)
                    tools_executed += 1
                    messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": result}],
                    })
            continue

        # Fallback (unexpected stop_reason)
        final_text = _text_from_content(response.content)
        if not final_text.strip() and tools_executed > 0:
            logger.warning("Model stopped with no text after %d tool(s); not speaking", tools_executed)
        messages = messages + [{"role": "assistant", "content": response.content}]
        break

    out = final_text.strip()
    if not out:
        logger.warning("run_turn returned empty text (tools_executed=%d)", tools_executed)
    return (out, messages)


def _text_from_content(content: list[Any]) -> str:
    """Extract concatenated text from API response content (handles dict and SDK object blocks)."""
    out = []
    for block in content or []:
        if isinstance(block, dict):
            if block.get("type") == "text":
                t = block.get("text")
                if t:
                    out.append(t)
        else:
            if getattr(block, "type", None) == "text":
                t = getattr(block, "text", None)
                if t:
                    out.append(t)
    return "".join(out)


def add_proactive_offer(offers_made: list[str], offer_key: str) -> None:
    """Record that we made this proactive offer so it is not repeated."""
    if offer_key and offer_key not in offers_made:
        offers_made.append(offer_key)
