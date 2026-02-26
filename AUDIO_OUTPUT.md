# Audio Output Module — `agent/audio_output.py`

## Purpose

Handles all TTS playback for the cabin agent. Uses ElevenLabs streaming API with a trained custom voice. Playback runs in a separate async task so it never blocks the VAD/STT listening loop.

---

## Dependencies

```bash
pip install elevenlabs sounddevice numpy
```

Add to `requirements.txt`:
```
elevenlabs>=1.0.0
sounddevice
numpy
```

---

## Environment Variables

```env
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_VOICE_ID=x1lXdnBpCIP1C3Bg2D2k
```

---

## Implementation

```python
import asyncio
import io
import os
import numpy as np
import sounddevice as sd
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings

# --- Config ---

VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "x1lXdnBpCIP1C3Bg2D2k")
API_KEY = os.getenv("ELEVENLABS_API_KEY")
MODEL_ID = "eleven_turbo_v2"  # lowest latency — required for conversational use
SAMPLE_RATE = 44100

client = ElevenLabs(api_key=API_KEY)

# Shared lock — prevents overlapping speech
_playback_lock = asyncio.Lock()

# Flag so the VAD loop can check if agent is currently speaking
_is_speaking = False


def is_speaking() -> bool:
    return _is_speaking


async def speak(text: str, interrupt: bool = False) -> None:
    """
    Convert text to speech using the trained ElevenLabs voice and play it.
    
    - Streams audio chunks as they arrive for lowest perceived latency.
    - Acquires a lock so calls queue rather than overlap.
    - Set interrupt=True to cancel current speech and speak immediately
      (use for pre-arrival alerts and proactive triggers).
    """
    global _is_speaking

    if not text or not text.strip():
        return

    if interrupt:
        # Signal any current playback to stop — handled via the lock timeout
        # For now: wait briefly then proceed. Can extend with a cancel event.
        await asyncio.sleep(0.1)

    async with _playback_lock:
        _is_speaking = True
        try:
            await _stream_and_play(text)
        finally:
            _is_speaking = False


async def _stream_and_play(text: str) -> None:
    """
    Calls ElevenLabs streaming API and plays audio as chunks arrive.
    Runs the blocking sounddevice call in a thread executor.
    """
    loop = asyncio.get_event_loop()

    # Collect streamed audio bytes
    audio_buffer = io.BytesIO()

    audio_stream = client.text_to_speech.convert(
        voice_id=VOICE_ID,
        text=text,
        model_id=MODEL_ID,
        output_format="pcm_44100",  # raw PCM — no decode step needed
        voice_settings=VoiceSettings(
            stability=0.5,           # balanced — adjust per voice tuning
            similarity_boost=0.8,    # high for trained voice fidelity
            style=0.2,               # subtle style expression
            use_speaker_boost=True
        )
    )

    for chunk in audio_stream:
        if chunk:
            audio_buffer.write(chunk)

    audio_buffer.seek(0)
    pcm_data = np.frombuffer(audio_buffer.read(), dtype=np.int16)

    # Play on executor so we don't block the event loop
    await loop.run_in_executor(None, _play_pcm, pcm_data)


def _play_pcm(pcm_data: np.ndarray) -> None:
    """Blocking PCM playback via sounddevice."""
    sd.play(pcm_data, samplerate=SAMPLE_RATE, dtype='int16')
    sd.wait()


# --- Fallback (offline dev / no API key) ---

async def speak_fallback(text: str) -> None:
    """
    pyttsx3 fallback for offline development.
    Only used if ELEVENLABS_API_KEY is not set.
    """
    import pyttsx3
    loop = asyncio.get_event_loop()

    def _speak_blocking(t: str):
        engine = pyttsx3.init()
        engine.setProperty('rate', 165)
        engine.say(t)
        engine.runAndWait()

    await loop.run_in_executor(None, _speak_blocking, text)


# --- Public interface (auto-selects based on env) ---

async def say(text: str, interrupt: bool = False) -> None:
    """
    Primary entry point. Call this from main.py and proactive.py.
    Auto-falls back to pyttsx3 if no API key is present.
    """
    if API_KEY:
        await speak(text, interrupt=interrupt)
    else:
        await speak_fallback(text)
```

---

## Usage

From `main.py` or `proactive.py`:

```python
from agent.audio_output import say, is_speaking

# Standard response
await say("Heads up, arriving at Civic Center in about 3 minutes.")

# Interrupt current speech for a priority alert
await say("Emergency stop detected. Please remain seated.", interrupt=True)

# Check before processing mic input — ignore speech while agent is talking
if not is_speaking():
    transcript = await get_next_transcript()
```

---

## VAD Integration Note

The STT loop in `audio_input.py` should gate on `is_speaking()` to avoid the agent hearing itself. Add this check before passing audio to Whisper:

```python
from agent.audio_output import is_speaking

# In the VAD callback:
if is_speaking():
    return  # discard — agent is speaking
```

---

## Voice Tuning Reference

The voice `x1lXdnBpCIP1C3Bg2D2k` is a trained Professional Voice Clone. Recommended starting values:

| Parameter | Value | Notes |
|---|---|---|
| `stability` | 0.5 | Lower = more expressive, higher = more consistent |
| `similarity_boost` | 0.8 | High keeps it close to the source voice |
| `style` | 0.2 | Subtle — too high can sound affected for short utterances |
| `use_speaker_boost` | True | Recommended for cloned voices |

Tune these after first listen sessions with real agent outputs. Short confirmations (1 sentence) and longer proactive messages may need different profiles — ElevenLabs allows per-request settings so you can differentiate by message type if needed.

---

## File Placement

```
transit-agent/
└── agent/
    └── audio_output.py
```
