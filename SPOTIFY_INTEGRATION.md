# Spotify Audio Integration — `agent/spotify.py`

## Problem

The Spotify Web API controls playback but does not guarantee which device
plays or that any device is active. A successful API response (HTTP 200)
does not mean audio is playing. Two failure modes:

1. **No active device** — Spotify client not running or not registered
2. **Wrong output device** — Spotify playing to a different audio device
   than the cabin speakers

---

## Dependencies

```bash
pip install spotipy
brew install switchaudio-osx   # macOS only — for forcing audio output device
```

Add to `requirements.txt`:
```
spotipy>=2.23.0
```

---

## Environment Variables

```env
SPOTIPY_CLIENT_ID=your_client_id
SPOTIPY_CLIENT_SECRET=your_client_secret
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback
SPOTIFY_TARGET_DEVICE_NAME=your_speaker_name   # exact name from Spotify devices list
SPOTIFY_OUTPUT_DEVICE_NAME=your_speaker_name   # system audio device name (SwitchAudioSource)
```

Get credentials from https://developer.spotify.com/dashboard

---

## `agent/spotify.py`

```python
# agent/spotify.py

import os
import subprocess
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth

logger = logging.getLogger(__name__)

# --- Config ---

TARGET_DEVICE_NAME = os.getenv("SPOTIFY_TARGET_DEVICE_NAME")
OUTPUT_DEVICE_NAME = os.getenv("SPOTIFY_OUTPUT_DEVICE_NAME")

SCOPE = " ".join([
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
])

# --- Client ---

_sp: spotipy.Spotify | None = None


def get_client() -> spotipy.Spotify:
    global _sp
    if _sp is None:
        _sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIPY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
            scope=SCOPE,
            open_browser=False,
        ))
    return _sp


# --- Device resolution ---

def get_target_device() -> dict | None:
    """
    Returns the best available Spotify playback device.
    Priority:
      1. Device matching SPOTIFY_TARGET_DEVICE_NAME
      2. Currently active device
      3. First available device
    Returns None if no devices are available.
    """
    sp = get_client()
    try:
        devices = sp.devices().get("devices", [])
    except Exception as e:
        logger.error(f"Spotify: failed to fetch devices — {e}")
        return None

    if not devices:
        logger.warning("Spotify: no devices available")
        return None

    if TARGET_DEVICE_NAME:
        named = next(
            (d for d in devices if d["name"].lower() == TARGET_DEVICE_NAME.lower()),
            None
        )
        if named:
            return named

    active = next((d for d in devices if d["is_active"]), None)
    if active:
        return active

    return devices[0]


def list_devices() -> None:
    """
    Debug utility — prints all available Spotify devices.
    Run once to identify the correct SPOTIFY_TARGET_DEVICE_NAME.
    """
    sp = get_client()
    devices = sp.devices().get("devices", [])
    if not devices:
        print("No Spotify devices found. Make sure Spotify is open.")
        return
    print(f"{'ID':<40} {'Name':<30} {'Type':<15} Active")
    print("-" * 90)
    for d in devices:
        print(f"{d['id']:<40} {d['name']:<30} {d['type']:<15} {d['is_active']}")


# --- System audio output ---

def set_system_output(device_name: str) -> bool:
    """
    Forces macOS system audio output to the named device.
    Uses switchaudio-osx (brew install switchaudio-osx).
    Returns True on success.
    """
    try:
        subprocess.run(
            ["SwitchAudioSource", "-s", device_name],
            check=True,
            capture_output=True
        )
        logger.info(f"Spotify: system audio output set to '{device_name}'")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"Spotify: SwitchAudioSource failed — {e}")
        return False
    except FileNotFoundError:
        logger.warning("Spotify: SwitchAudioSource not installed (brew install switchaudio-osx)")
        return False


# --- Playback control ---

async def play(genre: str | None = None, query: str | None = None) -> str:
    """
    Start playback. Searches for a playlist by genre or query string.
    Routes to the correct device and output before playing.

    Returns a status string for the agent to speak/confirm.
    """
    sp = get_client()

    # Ensure system audio is routed correctly
    if OUTPUT_DEVICE_NAME:
        set_system_output(OUTPUT_DEVICE_NAME)

    # Resolve target device
    device = get_target_device()
    if not device:
        return "I can't reach Spotify right now — make sure it's open on this device."

    # Build search query
    search_query = query or f"{genre} music" if genre else "ambient music"

    try:
        results = sp.search(q=search_query, type="playlist", limit=5)
        playlists = results.get("playlists", {}).get("items", [])

        # Filter out None items (Spotify API can return nulls)
        playlists = [p for p in playlists if p]

        if not playlists:
            return f"I couldn't find a playlist for {genre or search_query}."

        # Prefer playlists with higher follower counts (more likely to be quality)
        target_playlist = playlists[0]
        context_uri = target_playlist["uri"]
        playlist_name = target_playlist["name"]

        sp.start_playback(
            device_id=device["id"],
            context_uri=context_uri
        )

        logger.info(f"Spotify: playing '{playlist_name}' on '{device['name']}'")
        return f"Playing {playlist_name}."

    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Spotify playback error: {e}")
        if e.http_status == 403:
            return "Spotify Premium is required for playback control."
        if e.http_status == 404:
            return "I lost track of the Spotify device — try opening Spotify first."
        return "Something went wrong with Spotify."


async def pause() -> str:
    sp = get_client()
    device = get_target_device()
    if not device:
        return "No active Spotify device found."
    try:
        sp.pause_playback(device_id=device["id"])
        return "Music paused."
    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Spotify pause error: {e}")
        return "Couldn't pause Spotify."


async def resume() -> str:
    sp = get_client()
    device = get_target_device()
    if not device:
        return "No active Spotify device found."
    try:
        sp.start_playback(device_id=device["id"])
        return "Resuming music."
    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Spotify resume error: {e}")
        return "Couldn't resume Spotify."


async def set_volume(level: int) -> str:
    """level: 0–100"""
    sp = get_client()
    device = get_target_device()
    if not device:
        return "No active Spotify device found."
    try:
        sp.volume(volume_percent=max(0, min(100, level)), device_id=device["id"])
        return f"Volume set to {level}."
    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Spotify volume error: {e}")
        return "Couldn't adjust the volume."


async def stop() -> str:
    return await pause()
```

---

## Claude Tool Definition

Update `agent/llm.py` to replace the mock audio tool with the real Spotify handler:

```python
# In your tools list:
{
    "name": "set_audio",
    "description": "Control cabin music playback via Spotify. "
                   "Use action='play' with a genre or search query, "
                   "'pause', 'resume', 'stop', or 'volume' with a level 0-100.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action":  { "type": "string", "enum": ["play", "pause", "resume", "stop", "volume"] },
            "genre":   { "type": "string", "description": "Music genre e.g. jazz, ambient, classical" },
            "query":   { "type": "string", "description": "Specific search query if genre isn't enough" },
            "volume":  { "type": "integer", "description": "Volume level 0-100, for action=volume only" }
        },
        "required": ["action"]
    }
}

# Tool call handler:
async def handle_tool_call(name: str, inputs: dict, ws_broadcast) -> str:
    if name == "set_audio":
        action = inputs.get("action")
        if action == "play":
            return await spotify.play(
                genre=inputs.get("genre"),
                query=inputs.get("query")
            )
        elif action == "pause":  return await spotify.pause()
        elif action == "resume": return await spotify.resume()
        elif action == "stop":   return await spotify.stop()
        elif action == "volume":
            return await spotify.set_volume(inputs.get("volume", 50))
    # ... other tools
```

---

## First-Run Setup

**1. Authenticate Spotipy (one-time)**

Spotipy uses OAuth — the first run opens a browser for authorization and
caches the token locally. Run this once manually before using in the agent:

```bash
cd transit-agent
python3 -c "from agent.spotify import get_client; get_client()"
```

Follow the browser prompt, authorize, and the token is cached to
`.spotify_cache` in the project root.

**2. Find your device name**

```bash
python3 -c "from agent.spotify import list_devices; list_devices()"
```

Copy the exact device name into `.env` as `SPOTIFY_TARGET_DEVICE_NAME`.

**3. Find your system audio device name**

```bash
SwitchAudioSource -a   # lists all available system audio output devices
```

Copy the exact name into `.env` as `SPOTIFY_OUTPUT_DEVICE_NAME`.

---

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `No devices available` | Spotify app not open | Open Spotify on the Mac before starting the agent |
| `403 Forbidden` | Free Spotify account | Playback control requires Spotify Premium |
| `404 Not Found` | Device went inactive | Re-open Spotify, re-run device list |
| Audio plays on wrong device | System output not set | Set `SPOTIFY_OUTPUT_DEVICE_NAME` correctly |
| Silent success (no audio) | No active device at play time | Ensure Spotify is open and `list_devices()` shows it |

---

## Linux / Physical Vehicle Notes

`SwitchAudioSource` is macOS only. For Linux, use `pactl`:

```python
def set_system_output_linux(device_name: str) -> bool:
    try:
        subprocess.run(
            ["pactl", "set-default-sink", device_name],
            check=True, capture_output=True
        )
        return True
    except Exception as e:
        logger.warning(f"pactl failed: {e}")
        return False
```

Abstract the call in `spotify.py` behind a platform check:

```python
import platform

def set_system_output(device_name: str) -> bool:
    if platform.system() == "Darwin":
        return _set_output_macos(device_name)
    elif platform.system() == "Linux":
        return _set_output_linux(device_name)
    return False
```

---

## File Placement

```
transit-agent/
└── agent/
    └── spotify.py    ← new
```
