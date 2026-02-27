"""API keys, device settings, feature flags."""

import os
from pathlib import Path

# Load .env if present (no extra dependency required for minimal setup)
_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    for line in _env.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# API keys
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY: str = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.environ.get("ELEVENLABS_VOICE_ID", "")

# STT
WHISPER_MODEL: str = os.environ.get("WHISPER_MODEL", "base.en")

# Ports
VEHICLE_API_PORT: int = int(os.environ.get("VEHICLE_API_PORT", "8001"))
WS_PORT: int = int(os.environ.get("WS_PORT", "8765"))

# TTS: use ElevenLabs if key set, else pyttsx3
USE_ELEVENLABS: bool = bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID)

# Audio device (override for different host; e.g. ALSA on Linux)
AUDIO_INPUT_DEVICE: int | None = None  # None = default
AUDIO_OUTPUT_DEVICE: int | None = None

# Rider context: "commuter" = brief intro, "demo" = fuller showcase intro
RIDER_TYPE: str = os.environ.get("RIDER_TYPE", "commuter").lower()

# Weather: default location for get_weather when user doesn't specify (city name or "lat,lon")
WEATHER_DEFAULT_LOCATION: str = os.environ.get("WEATHER_DEFAULT_LOCATION", "San Francisco")

# Optional: when set_audio(play) is called, play this stream URL in the background (e.g. internet radio).
# If unset, DEFAULT_MUSIC_STREAM_URL is used so "play music" still produces audio. Override in .env to change or disable.
MUSIC_STREAM_URL: str = os.environ.get("MUSIC_STREAM_URL", "").strip()
# Fallback stream when MUSIC_STREAM_URL is not set (used by set_audio(play)). Set MUSIC_STREAM_URL to "" and this to "" to disable.
DEFAULT_MUSIC_STREAM_URL: str = os.environ.get("DEFAULT_MUSIC_STREAM_URL", "https://streams.kexp.org/kexp128.mp3").strip()

# Spotify (optional): for "play X on Spotify". Requires Premium. Get refresh_token via scripts/spotify_auth.py
SPOTIFY_CLIENT_ID: str = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET: str = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REFRESH_TOKEN: str = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
# Redirect URI for OAuth (must match Spotify Dashboard exactly). Default 127.0.0.1; use localhost if you added that.
SPOTIFY_REDIRECT_URI: str = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8767/callback").strip()
SPOTIFY_DEVICE_ID: str = os.environ.get("SPOTIFY_DEVICE_ID", "").strip()  # optional: cabin display device
# Optional: macOS system audio output device name (SwitchAudioSource). When set, Spotify playback is routed to this device. Run: SwitchAudioSource -a (use exact name; spaces are fine, no quotes needed in .env).
SPOTIFY_OUTPUT_DEVICE_NAME: str = os.environ.get("SPOTIFY_OUTPUT_DEVICE_NAME", "").strip()
SPOTIFY_TOKEN_PORT: int = int(os.environ.get("SPOTIFY_TOKEN_PORT", "8766"))  # for display to get SDK token
USE_SPOTIFY: bool = bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN)

# Flight status (optional): AviationStack free tier, 100 req/month. Get key at https://aviationstack.com/
AVIATIONSTACK_API_KEY: str = os.environ.get("AVIATIONSTACK_API_KEY", "").strip()
