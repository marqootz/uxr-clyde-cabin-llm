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
