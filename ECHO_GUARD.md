# Echo Guard — `agent/echo_guard.py` + updated `agent/audio_output.py`

## Problem

The always-listening mic pipeline will capture Clyde's own TTS output and treat it as a new user prompt unless explicitly guarded. Three mechanisms work together:

1. **Speaking gate** — discard all audio while TTS is active
2. **Post-speech holdoff** — keep gate closed for a fixed window after TTS ends (cabin reverberation)
3. **Transcript similarity check** — discard transcripts that closely match recent agent speech

---

## `agent/echo_guard.py`

```python
# agent/echo_guard.py
# Manages the speaking gate, holdoff window, and transcript similarity check.
# All audio_input.py and main.py gating goes through this module.

import asyncio
import time
from difflib import SequenceMatcher

# --- Config ---

HOLDOFF_SECONDS = 0.45      # silence window kept after TTS ends (tune per cabin)
ECHO_THRESHOLD = 0.70       # similarity ratio above which a transcript is discarded
RECENT_SPEECH_WINDOW = 5    # number of recent utterances to check against

# --- State ---

_is_speaking: bool = False
_holdoff_until: float = 0.0
_recent_utterances: list[str] = []  # rolling window of recent agent speech


# --- Gate API ---

def set_speaking(active: bool, holdoff: bool = True) -> None:
    """
    Called by audio_output.py when TTS starts and ends.
    When ending (active=False), starts the holdoff timer.
    """
    global _is_speaking, _holdoff_until
    _is_speaking = active
    if not active and holdoff:
        _holdoff_until = time.monotonic() + HOLDOFF_SECONDS


def is_gated() -> bool:
    """
    Returns True if audio input should be discarded.
    Covers both active TTS and the post-speech holdoff window.
    """
    if _is_speaking:
        return True
    if time.monotonic() < _holdoff_until:
        return True
    return False


# --- Transcript similarity check ---

def register_utterance(text: str) -> None:
    """
    Call this every time Clyde speaks. Stores the utterance
    for echo detection on incoming transcripts.
    """
    global _recent_utterances
    _recent_utterances.append(text.lower().strip())
    if len(_recent_utterances) > RECENT_SPEECH_WINDOW:
        _recent_utterances.pop(0)


def is_echo(transcript: str) -> bool:
    """
    Returns True if the transcript closely matches any recent agent utterance.
    Use this as a last line of defense after the gate check.
    """
    if not _recent_utterances or not transcript:
        return False

    t = transcript.lower().strip()

    for utterance in _recent_utterances:
        ratio = SequenceMatcher(None, t, utterance).ratio()
        if ratio >= ECHO_THRESHOLD:
            return True

        # Also check if transcript is a substring of a recent utterance
        # (catches partial captures at the start/end of TTS playback)
        if len(t) > 8 and t in utterance:
            return True

    return False


def clear() -> None:
    """Reset all state — call at the start of each new ride session."""
    global _is_speaking, _holdoff_until, _recent_utterances
    _is_speaking = False
    _holdoff_until = 0.0
    _recent_utterances = []
```

---

## `agent/audio_output.py` (updated)

Changes from previous version:
- Imports and calls `echo_guard.set_speaking()` and `echo_guard.register_utterance()`
- Holdoff is now managed by `echo_guard` rather than a raw `asyncio.sleep`

```python
# agent/audio_output.py

import asyncio
import io
import os
import numpy as np
import sounddevice as sd
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from agent import echo_guard

# --- Config ---

VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "x1lXdnBpCIP1C3Bg2D2k")
API_KEY = os.getenv("ELEVENLABS_API_KEY")
MODEL_ID = "eleven_turbo_v2"
SAMPLE_RATE = 44100

client = ElevenLabs(api_key=API_KEY)

_playback_lock = asyncio.Lock()


async def say(text: str, interrupt: bool = False, ws_broadcast=None) -> None:
    """
    Primary entry point. Speaks text via ElevenLabs, manages echo guard state,
    and optionally broadcasts audio levels to the display via WebSocket.

    Args:
        text:         Text for Clyde to speak.
        interrupt:    If True, attempts to speak over current playback.
        ws_broadcast: Optional async callable to send display messages.
                      Signature: ws_broadcast(dict) -> None
    """
    if not text or not text.strip():
        return

    if API_KEY:
        await _speak_elevenlabs(text, interrupt, ws_broadcast)
    else:
        await _speak_fallback(text)


async def _speak_elevenlabs(text: str, interrupt: bool, ws_broadcast) -> None:
    if interrupt:
        await asyncio.sleep(0.1)

    async with _playback_lock:
        # Register utterance BEFORE speaking so the gate is consistent
        # even if something slips through during the first few ms
        echo_guard.register_utterance(text)
        echo_guard.set_speaking(True)

        try:
            if ws_broadcast:
                await ws_broadcast({"type": "state", "value": "speaking",
                                    "transcript": text})
            await _stream_and_play(text, ws_broadcast)
        finally:
            # Holdoff starts inside set_speaking(False)
            echo_guard.set_speaking(False, holdoff=True)
            if ws_broadcast:
                await ws_broadcast({"type": "state", "value": "idle"})


async def _stream_and_play(text: str, ws_broadcast) -> None:
    loop = asyncio.get_event_loop()
    audio_buffer = io.BytesIO()

    audio_stream = client.text_to_speech.convert(
        voice_id=VOICE_ID,
        text=text,
        model_id=MODEL_ID,
        output_format="pcm_44100",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.8,
            style=0.2,
            use_speaker_boost=True
        )
    )

    for chunk in audio_stream:
        if chunk:
            audio_buffer.write(chunk)

    audio_buffer.seek(0)
    pcm_data = np.frombuffer(audio_buffer.read(), dtype=np.int16)

    # Start amplitude broadcast task if display is connected
    level_task = None
    if ws_broadcast:
        level_task = asyncio.create_task(
            _emit_audio_levels(pcm_data, ws_broadcast)
        )

    await loop.run_in_executor(None, _play_pcm, pcm_data)

    if level_task:
        level_task.cancel()


async def _emit_audio_levels(pcm_data: np.ndarray, ws_broadcast) -> None:
    """
    Emits RMS amplitude values at ~30fps during playback.
    Used to drive the presence animation on the display.
    """
    chunk_size = int(SAMPLE_RATE / 30)  # ~33ms chunks
    total_chunks = len(pcm_data) // chunk_size

    for i in range(total_chunks):
        chunk = pcm_data[i * chunk_size:(i + 1) * chunk_size]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        normalized = min(rms / 8000.0, 1.0)  # tune divisor to voice level
        await ws_broadcast({"type": "audio_level", "value": round(normalized, 3)})
        await asyncio.sleep(0.033)


def _play_pcm(pcm_data: np.ndarray) -> None:
    sd.play(pcm_data, samplerate=SAMPLE_RATE, dtype='int16')
    sd.wait()


async def _speak_fallback(text: str) -> None:
    """pyttsx3 fallback for offline dev — no echo guard needed at this fidelity."""
    import pyttsx3
    loop = asyncio.get_event_loop()

    def _blocking(t):
        engine = pyttsx3.init()
        engine.setProperty('rate', 165)
        engine.say(t)
        engine.runAndWait()

    echo_guard.register_utterance(text)
    echo_guard.set_speaking(True)
    try:
        await loop.run_in_executor(None, _blocking, text)
    finally:
        echo_guard.set_speaking(False, holdoff=True)
```

---

## `agent/audio_input.py` — Gate Integration

The VAD loop checks `echo_guard.is_gated()` before processing any audio frame, and runs `echo_guard.is_echo()` on completed transcripts before yielding them.

```python
# agent/audio_input.py (relevant section)

import asyncio
import numpy as np
import sounddevice as sd
from agent import echo_guard
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
BLOCK_SIZE = 512
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")

model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")


async def transcript_stream():
    """
    Async generator yielding transcripts from mic input.
    Gated by echo_guard — skips audio while Clyde is speaking
    and discards transcripts that match recent agent utterances.
    """
    loop = asyncio.get_event_loop()
    audio_buffer = []
    vad_active = False

    def audio_callback(indata, frames, time_info, status):
        if echo_guard.is_gated():
            return  # discard — Clyde is speaking or in holdoff

        audio_chunk = indata[:, 0].copy()

        nonlocal vad_active, audio_buffer
        is_speech = _vad_is_speech(audio_chunk)

        if is_speech:
            vad_active = True
            audio_buffer.append(audio_chunk)
        elif vad_active:
            # Speech just ended — queue for transcription
            full_audio = np.concatenate(audio_buffer)
            loop.call_soon_threadsafe(
                transcription_queue.put_nowait, full_audio
            )
            audio_buffer = []
            vad_active = False

    transcription_queue = asyncio.Queue()

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype='float32',
        channels=1,
        callback=audio_callback
    ):
        while True:
            audio = await transcription_queue.get()
            transcript = await _transcribe(audio)

            if not transcript:
                continue

            # Last line of defense — similarity check
            if echo_guard.is_echo(transcript):
                continue  # discard — likely agent's own voice

            yield transcript


async def _transcribe(audio: np.ndarray) -> str | None:
    loop = asyncio.get_event_loop()
    segments, _ = await loop.run_in_executor(
        None,
        lambda: model.transcribe(audio, language="en", vad_filter=True)
    )
    text = " ".join(s.text for s in segments).strip()
    return text if text else None


def _vad_is_speech(chunk: np.ndarray) -> bool:
    # Replace with silero-vad inference in production
    # Placeholder: energy-based threshold
    return float(np.abs(chunk).mean()) > 0.01
```

---

## `agent/main.py` — Session Reset

Call `echo_guard.clear()` at the start of each new ride session:

```python
from agent import echo_guard

async def start_ride_session():
    echo_guard.clear()
    # ... rest of session init
```

---

## Tuning Guide

| Parameter | Default | Tune when... |
|---|---|---|
| `HOLDOFF_SECONDS` | 0.45s | Agent hears its own tail / cut-off responses |
| `ECHO_THRESHOLD` | 0.70 | False positives (real user input discarded) or echoes still getting through |
| `RECENT_SPEECH_WINDOW` | 5 | More context needed for echo check vs. memory overhead |
| RMS divisor in `_emit_audio_levels` | 8000 | Waveform animation too flat or clipping |

Test `HOLDOFF_SECONDS` in the actual vehicle — hard cabin surfaces reflect more than a typical room and may need 500–600ms.

---

## File Placement

```
transit-agent/
└── agent/
    ├── echo_guard.py      ← new
    ├── audio_output.py    ← updated
    └── audio_input.py     ← updated (gate integration)
```
